// safe_role.js — Safe Role: บันทึกยศตอนสมาชิกออก แล้วคืนยศให้ตอนกลับเข้ามา (discord.js v14)
// มีแผง UI หน้าตาเหมือนแผงยืนยันตัวตน (Components V2) พร้อมปุ่ม "ดูยศที่บันทึก" / "กู้คืนยศ"
//
// วิธีใช้ใน cat_shop_ticket_bot.js (หลังสร้าง client ที่บรรทัด ~368):
//   const { installSafeRole, SAFE_ROLE_COMMAND } = require("./safe_role");
//   installSafeRole(client, { ownerId: OWNER_ID, em, btnEmoji });
// และเพิ่ม SAFE_ROLE_COMMAND เข้าไปใน c.application.commands.set([ ... ]) ตอน ClientReady
//
// ต้องเปิด Privileged Intent "Server Members" (บอทเปิดอยู่แล้ว: GuildMembers)

const fs = require("fs");
const { Events, PermissionFlagsBits, MessageFlags, Routes } = require("discord.js");

const FILE = "safe_roles.json";
const KEEP_DAYS = 0; // เก็บข้อมูลคนที่ออกไปกี่วัน (0 = เก็บตลอด)
const SKIP_DANGEROUS = true; // ไม่คืนยศที่มีสิทธิ์อันตราย (แอดมิน/จัดการเซิร์ฟ ฯลฯ)
const EXCLUDE_ROLE_IDS = []; // ยศที่ไม่ต้องบันทึก/คืน ใส่ ID เป็น string
const PANEL_IMAGE_URL = "https://i.pinimg.com/736x/73/93/a9/7393a9ba6adaf8e05c9ef5f47fe16e31.jpg"; // รูปในแผง (ไม่ใส่ = ไม่แสดงรูป) ควรใช้ลิงก์ถาวร

const SAFE_ROLE_COMMAND = { name: "ตั้งค่าเซฟยศ", description: "ส่งแผง Safe Role (บันทึก/กู้คืนยศ) ไปยังช่องนี้" };

const DANGEROUS = [
  PermissionFlagsBits.Administrator,
  PermissionFlagsBits.ManageGuild,
  PermissionFlagsBits.ManageRoles,
  PermissionFlagsBits.ManageChannels,
  PermissionFlagsBits.ManageWebhooks,
  PermissionFlagsBits.ManageMessages,
  PermissionFlagsBits.KickMembers,
  PermissionFlagsBits.BanMembers,
  PermissionFlagsBits.ModerateMembers,
  PermissionFlagsBits.MentionEveryone,
].reduce((a, b) => a | b, 0n);

// ───────── เก็บข้อมูล: { guildId: { userId: { roles: [id], at: ms, left: bool } } } ─────────
function load() {
  try {
    if (fs.existsSync(FILE)) return JSON.parse(fs.readFileSync(FILE, "utf-8"));
  } catch (e) {
    console.error("[SAFE-ROLE] อ่านไฟล์ไม่ได้ ใช้ค่าเริ่มต้น:", e.message);
  }
  return {};
}

const data = load();
let dirty = false;

function save() {
  if (!dirty) return;
  dirty = false;
  try {
    const tmp = FILE + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(data));
    fs.renameSync(tmp, FILE); // atomic กันไฟล์พัง
  } catch (e) {
    dirty = true;
    console.error("[SAFE-ROLE] บันทึกไม่สำเร็จ:", e.message);
  }
}

function cleanup() {
  if (!KEEP_DAYS) return;
  const limit = Date.now() - KEEP_DAYS * 86_400_000;
  for (const users of Object.values(data)) {
    for (const [uid, rec] of Object.entries(users)) {
      if (rec.left && rec.at < limit) { delete users[uid]; dirty = true; }
    }
  }
}

function roleIdsOf(member) {
  return [...member.roles.cache.values()]
    .filter((r) => r.id !== member.guild.id && !r.managed && !EXCLUDE_ROLE_IDS.includes(r.id))
    .map((r) => r.id);
}

function snapshot(member, left = false) {
  if (!member?.guild || member.user?.bot) return;
  const users = (data[member.guild.id] ??= {});
  const old = users[member.id];
  if (!left && old?.left) return; // รอคืนยศอยู่ อย่าเขียนทับ
  const ids = roleIdsOf(member);
  // ตอนออก ถ้า cache ว่าง (partial member) ให้คงข้อมูลเดิมไว้
  if (left && !ids.length && old?.roles?.length) {
    old.left = true; old.at = Date.now(); dirty = true;
    return;
  }
  users[member.id] = { roles: ids, at: Date.now(), left };
  dirty = true;
}

// ───────── คืนยศ (ให้เฉพาะยศที่ยังไม่มี และผ่านการตรวจความปลอดภัย) ─────────
async function giveSaved(member) {
  const rec = data[member.guild.id]?.[member.id];
  if (!rec?.roles?.length) return { status: "none", restored: 0, skipped: 0 };

  const guild = member.guild;
  const me = guild.members.me;
  if (!me?.permissions.has(PermissionFlagsBits.ManageRoles)) {
    return { status: "noperm", restored: 0, skipped: rec.roles.length };
  }

  const give = [];
  let skipped = 0;
  for (const id of rec.roles) {
    if (member.roles.cache.has(id)) continue;
    const role = guild.roles.cache.get(id);
    if (
      !role || role.managed || role.id === guild.id ||
      role.comparePositionTo(me.roles.highest) >= 0 ||
      (SKIP_DANGEROUS && (role.permissions.bitfield & DANGEROUS) !== 0n)
    ) { skipped++; continue; }
    give.push(role);
  }

  if (give.length) {
    try {
      await member.roles.add(give, "safe-role: คืนยศที่บันทึกไว้");
    } catch (e) {
      console.error("[SAFE-ROLE] คืนยศไม่สำเร็จ:", e.message);
      return { status: "error", restored: 0, skipped: rec.roles.length };
    }
  }
  rec.left = false;
  rec.at = Date.now();
  dirty = true;
  return { status: "ok", restored: give.length, skipped };
}

// ───────── UI (หน้าตาเหมือนแผงยืนยันตัวตน: Container + ข้อความ + เส้นคั่น + ปุ่ม) ─────────
function makeUi(opts) {
  const em = opts.em ? (k) => opts.em(k) + " " : () => "";
  const btnEmoji = (k) => (opts.btnEmoji ? { emoji: opts.btnEmoji(k) } : {});

  function panelPayload() {
    const parts = [
      {
        type: 10,
        content:
          `# ${em("verify")}Safe Role\n\n` +
          "บอทจะจำยศของคุณไว้ แม้ออกจากเซิร์ฟเวอร์ เมื่อกลับเข้ามาจะได้ยศคืนอัตโนมัติ\n" +
          "หากยศไม่กลับมา กดปุ่มด้านล่างเพื่อกู้คืนได้เอง",
      },
      { type: 14, spacing: 2 },
    ];
    if (PANEL_IMAGE_URL) {
      parts.push({ type: 12, items: [{ media: { url: PANEL_IMAGE_URL } }] }, { type: 14, spacing: 2 });
    }
    parts.push(
      {
        type: 1,
        components: [
          { type: 2, style: 3, label: "กู้คืนยศ", ...btnEmoji("verify"), custom_id: "saferole_restore" },
          { type: 2, style: 2, label: "ดูยศที่บันทึก", ...btnEmoji("shield"), custom_id: "saferole_view" },
        ],
      },
      { type: 14, spacing: 1 },
      { type: 10, content: "-# Developed by bob" }
    );
    return { flags: MessageFlags.IsComponentsV2, components: [{ type: 17, components: parts }] };
  }

  const replyPayload = (title, body) => ({
    flags: MessageFlags.Ephemeral | MessageFlags.IsComponentsV2,
    components: [
      {
        type: 17,
        components: [{ type: 10, content: `# ${em("verify")}${title}\n\n${body}` }],
      },
    ],
  });

  return { panelPayload, replyPayload };
}

// ───────── ติดตั้งกับ client ─────────
function installSafeRole(client, opts = {}) {
  const ui = makeUi(opts);

  setInterval(() => { cleanup(); save(); }, 30_000);
  for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { save(); });

  client.once(Events.ClientReady, async () => {
    for (const guild of client.guilds.cache.values()) {
      try {
        const members = await guild.members.fetch();
        for (const m of members.values()) snapshot(m);
      } catch (e) {
        console.error("[SAFE-ROLE] ดึงสมาชิกไม่สำเร็จ:", e.message);
      }
    }
    save();
    console.log("🛡️ safe-role พร้อมทำงาน");
  });

  client.on(Events.GuildMemberUpdate, (oldM, newM) => {
    if (oldM.roles.cache.size === newM.roles.cache.size &&
        oldM.roles.cache.every((_, id) => newM.roles.cache.has(id))) return;
    snapshot(newM);
  });

  client.on(Events.GuildMemberRemove, (member) => {
    snapshot(member, true);
    save();
  });

  client.on(Events.GuildMemberAdd, async (member) => {
    if (member.user.bot) return;
    const rec = data[member.guild.id]?.[member.id];
    if (!rec?.left) return;
    const r = await giveSaved(member).catch((e) => {
      console.error("[SAFE-ROLE]", e.message);
      return null;
    });
    if (r?.restored) console.log(`[SAFE-ROLE] คืน ${r.restored} ยศให้ ${member.user.tag} (ข้าม ${r.skipped})`);
    save();
  });

  // คำสั่งส่งแผง + ปุ่มบนแผง (listener แยก ไม่ชนกับ handler หลักของบอท)
  client.on(Events.InteractionCreate, async (interaction) => {
    try {
      if (interaction.isChatInputCommand() && interaction.commandName === SAFE_ROLE_COMMAND.name) {
        if (opts.ownerId && interaction.user.id !== opts.ownerId) {
          return interaction.reply({ content: "❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", flags: MessageFlags.Ephemeral });
        }
        await interaction.deferReply({ flags: MessageFlags.Ephemeral });
        try {
          await client.rest.post(Routes.channelMessages(interaction.channelId), { body: ui.panelPayload() });
          return interaction.editReply("✅ ส่งแผง Safe Role เรียบร้อยแล้ว");
        } catch (e) {
          console.error("[SAFE-ROLE PANEL]", e.status, e.message);
          return interaction.editReply("❌ ส่งแผงไม่สำเร็จ (ดู log / เช็คสิทธิ์บอทและอีโมจิ)");
        }
      }

      if (!interaction.isButton()) return;

      if (interaction.customId === "saferole_view") {
        const rec = data[interaction.guildId]?.[interaction.user.id];
        const ids = (rec?.roles ?? []).filter((id) => interaction.guild.roles.cache.has(id));
        const body = ids.length
          ? `ยศที่บันทึกไว้ (${ids.length}):\n${ids.map((id) => `<@&${id}>`).join(" ")}`
          : "ยังไม่มียศที่บันทึกไว้";
        return interaction.reply(ui.replyPayload("ยศที่บันทึก", body));
      }

      if (interaction.customId === "saferole_restore") {
        if (!interaction.guild || !interaction.member) {
          return interaction.reply({ content: "❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์", flags: MessageFlags.Ephemeral });
        }
        await interaction.deferReply({ flags: MessageFlags.Ephemeral });
        const r = await giveSaved(interaction.member);
        save();
        let body;
        if (r.status === "none") body = "ยังไม่มียศที่บันทึกไว้ให้กู้คืน";
        else if (r.status === "noperm") body = "❌ บอทไม่มีสิทธิ์ Manage Roles กรุณาแจ้งแอดมิน";
        else if (r.status === "error") body = "❌ กู้คืนไม่สำเร็จ (ยศบอทอาจต่ำกว่ายศที่จะให้) กรุณาแจ้งแอดมิน";
        else if (!r.restored) body = r.skipped ? `ไม่มียศที่กู้คืนได้ (ข้าม ${r.skipped} ยศที่บอทให้ไม่ได้)` : "✅ คุณมียศครบแล้ว ไม่ต้องกู้คืน";
        else body = `✅ กู้คืนยศสำเร็จ ${r.restored} ยศ` + (r.skipped ? `\nข้าม ${r.skipped} ยศที่บอทให้ไม่ได้` : "");
        return interaction.editReply(body);
      }
    } catch (e) {
      console.error("[SAFE-ROLE INTERACTION]", e);
      const msg = { content: "❌ เกิดข้อผิดพลาด ลองใหม่อีกครั้ง", flags: MessageFlags.Ephemeral };
      try {
        if (interaction.deferred || interaction.replied) await interaction.followUp(msg);
        else await interaction.reply(msg);
      } catch {}
    }
  });
}

module.exports = { installSafeRole, SAFE_ROLE_COMMAND, giveSaved, snapshot };
