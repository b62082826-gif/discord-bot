// เครดิต : MC https://discord.gg/3VRwGSZZZE (เวอร์ชัน JavaScript / discord.js v14)
// ต้องใช้ Node.js 18+ และ discord.js 14.19+ -> npm install discord.js
//
// ตั้งค่าโทเค่นผ่าน environment variable: DISCORD_TOKEN
// Windows (cmd): set DISCORD_TOKEN=xxxxx && node cat_shop_ticket_bot.js
// Linux/Mac: DISCORD_TOKEN=xxxxx node cat_shop_ticket_bot.js

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
  EmbedBuilder,
} = require("discord.js");

// bot-hosting.net: ใส่โทเค่นใน Environment/Startup variable ชื่อ DISCORD_TOKEN
// หรือสร้างไฟล์ .env ข้าง ๆ ไฟล์นี้ แล้วเขียนบรรทัด DISCORD_TOKEN=xxxxx (ต้องใช้ Node 20.12+)
try {
  if (fs.existsSync(".env") && typeof process.loadEnvFile === "function") process.loadEnvFile(".env");
} catch (e) {
  console.error("[ENV] อ่านไฟล์ .env ไม่ได้:", e.message);
}

const BOT_TOKEN = process.env.DISCORD_TOKEN || "";
const OWNER_ID = "1524722784817909811"; // ไอดีเจ้าของที่ใช้คำสั่ง /ตั้งค่าตั๋ว ได้ (ใส่เป็น string)
const BUG_CATEGORY_ID = "1572197960509292644"; // หมวดหมู่ แจ้งบั๊ก
const CONTACT_CATEGORY_ID = "1572198033670545510"; // หมวดหมู่ ติดต่อ

// ───────────────────────── ตั้งค่าระบบเสริม (เว้นว่าง "" = ปิดส่วนนั้น) ─────────────────────────
const VERIFY_ROLE_ID = "1571827346510446647"; // ยศที่ได้เมื่อกดยืนยันตัวตน (บอทต้องมีสิทธิ์ Manage Roles และยศบอทต้องอยู่สูงกว่ายศนี้)
const VERIFY_MIN_ACCOUNT_DAYS = 0; // อายุบัญชี Discord ขั้นต่ำ (วัน) ถึงจะยืนยันได้ 0 = ไม่เช็ก
const WELCOME_CHANNEL_ID = "1571827347722739815"; // ห้องข้อความต้อนรับสมาชิกใหม่
const LEAVE_CHANNEL_ID = "1571827347722739817"; // ห้องแจ้งคนออก (เว้นว่าง = ใช้ห้องต้อนรับ)
const WELCOME_IMAGE_URL = "https://i.pinimg.com/736x/4e/43/47/4e4347489e411396189a611b05645ae2.jpg"; // รูปแบนเนอร์ในข้อความต้อนรับ (ไม่ใส่ก็ได้)
const LEVEL_UP_CHANNEL_ID = "1572553862412369980"; // ห้องแจ้งเลเวลอัป (เว้นว่าง = ส่งในห้องที่เขาพิมพ์อยู่)
const LEVEL_ROLES = { 1: "1571827346523037780", 5: "1571827346523037781", 10: "1571827346523037782", 20: "1571827346523037783", 35: "1571827346523037784", 50: "1571827346523037785", 100: "1571827346523037786" }; // ยศตามเลเวล
const XP_MIN = 15; // XP ต่อข้อความ (สุ่มระหว่าง MIN-MAX)
const XP_MAX = 100;
const XP_COOLDOWN_MS = 60_000; // นับ XP ได้ทุก ๆ กี่มิลลิวินาทีต่อคน

// ลิงก์ cdn.discordapp.com ที่มี ?ex=&is=&hm= จะหมดอายุ -> รูปพัง
// แนะนำใช้ลิงก์รูปถาวร
const TICKET_IMAGE_URL =
  "https://i.pinimg.com/736x/1c/54/2b/1c542b646ec39944d70dc01ea3fe3122.jpg";

// ───────────────────────── ระบบรับยศ 77 จังหวัด ─────────────────────────
const PROVINCE_IMAGE_URL =
  "https://i.pinimg.com/1200x/e9/9a/b8/e99ab860faa0f47a5931a5a472afea0c.jpg";

const PROVINCE_REGIONS = {
  "ภาคเหนือ": [
    "เชียงใหม่", "เชียงราย", "ลำปาง", "ลำพูน", "แม่ฮ่องสอน",
    "น่าน", "พะเยา", "แพร่", "อุตรดิตถ์",
  ],
  "ภาคอีสาน": [
    "ขอนแก่น", "อุดรธานี", "นครราชสีมา", "อุบลราชธานี", "ร้อยเอ็ด",
    "มหาสารคาม", "กาฬสินธุ์", "สกลนคร", "เลย", "ชัยภูมิ",
    "หนองคาย", "หนองบัวลำภู", "ยโสธร", "ศรีสะเกษ", "สุรินทร์",
    "บุรีรัมย์", "มุกดาหาร", "อำนาจเจริญ", "นครพนม", "บึงกาฬ",
  ],
  "ภาคกลาง": [
    "กรุงเทพมหานคร", "นนทบุรี", "ปทุมธานี", "สมุทรปราการ",
    "พระนครศรีอยุธยา", "อ่างทอง", "ลพบุรี", "สิงห์บุรี",
    "ชัยนาท", "สระบุรี", "นครนายก", "สุพรรณบุรี",
    "นครปฐม", "สมุทรสาคร", "สมุทรสงคราม",
    "สุโขทัย", "พิษณุโลก", "พิจิตร", "กำแพงเพชร",
    "เพชรบูรณ์", "นครสวรรค์", "อุทัยธานี",
  ],
  "ภาคตะวันออก": [
    "ชลบุรี", "ระยอง", "จันทบุรี", "ตราด", "ฉะเชิงเทรา",
    "ปราจีนบุรี", "สระแก้ว",
  ],
  "ภาคตะวันตก": [
    "ตาก", "กาญจนบุรี", "ราชบุรี", "เพชรบุรี", "ประจวบคีรีขันธ์",
  ],
  "ภาคใต้": [
    "ภูเก็ต", "กระบี่", "พังงา", "ระนอง", "ชุมพร",
    "สุราษฎร์ธานี", "นครศรีธรรมราช", "พัทลุง", "ตรัง",
    "สงขลา", "สตูล", "ปัตตานี", "ยะลา", "นราธิวาส",
  ],
};
const ALL_PROVINCES = new Set(Object.values(PROVINCE_REGIONS).flat()); // 77 จังหวัด

// หน้าตาเหมือนแผงยืนยันตัวตน (Components V2: Container + ข้อความ + เส้นคั่น + ตัวเลือก)
function buildProvincePanelPayload() {
  return {
    flags: MessageFlags.IsComponentsV2,
    components: [
      {
        type: 17,
        components: [
          {
            type: 10,
            content:
              `# ${em("verify")} ระบบรับยศ 77 จังหวัด\n\n` +
              "เลือกภูมิภาคและจังหวัดของคุณจากเมนูด้านล่าง เพื่อรับยศประจำจังหวัด",
          },
          { type: 14, spacing: 2 },
          { type: 12, items: [{ media: { url: PROVINCE_IMAGE_URL } }] }, // MediaGallery
          { type: 14, spacing: 2 },
          {
            type: 1,
            components: [
              {
                type: 3, // StringSelect
                custom_id: "region_select",
                placeholder: "เลือกภูมิภาค",
                options: Object.keys(PROVINCE_REGIONS).map((r) => ({ label: r, value: r })),
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

async function handleRegionSelect(interaction) {
  const region = interaction.values[0];
  if (!Object.hasOwn(PROVINCE_REGIONS, region)) {
    return interaction.reply({ content: "❌ ไม่พบภูมิภาคนี้", flags: MessageFlags.Ephemeral });
  }

  return interaction.reply({
    flags: MessageFlags.Ephemeral | MessageFlags.IsComponentsV2,
    components: [
      {
        type: 17,
        components: [
          { type: 10, content: `# ${em("verify")} เลือกจังหวัด\n\nภูมิภาค: **${region}**` },
          { type: 14, spacing: 2 },
          {
            type: 1,
            components: [
              {
                type: 3,
                custom_id: "province_select",
                placeholder: "เลือกจังหวัดของคุณ",
                options: PROVINCE_REGIONS[region].map((p) => ({ label: p, value: p })),
              },
            ],
          },
        ],
      },
    ],
  });
}

async function handleProvinceSelect(interaction) {
  await interaction.deferReply({ flags: MessageFlags.Ephemeral });

  const province = interaction.values[0];
  if (!interaction.guild || !interaction.member || !ALL_PROVINCES.has(province)) {
    return interaction.editReply("❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์ และต้องเลือกจังหวัดที่มีในรายการ");
  }

  const role = interaction.guild.roles.cache.find((r) => r.name === province);
  if (!role) return interaction.editReply("❌ ไม่พบยศ (ให้แอดมินใช้ /สร้างยศ77 ก่อน)");

  try {
    // ถอดยศจังหวัดเดิมออก เพื่อให้มีจังหวัดเดียวต่อคน
    const oldRoles = interaction.member.roles.cache.filter(
      (r) => ALL_PROVINCES.has(r.name) && r.id !== role.id
    );
    if (oldRoles.size) await interaction.member.roles.remove(oldRoles, "เปลี่ยนจังหวัด");
    await interaction.member.roles.add(role, "รับยศจังหวัด");
    return interaction.editReply(`✅ คุณได้รับยศ: ${role.name}`);
  } catch (e) {
    console.error("[PROVINCE]", e.message);
    return interaction.editReply("❌ ให้ยศไม่สำเร็จ (บอทอาจไม่มีสิทธิ์ Manage Roles หรือยศบอทต่ำกว่ายศจังหวัด) กรุณาแจ้งแอดมิน");
  }
}

async function handleCreateProvinceRoles(interaction) {
  await interaction.deferReply({ flags: MessageFlags.Ephemeral });
  if (!interaction.guild) return interaction.editReply("❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์");

  const roles = await interaction.guild.roles.fetch();
  const existing = new Set(roles.map((r) => r.name));
  let created = 0;

  try {
    for (const province of ALL_PROVINCES) {
      if (existing.has(province)) continue;
      await interaction.guild.roles.create({ name: province, reason: "สร้างยศ 77 จังหวัด" });
      created++;
    }
  } catch (e) {
    console.error("[CREATE ROLES]", e.message);
    const why = e.code === 30005 ? "เซิร์ฟเวอร์มียศครบจำนวนสูงสุดแล้ว (250)" : "บอทอาจไม่มีสิทธิ์ Manage Roles";
    return interaction.editReply(`⚠️ สร้างได้ ${created} ยศ แล้วหยุด: ${why}`);
  }

  return interaction.editReply(`✅ สร้างยศสำเร็จ ${created} ยศ`);
}

const STATE_FILE = "ticket_state.json";
const LEVEL_FILE = "levels.json";
const AUTO_REPLY_COOLDOWN_MS = 60_000;

// ───────────────────────── อีโมจิ (Application Emoji ของบอท) ─────────────────────────
// รูปแบบ: [ชื่อ, ID] ดูได้ที่ Developer Portal -> Emojis
const E_IDS = {
  ticket: ["431007ticketicon", "1572207134970482748"],
  approve: ["157030approveids", "1572207131262853160"],
  denied: ["944140deniedids", "1572207141224190003"],
  verify: ["45415verifygreen", "1572207125323714580"],
  shield: ["379975bluestaff", "1572207133230108703"],
  partner: ["18284partner", "1572207119489572914"],
};
const em = (k) => `<:${E_IDS[k][0]}:${E_IDS[k][1]}>`; // ใช้ในข้อความ
const btnEmoji = (k) => ({ id: E_IDS[k][1], name: E_IDS[k][0] }); // ใช้บนปุ่ม

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

// ───────────────────────── level / XP ─────────────────────────
function loadLevels() {
  try {
    if (fs.existsSync(LEVEL_FILE)) return JSON.parse(fs.readFileSync(LEVEL_FILE, "utf-8"));
  } catch (e) {
    console.error("[LEVEL] อ่านไฟล์ไม่ได้ ใช้ค่าเริ่มต้น:", e.message);
  }
  return {};
}

const levels = loadLevels(); // { guildId: { userId: { xp } } }
let levelsDirty = false;
const lastXp = new Map();

function saveLevels() {
  if (!levelsDirty) return;
  levelsDirty = false;
  try {
    const tmp = LEVEL_FILE + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(levels));
    fs.renameSync(tmp, LEVEL_FILE);
  } catch (e) {
    levelsDirty = true;
    console.error("[LEVEL] บันทึกไม่สำเร็จ:", e.message);
  }
}
setInterval(saveLevels, 30_000);
for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => { saveLevels(); process.exit(0); });
}

// XP ที่ต้องใช้เพื่อขึ้นจากเลเวล lvl ไปเลเวลถัดไป
const xpNeeded = (lvl) => 5 * lvl * lvl + 50 * lvl + 100;

function levelFromXp(total) {
  let level = 0, rest = total;
  while (rest >= xpNeeded(level)) { rest -= xpNeeded(level); level++; }
  return { level, current: rest, need: xpNeeded(level) };
}

async function giveLevelRoles(member, level) {
  for (const [lvl, roleId] of Object.entries(LEVEL_ROLES)) {
    if (!roleId || level < Number(lvl) || member.roles.cache.has(roleId)) continue;
    await member.roles.add(roleId, `ถึงเลเวล ${lvl}`)
      .catch((e) => console.error("[LEVEL ROLE]", e.message));
  }
}

async function awardXp(message) {
  const member = message.member;
  if (!member) return;
  const parent = message.channel.parentId;
  if (parent && (parent === BUG_CATEGORY_ID || parent === CONTACT_CATEGORY_ID)) return; // ไม่นับในห้องตั๋ว

  const key = `${message.guildId}:${message.author.id}`;
  const now = Date.now();
  if (now - (lastXp.get(key) ?? 0) < XP_COOLDOWN_MS) return;
  lastXp.set(key, now);

  const users = (levels[message.guildId] ??= {});
  const user = (users[message.author.id] ??= { xp: 0 });
  const before = levelFromXp(user.xp).level;
  user.xp += XP_MIN + Math.floor(Math.random() * (XP_MAX - XP_MIN + 1));
  levelsDirty = true;
  const after = levelFromXp(user.xp).level;
  if (after <= before) return;

  await giveLevelRoles(member, after);

  const channel = LEVEL_UP_CHANNEL_ID
    ? await client.channels.fetch(LEVEL_UP_CHANNEL_ID).catch(() => null)
    : message.channel;
  if (channel?.isTextBased()) {
    await channel
      .send({ content: `${em("approve")} ${member} เลเวลอัปเป็น **เลเวล ${after}** แล้ว!`, allowedMentions: { users: [member.id] } })
      .catch((e) => console.error("[LEVEL UP]", e.message));
  }
}

function rankOf(guildId, userId) {
  const sorted = Object.entries(levels[guildId] ?? {}).sort((a, b) => b[1].xp - a[1].xp);
  const i = sorted.findIndex(([id]) => id === userId);
  return { position: i + 1, total: sorted.length, sorted };
}

async function handleRank(interaction) {
  const target = interaction.options.getUser("ผู้ใช้") ?? interaction.user;
  const xp = levels[interaction.guildId]?.[target.id]?.xp ?? 0;
  const { level, current, need } = levelFromXp(xp);
  const { position, total } = rankOf(interaction.guildId, target.id);
  const filled = Math.round((current / need) * 10);
  const bar = "▰".repeat(filled) + "▱".repeat(10 - filled);
  const embed = new EmbedBuilder()
    .setColor(0x2b2d31)
    .setAuthor({ name: target.username, iconURL: target.displayAvatarURL() })
    .setDescription(
      `**เลเวล ${level}**\n${bar} ${current}/${need} XP\n\n` +
      `อันดับ **${position > 0 ? position : "-"}** จาก ${total} คน · XP รวม ${xp}`
    );
  return interaction.reply({ embeds: [embed] });
}

async function handleLeaderboard(interaction) {
  const { sorted } = rankOf(interaction.guildId, "");
  if (!sorted.length) return interaction.reply({ content: "ยังไม่มีข้อมูลเลเวล", flags: MessageFlags.Ephemeral });
  const medals = ["🥇", "🥈", "🥉"];
  const lines = sorted.slice(0, 10).map(([id, u], i) =>
    `${medals[i] ?? `**${i + 1}.**`} <@${id}> — เลเวล ${levelFromXp(u.xp).level} · ${u.xp} XP`
  );
  const embed = new EmbedBuilder().setColor(0x2b2d31).setTitle("อันดับเลเวล").setDescription(lines.join("\n"));
  return interaction.reply({ embeds: [embed], allowedMentions: { parse: [] } });
}

// ───────────────────────── client ─────────────────────────
const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent, // ต้องเปิด Privileged Intent ใน Developer Portal
    GatewayIntentBits.GuildMembers, // ต้องเปิด Privileged Intent ใน Developer Portal
  ],
});

// ───────────────────────── Safe Role (บันทึกยศตอนออก คืนยศตอนกลับเข้ามา) ─────────────────────────
const { installSafeRole, SAFE_ROLE_COMMAND } = require("./safe_role");
installSafeRole(client, { ownerId: OWNER_ID, em, btnEmoji });

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
    `# ${em("ticket")} ยินดีต้อนรับสู่ระบบตั๋ว Support`,
    "",
    "กรุณาแจ้งรายละเอียดที่ต้องการให้ครบถ้วน เพื่อให้ทีมงานสามารถตอบกลับและให้บริการได้รวดเร็วยิ่งขึ้น",
    "",
    `${em("shield")} **กฎการใช้บริการ**`,
    ...[
      "กรุณาพูดคุยด้วยถ้อยคำสุภาพ",
      "ห้ามสแปมหรือแท็กทีมงานซ้ำ ๆ",
      "กรุณารอทีมงานตอบกลับตามลำดับคิว",
      "เมื่อได้รับงานแล้ว กรุณาตรวจสอบงานให้เรียบร้อยก่อนปิดตั๋ว",
      "หากมีการแก้ไขเพิ่มเติมหลังส่งงาน อาจมีค่าใช้จ่ายเพิ่มเติมตามความเหมาะสม",
    ].map((s) => `${em("approve")} ${s}`),
    "",
    `${em("verify")} เวลาทำการ`,
    "เปิดให้บริการทุกวัน โดยทีมงานจะพยายามตอบกลับให้เร็วที่สุด",
    "",
    `${em("partner")} ขอบคุณที่เลือกใช้บริการ Support`,
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
                emoji: btnEmoji("denied"),
                custom_id: "ticket_bug",
              },
              {
                type: 2, style: 2, label: "ติดต่อ",
                emoji: btnEmoji("partner"),
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
      `# ${em("ticket")} ยินดีต้อนรับคับ\n` +
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

function buildVerifyPanelPayload() {
  return {
    flags: MessageFlags.IsComponentsV2,
    components: [
      {
        type: 17,
        components: [
          {
            type: 10,
            content:
              `# ${em("verify")} ยืนยันตัวตน\n\n` +
              "กดปุ่มด้านล่างเพื่อรับยศสมาชิก และเข้าถึงห้องต่าง ๆ ภายในเซิร์ฟเวอร์",
          },
          { type: 14, spacing: 2 },
          {
            type: 1,
            components: [
              { type: 2, style: 3, label: "ยืนยันตัวตน", emoji: btnEmoji("verify"), custom_id: "verify_member" },
            ],
          },
        ],
      },
    ],
  };
}

async function handleVerify(interaction) {
  const reply = (content) => interaction.reply({ content, flags: MessageFlags.Ephemeral });

  if (!VERIFY_ROLE_ID) return reply("❌ ยังไม่ได้ตั้งค่ายศสำหรับยืนยันตัวตน กรุณาแจ้งแอดมิน");
  if (!interaction.guild || !interaction.member) return reply("❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์");
  if (interaction.member.roles.cache.has(VERIFY_ROLE_ID)) return reply("✅ คุณยืนยันตัวตนแล้ว");

  if (VERIFY_MIN_ACCOUNT_DAYS > 0) {
    const ageDays = (Date.now() - interaction.user.createdTimestamp) / 86_400_000;
    if (ageDays < VERIFY_MIN_ACCOUNT_DAYS) {
      return reply(`❌ บัญชี Discord ต้องมีอายุอย่างน้อย ${VERIFY_MIN_ACCOUNT_DAYS} วันจึงจะยืนยันได้`);
    }
  }

  try {
    await interaction.member.roles.add(VERIFY_ROLE_ID, "ยืนยันตัวตนผ่านปุ่ม");
    return reply("✅ ยืนยันตัวตนสำเร็จ ยินดีต้อนรับ!");
  } catch (e) {
    console.error("[VERIFY]", e.message);
    return reply("❌ ให้ยศไม่สำเร็จ (บอทอาจไม่มีสิทธิ์ หรือยศบอทต่ำกว่ายศยืนยัน) กรุณาแจ้งแอดมิน");
  }
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
    { name: "ตั้งค่ายืนยัน", description: "ส่งแผงยืนยันตัวตนไปยังช่องนี้" },
    { name: "ตั้งค่าระบบ", description: "สร้างระบบรับยศ 77 จังหวัด" },
    { name: "สร้างยศ77", description: "สร้าง Role 77 จังหวัด" },
    {
      name: "เลเวล",
      description: "ดูเลเวลและ XP",
      options: [{ type: 6, name: "ผู้ใช้", description: "ดูของคนอื่น (ไม่ใส่ = ของตัวเอง)", required: false }],
    },
    { name: "อันดับ", description: "ดูอันดับเลเวล 10 อันดับแรก" },
    SAFE_ROLE_COMMAND,
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

    if (interaction.isChatInputCommand()) {
      switch (interaction.commandName) {
        case "ตั้งค่ายืนยัน": {
          if (interaction.user.id !== OWNER_ID) {
            return interaction.reply({ content: "❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", flags: MessageFlags.Ephemeral });
          }
          await interaction.deferReply({ flags: MessageFlags.Ephemeral });
          const ok = await sendRaw(interaction.channelId, buildVerifyPanelPayload());
          return interaction.editReply(ok ? "✅ ส่งแผงยืนยันตัวตนเรียบร้อยแล้ว" : "❌ ส่งแผงไม่สำเร็จ (ดู log / เช็คสิทธิ์บอทและอีโมจิ)");
        }
        case "ตั้งค่าระบบ": {
          if (interaction.user.id !== OWNER_ID) {
            return interaction.reply({ content: "❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", flags: MessageFlags.Ephemeral });
          }
          await interaction.deferReply({ flags: MessageFlags.Ephemeral });
          const ok = await sendRaw(interaction.channelId, buildProvincePanelPayload());
          return interaction.editReply(ok ? "✅ ส่งแผงรับยศจังหวัดเรียบร้อยแล้ว" : "❌ ส่งแผงไม่สำเร็จ (ดู log / เช็คสิทธิ์บอท)");
        }
        case "สร้างยศ77": {
          if (interaction.user.id !== OWNER_ID) {
            return interaction.reply({ content: "❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", flags: MessageFlags.Ephemeral });
          }
          return await handleCreateProvinceRoles(interaction);
        }
        case "เลเวล":
          return await handleRank(interaction);
        case "อันดับ":
          return await handleLeaderboard(interaction);
      }
      return;
    }

    if (interaction.type !== InteractionType.MessageComponent) return;

    switch (interaction.customId) {
      case "region_select":
        return await handleRegionSelect(interaction);
      case "province_select":
        return await handleProvinceSelect(interaction);
      case "verify_member":
        return await handleVerify(interaction);
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

  await awardXp(message).catch((e) => console.error("[XP ERROR]", e.message));

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

// ───────────────────────── ต้อนรับ / ลาออก ─────────────────────────
async function sendToChannel(channelId, payload) {
  if (!channelId) return;
  const channel = await client.channels.fetch(channelId).catch(() => null);
  if (!channel?.isTextBased()) return;
  await channel.send(payload).catch((e) => console.error("[WELCOME]", e.message));
}

client.on(Events.GuildMemberAdd, async (member) => {
  if (member.user.bot) return;
  // หมายเหตุ: ไม่ใส่อีโมจิในหัวข้อ embed เพราะ Discord ไม่แสดงอีโมจิกำหนดเองในหัวข้อ
  const embed = new EmbedBuilder()
    .setColor(0x2b2d31)
    .setTitle(`ยินดีต้อนรับสู่ ${member.guild.name}`)
    .setDescription(
      `${em("verify")} สวัสดี ${member} ยินดีที่ได้รู้จัก!\n` +
      `คุณเป็นสมาชิกคนที่ **${member.guild.memberCount}**` +
      (VERIFY_ROLE_ID ? "\n\nอย่าลืมกดปุ่มยืนยันตัวตนเพื่อเข้าถึงห้องต่าง ๆ" : "")
    )
    .setThumbnail(member.user.displayAvatarURL({ size: 256 }))
    .setTimestamp();
  if (WELCOME_IMAGE_URL) embed.setImage(WELCOME_IMAGE_URL);
  await sendToChannel(WELCOME_CHANNEL_ID, {
    content: `${member}`,
    embeds: [embed],
    allowedMentions: { users: [member.id] },
  });
});

client.on(Events.GuildMemberRemove, async (member) => {
  if (member.user?.bot) return;
  const embed = new EmbedBuilder()
    .setColor(0x2b2d31)
    .setDescription(
      `${em("denied")} **${member.user?.username ?? "สมาชิก"}** ออกจากเซิร์ฟเวอร์แล้ว\n` +
      `ตอนนี้มีสมาชิก **${member.guild.memberCount}** คน`
    )
    .setTimestamp();
  await sendToChannel(LEAVE_CHANNEL_ID || WELCOME_CHANNEL_ID, { embeds: [embed] });
});

if (!BOT_TOKEN) {
  console.error("ยังไม่ได้ตั้งค่า DISCORD_TOKEN");
  process.exit(1);
}
client.login(BOT_TOKEN);
