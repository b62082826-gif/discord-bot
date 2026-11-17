// เครดิต : MC  https://discord.gg/3VRwGSZZZE  (เวอร์ชัน JavaScript / discord.js v14)
// ต้องใช้ Node.js 18+ และ discord.js 14.19+  ->  npm install discord.js
//
// ตั้งค่าโทเค่นผ่าน environment variable:  DISCORD_TOKEN
//   Windows (cmd):  set DISCORD_TOKEN=xxxxx && node cat_shop_ticket_bot.js
//   Linux/Mac:      DISCORD_TOKEN=xxxxx node cat_shop_ticket_bot.js

const fs = require("fs");
const {
  Client,
  GatewayIntentBits,
  Events,
  ChannelType,
  PermissionFlagsBits,
  MessageFlags,
  Routes,
  InteractionType,
} = require("discord.js");

// bot-hosting.net: ใส่โทเค่นใน Environment/Startup variable ชื่อ DISCORD_TOKEN
// หรือสร้างไฟล์ .env ข้าง ๆ ไฟล์นี้ แล้วเขียนบรรทัด  DISCORD_TOKEN=xxxxx  (ต้องใช้ Node 20.12+)
try {
  if (fs.existsSync(".env") && typeof process.loadEnvFile === "function") process.loadEnvFile(".env");
} catch (e) {
  console.error("[ENV] อ่านไฟล์ .env ไม่ได้:", e.message);
}
const BOT_TOKEN = process.env.DISCORD_TOKEN || "";
const OWNER_ID = "1524722784817909811";            // ไอดีเจ้าของที่ใช้คำสั่ง /ตั้งค่าตั๋ว ได้ (ใส่เป็น string)
const BUG_CATEGORY_ID = "1572197960509292644";     // หมวดหมู่ แจ้งบั๊ก
const CONTACT_CATEGORY_ID = "1572198033670545510"; // หมวดหมู่ ติดต่อ

// ลิงก์ cdn.discordapp.com ที่มี ?ex=&is=&hm= จะหมดอายุ -> รูปพัง
// แนะนำใช้ลิงก์รูปถาวร
const TICKET_IMAGE_URL =
  "https://i.pinimg.com/736x/1c/54/2b/1c542b646ec39944d70dc01ea3fe3122.jpg";

const STATE_FILE = "ticket_state.json";
const AUTO_REPLY_COOLDOWN_MS = 60_000;

// ───────────────────────── state ─────────────────────────
function loadState() {
  const state = { bug: 0, contact: 0, disabled: [] };
  try {
    if (fs.existsSync(STATE_FILE)) {
      Object.assign(state, JSON.parse(fs.readFileSync(STATE_FILE, "utf-8")));
    }
  } catch (e) {
    console.error("[STATE] อ่านไฟล์ไม่ได้ ใช้ค่าเริ่มต้น:", e.message);
  }
  return state;
}

const state = loadState();
const disabledChannels = new Set(state.disabled);
const lastAutoReply = new Map();

function saveState() {
  const tmp = STATE_FILE + ".tmp";
  fs.writeFileSync(
    tmp,
    JSON.stringify({ bug: state.bug, contact: state.contact, disabled: [...disabledChannels] })
  );
  fs.renameSync(tmp, STATE_FILE); // เขียนแบบ atomic กันไฟล์พัง
}

// ───────────────────────── client ─────────────────────────
const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent, // ต้องเปิด Privileged Intent ใน Developer Portal
    GatewayIntentBits.GuildMembers,   // ต้องเปิด Privileged Intent ใน Developer Portal
  ],
});

async function sendRaw(channelId, body) {
  try {
    await client.rest.post(Routes.channelMessages(channelId), { body });
    return true;
  } catch (e) {
    console.error("[API ERROR]", e.status, e.message);
    return false;
  }
}

// ───────────────────────── keyword ─────────────────────────
function isBugRelated(text) {
  // ใช้ \b กันติดคำอื่น เช่น debug / bugle
  return /บั๊ก|บัค|บัก|ข้อผิดพลาด|พัง|\b(bug|error)\b/i.test(text);
}

const PARTNER_KEYWORDS = [
  "พาทเนอร์", "พาทเนอ", "พาตเนอ", "พาตเนอร์", "พาทเน", "partner",
  "partener", "parner", "พาทเนร์", "พาทเนะ", "พาร์ทเนอร์",
];

function levenshteinSimilarity(a, b) {
  const m = a.length, n = b.length;
  if (!m || !n) return 0;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) {
      cur[j] = Math.min(
        prev[j] + 1,
        cur[j - 1] + 1,
        prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)
      );
    }
    prev = cur;
  }
  return 1 - prev[n] / Math.max(m, n);
}

function isPartnerRelated(text) {
  const lowered = text.toLowerCase();
  const normalized = lowered.replace(/\s+/g, "");
  if (PARTNER_KEYWORDS.some((kw) => normalized.includes(kw))) return true;
  return lowered
    .split(/\s+/)
    .some(
      (w) =>
        w.length >= 5 &&
        ["พาทเนอร์", "partner"].some((t) => levenshteinSimilarity(w, t) >= 0.8)
    );
}

// ───────────────────────── payloads ─────────────────────────
function buildTicketPanelPayload() {
  const content = [
    "# <:cuteee_684132194347909236:1512881767013683390> ยินดีต้อนรับสู่ระบบตั๋ว Support",
    "",
    "กรุณาแจ้งรายละเอียดที่ต้องการให้ครบถ้วน เพื่อให้ทีมงานสามารถตอบกลับและให้บริการได้รวดเร็วยิ่งขึ้น",
    "",
    "<a:1058991530632818788:1511136593015210104> **กฎการใช้บริการ**",
    ...[
      "กรุณาพูดคุยด้วยถ้อยคำสุภาพ",
      "ห้ามสแปมหรือแท็กทีมงานซ้ำ ๆ",
      "กรุณารอทีมงานตอบกลับตามลำดับคิว",
      "เมื่อได้รับงานแล้ว กรุณาตรวจสอบงานให้เรียบร้อยก่อนปิดตั๋ว",
      "หากมีการแก้ไขเพิ่มเติมหลังส่งงาน อาจมีค่าใช้จ่ายเพิ่มเติมตามความเหมาะสม",
    ].map((s) => `<a:chech_bw:1511137765335498925> ${s}`),
    "",
    "<a:green_cycle:1496813384497102949> เวลาทำการ",
    "เปิดให้บริการทุกวัน โดยทีมงานจะพยายามตอบกลับให้เร็วที่สุด",
    "",
    "<a:leftwing:1511122222587314186> ขอบคุณที่เลือกใช้บริการ Support <a:rightwing:1511122610937659413>",
    "หากต้องการสั่งทำบอทหรือสอบถามรายละเอียดเพิ่มเติม สามารถแจ้งข้อมูลไว้ในตั๋วนี้ได้เลย ทีมงานจะเข้ามาดูแลคุณโดยเร็วที่สุด",
  ].join("\n");

  return {
    flags: MessageFlags.IsComponentsV2,
    components: [
      {
        type: 17, // Container
        components: [
          { type: 10, content }, // TextDisplay
          { type: 14, spacing: 2 }, // Separator
          { type: 12, items: [{ media: { url: TICKET_IMAGE_URL } }] }, // MediaGallery
          { type: 14, spacing: 2 },
          {
            type: 1, // ActionRow
            components: [
              {
                type: 2, style: 4, label: "แจ้งบั๊ก",
                emoji: { name: "🐞" },
                custom_id: "ticket_bug",
              },
              {
                type: 2, style: 2, label: "ติดต่อ",
                emoji: { id: "1496519201215742072", name: "emoji_39", animated: true },
                custom_id: "ticket_contact",
              },
            ],
          },
          { type: 14, spacing: 1 },
          { type: 10, content: "-# Developed by bob" },
        ],
      },
    ],
  };
}

function buildWelcomePayload(openerId, extra = "") {
  return {
    content:
      "# <a:leftwing:1511122222587314186> ยินดีต้อนรับคับ <a:rightwing:1511122610937659413>\n" +
      `คนเปิดตั๋ว <@${openerId}> รอแอดมินมาตอบนะงับ` +
      (extra ? `\n\n${extra}` : ""),
    components: [
      {
        type: 1,
        components: [{ type: 2, style: 4, label: "🔒 ปิดตั๋ว", custom_id: "close_ticket" }],
      },
    ],
  };
}

// ───────────────────────── ticket ─────────────────────────
function isStaff(member) {
  return (
    !!member?.permissions &&
    (member.permissions.has(PermissionFlagsBits.Administrator) ||
      member.permissions.has(PermissionFlagsBits.ManageChannels))
  );
}

/** คืนค่า { channel } หรือ { error } */
async function createTicketChannel(guild, opener, categoryId, type) {
  const category = guild.channels.cache.get(categoryId);
  if (!category || category.type !== ChannelType.GuildCategory) {
    return { error: "ไม่พบหมวดหมู่ตั๋ว (ตั้งค่า ID ผิด) กรุณาแจ้งแอดมิน" };
  }

  // กันเปิดตั๋วซ้ำ (เก็บ owner ไว้ใน topic ใช้ได้หลังรีสตาร์ท)
  const topic = `ticket:${type}:${opener.id}`;
  const existing = category.children.cache.find((c) => c.topic === topic);
  if (existing) return { error: `คุณมีตั๋วที่เปิดอยู่แล้ว → ${existing}` };

  const allow = [
    PermissionFlagsBits.ViewChannel,
    PermissionFlagsBits.SendMessages,
    PermissionFlagsBits.AttachFiles,
    PermissionFlagsBits.ReadMessageHistory,
  ];
  const permissionOverwrites = [
    { id: guild.roles.everyone.id, deny: [PermissionFlagsBits.ViewChannel] },
    { id: opener.id, allow },
    {
      id: client.user.id,
      allow: [...allow, PermissionFlagsBits.ManageChannels],
    },
  ];
  for (const role of guild.roles.cache.values()) {
    if (role.id === guild.id) continue; // ข้าม @everyone
    if (
      role.permissions.has(PermissionFlagsBits.Administrator) ||
      role.permissions.has(PermissionFlagsBits.ManageChannels)
    ) {
      permissionOverwrites.push({
        id: role.id,
        allow: [...allow, PermissionFlagsBits.ManageChannels],
      });
    }
  }

  state[type] += 1;
  saveState();
  const num = String(state[type]).padStart(2, "0");
  // ใช้ username (a-z0-9_) แทน displayName กันชื่อห้องเพี้ยน/ยาวเกิน
  const slug =
    opener.user.username.toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 80) || opener.id;

  try {
    const channel = await guild.channels.create({
      name: `${slug}-${num}`,
      type: ChannelType.GuildText,
      parent: categoryId,
      topic,
      permissionOverwrites,
    });
    return { channel };
  } catch (e) {
    console.error("[TICKET] สร้างห้องไม่สำเร็จ:", e.message);
    if (e.code === 50013) {
      return { error: "บอทไม่มีสิทธิ์สร้างห้อง (ต้องมี Manage Channels) กรุณาแจ้งแอดมิน" };
    }
    return { error: "สร้างตั๋วไม่สำเร็จ ลองใหม่อีกครั้ง" };
  }
}

async function handleOpenTicket(interaction, categoryId, type) {
  await interaction.deferReply({ flags: MessageFlags.Ephemeral });
  if (!interaction.guild || !interaction.member) {
    return interaction.editReply("❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์");
  }
  const { channel, error } = await createTicketChannel(
    interaction.guild, interaction.member, categoryId, type
  );
  if (error) return interaction.editReply(`❌ ${error}`);

  const extra =
    type === "bug"
      ? "🐞 **กรุณาแจ้งรายละเอียดบั๊ก**\n" +
        "• บั๊กเกิดที่ไหน / คำสั่งหรือระบบอะไร\n" +
        "• ขั้นตอนที่ทำให้เกิดบั๊ก\n" +
        "• สิ่งที่คาดหวัง และสิ่งที่เกิดขึ้นจริง\n" +
        "• แนบภาพหน้าจอหรือวิดีโอ (ถ้ามี)"
      : "";
  await sendRaw(channel.id, buildWelcomePayload(interaction.user.id, extra));
  return interaction.editReply(`✅ เปิดตั๋วแล้ว! → ${channel}`);
}

// ───────────────────────── events ─────────────────────────
client.once(Events.ClientReady, async (c) => {
  await c.application.commands.set([
    { name: "ตั้งค่าตั๋ว", description: "ส่งแผงระบบตั๋วไปยังช่องนี้" },
  ]);
  console.log(`✅ บอทออนไลน์แล้ว: ${c.user.tag} (ID: ${c.user.id})`);
});

client.on(Events.InteractionCreate, async (interaction) => {
  try {
    // /ตั้งค่าตั๋ว
    if (interaction.isChatInputCommand() && interaction.commandName === "ตั้งค่าตั๋ว") {
      if (interaction.user.id !== OWNER_ID) {
        return interaction.reply({
          content: "❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
          flags: MessageFlags.Ephemeral,
        });
      }
      await interaction.deferReply({ flags: MessageFlags.Ephemeral });
      const ok = await sendRaw(interaction.channelId, buildTicketPanelPayload());
      return interaction.editReply(
        ok
          ? "✅ ส่งแผงตั๋วเรียบร้อยแล้ว"
          : "❌ ส่งแผงไม่สำเร็จ (ดู log / เช็คสิทธิ์บอทและอีโมจิ)"
      );
    }

    if (interaction.type !== InteractionType.MessageComponent) return;

    switch (interaction.customId) {
      case "ticket_bug":
        return await handleOpenTicket(interaction, BUG_CATEGORY_ID, "bug");
      case "ticket_contact":
        return await handleOpenTicket(interaction, CONTACT_CATEGORY_ID, "contact");
      case "close_ticket":
        if (!isStaff(interaction.member)) {
          return interaction.reply({
            content: "❌ คุณไม่มีสิทธิ์ปิดตั๋วนี้",
            flags: MessageFlags.Ephemeral,
          });
        }
        await interaction.reply({ content: "🔒 กำลังปิดตั๋ว...", flags: MessageFlags.Ephemeral });
        return await interaction.channel.delete(`ปิดตั๋วโดย ${interaction.user.tag}`);
    }
  } catch (e) {
    console.error("[INTERACTION ERROR]", e);
    const msg = { content: "❌ เกิดข้อผิดพลาด ลองใหม่อีกครั้ง", flags: MessageFlags.Ephemeral };
    try {
      if (interaction.deferred || interaction.replied) await interaction.followUp(msg);
      else await interaction.reply(msg);
    } catch {}
  }
});

client.on(Events.MessageCreate, async (message) => {
  if (message.author.bot || !message.guild) return;

  if (message.content.trim() === "!ปิดระบบ") {
    if (!isStaff(message.member)) return message.reply("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้");
    disabledChannels.add(message.channelId);
    saveState();
    return message.reply("🔕 ปิดระบบตอบอัตโนมัติในห้องนี้แล้ว");
  }

  const channel = message.channel;
  if (
    disabledChannels.has(channel.id) ||
    channel.type !== ChannelType.GuildText ||
    !channel.parentId ||
    isStaff(message.member) // ไม่ตอบข้อความของแอดมินเอง
  ) return;

  const now = Date.now();
  if (now - (lastAutoReply.get(channel.id) ?? 0) < AUTO_REPLY_COOLDOWN_MS) return;

  let reply = null;
  if (channel.parentId === BUG_CATEGORY_ID && isBugRelated(message.content)) {
    reply = "รับเรื่องแล้วงับ รบกวนแจ้งขั้นตอนที่ทำให้เกิดบั๊ก พร้อมภาพหน้าจอ (ถ้ามี) รอแอดมินมาตรวจสอบนะคับ";
  } else if (channel.parentId === CONTACT_CATEGORY_ID && isPartnerRelated(message.content)) {
    reply = "ส่งลิ้งและพร้อมอธิบายเซิร์ฟเวอร์ของท่านได้เลย รอแอดมินมาอนุมัตินะคับ";
  }
  if (reply) {
    lastAutoReply.set(channel.id, now);
    await message.reply(reply).catch((e) => console.error("[REPLY ERROR]", e.message));
  }
});

if (!BOT_TOKEN) {
  console.error("ยังไม่ได้ตั้งค่า DISCORD_TOKEN");
  process.exit(1);
}
client.login(BOT_TOKEN);
