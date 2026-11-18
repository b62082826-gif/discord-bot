// voice_bot.js — บอทเข้าห้องเสียงค้างไว้ (แปลงจาก Python nextcord เป็น JavaScript / discord.js v14)
// ใช้ได้ทุกเซิร์ฟเวอร์: ใช้คำสั่ง /เข้าห้อง เพื่อให้บอทเข้าห้องเสียงที่ต้องการ บอทจะจำห้องไว้และเข้าเองหลังรีสตาร์ท
//
// ติดตั้ง:  npm install discord.js @discordjs/voice libsodium-wrappers
// โทเค่น:   ตั้ง environment variable ชื่อ DISCORD_TOKEN (หรือไฟล์ .env บรรทัด DISCORD_TOKEN=xxxxx ใช้ Node 20.12+)
//   Windows (cmd): set DISCORD_TOKEN=xxxxx && node voice_bot.js
//   Linux/Mac:     DISCORD_TOKEN=xxxxx node voice_bot.js

const fs = require("fs");
const {
  Client,
  GatewayIntentBits,
  Events,
  ActivityType,
  ChannelType,
  PermissionFlagsBits,
  MessageFlags,
} = require("discord.js");
const {
  joinVoiceChannel,
  getVoiceConnection,
  entersState,
  VoiceConnectionStatus,
} = require("@discordjs/voice");

try {
  if (fs.existsSync(".env") && typeof process.loadEnvFile === "function") process.loadEnvFile(".env");
} catch (e) {
  console.error("[ENV] อ่านไฟล์ .env ไม่ได้:", e.message);
}

const BOT_TOKEN = process.env.DISCORD_TOKEN || "";

// ───────────────────────── ตั้งค่า ─────────────────────────
const STATUS_NAME = "https://discord.gg/tV6xz4Rc4n"; // ข้อความสถานะ (แบบกำลังสตรีม)
const STATUS_URL = "https://www.youtube.com/@HIHi-s2j4q"; // ต้องเป็นลิงก์ twitch.tv หรือ youtube.com ถึงจะขึ้นสถานะสตรีม
const DEFAULT_GUILD_ID = "1571827346477154315"; // เซิร์ฟเวอร์เริ่มต้น (เว้นว่าง "" = ไม่ใช้)
const DEFAULT_CHANNEL_ID = "1571827351212523623"; // ห้องเสียงเริ่มต้น (เว้นว่าง "" = ไม่ใช้)
const SELF_MUTE = false;
const SELF_DEAF = true;
const REJOIN_DELAY_MS = 5_000; // รอก่อนเข้าห้องใหม่เมื่อหลุด

const SAVE_FILE = "voice_channels.json"; // { guildId: channelId } ห้องที่บอทต้องอยู่

// ───────────────────────── ที่เก็บห้อง ─────────────────────────
function loadSaved() {
  try {
    if (fs.existsSync(SAVE_FILE)) return JSON.parse(fs.readFileSync(SAVE_FILE, "utf-8"));
  } catch (e) {
    console.error("[SAVE] อ่านไฟล์ไม่ได้ ใช้ค่าเริ่มต้น:", e.message);
  }
  return {};
}

const wanted = loadSaved();

function saveWanted() {
  try {
    const tmp = SAVE_FILE + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(wanted));
    fs.renameSync(tmp, SAVE_FILE); // เขียนแบบ atomic กันไฟล์พัง
  } catch (e) {
    console.error("[SAVE] บันทึกไม่สำเร็จ:", e.message);
  }
}

// ───────────────────────── client ─────────────────────────
const client = new Client({
  intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates],
});

const rejoinTimers = new Map();

function joinChannel(channel) {
  const old = getVoiceConnection(channel.guild.id);
  if (old) old.destroy();

  const connection = joinVoiceChannel({
    channelId: channel.id,
    guildId: channel.guild.id,
    adapterCreator: channel.guild.voiceAdapterCreator,
    selfMute: SELF_MUTE,
    selfDeaf: SELF_DEAF,
  });

  connection.on(VoiceConnectionStatus.Disconnected, async () => {
    try {
      // ถ้าแค่ย้ายห้อง/รีคอนเนกต์ จะกลับมาเองภายใน 5 วินาที
      await Promise.race([
        entersState(connection, VoiceConnectionStatus.Signalling, 5_000),
        entersState(connection, VoiceConnectionStatus.Connecting, 5_000),
      ]);
    } catch {
      if (connection.state.status !== VoiceConnectionStatus.Destroyed) connection.destroy();
      scheduleRejoin(channel.guild.id);
    }
  });

  return connection;
}

function scheduleRejoin(guildId) {
  if (!wanted[guildId] || rejoinTimers.has(guildId)) return; // ถูกสั่งออกเองแล้ว ไม่ต้องเข้าซ้ำ
  const t = setTimeout(async () => {
    rejoinTimers.delete(guildId);
    await ensureJoined(guildId);
  }, REJOIN_DELAY_MS);
  rejoinTimers.set(guildId, t);
}

async function ensureJoined(guildId) {
  const channelId = wanted[guildId];
  if (!channelId) return false;
  try {
    const guild = client.guilds.cache.get(guildId) ?? (await client.guilds.fetch(guildId));
    const channel = await guild.channels.fetch(channelId);
    if (!channel?.isVoiceBased()) throw new Error("ไม่ใช่ห้องเสียง");
    joinChannel(channel);
    console.log(`🔊 เข้าห้อง ${channel.name} ใน ${guild.name}`);
    return true;
  } catch (e) {
    console.error(`[JOIN] เข้าห้องไม่สำเร็จ (guild ${guildId}):`, e.message);
    scheduleRejoin(guildId);
    return false;
  }
}

// ───────────────────────── events ─────────────────────────
client.once(Events.ClientReady, async (c) => {
  c.user.setPresence({
    activities: [{ name: STATUS_NAME, type: ActivityType.Streaming, url: STATUS_URL }],
    status: "online",
  });

  await c.application.commands.set([
    {
      name: "เข้าห้อง",
      description: "ให้บอทเข้าห้องเสียงค้างไว้ (ไม่ระบุห้อง = ห้องที่คุณอยู่)",
      default_member_permissions: PermissionFlagsBits.ManageGuild.toString(),
      dm_permission: false,
      options: [
        {
          type: 7, // Channel
          name: "ห้อง",
          description: "ห้องเสียงที่ต้องการให้บอทเข้า",
          required: false,
          channel_types: [ChannelType.GuildVoice, ChannelType.GuildStageVoice],
        },
      ],
    },
    {
      name: "ออกห้อง",
      description: "ให้บอทออกจากห้องเสียงและเลิกเข้าห้องอัตโนมัติ",
      default_member_permissions: PermissionFlagsBits.ManageGuild.toString(),
      dm_permission: false,
    },
  ]);

  // ห้องเริ่มต้น (ถ้ายังไม่เคยตั้งในเซิร์ฟเวอร์นั้น)
  if (DEFAULT_GUILD_ID && DEFAULT_CHANNEL_ID && !wanted[DEFAULT_GUILD_ID]) {
    wanted[DEFAULT_GUILD_ID] = DEFAULT_CHANNEL_ID;
    saveWanted();
  }
  for (const guildId of Object.keys(wanted)) await ensureJoined(guildId);

  console.log(`✅ บอทออนไลน์แล้ว: ${c.user.tag} (ID: ${c.user.id})`);
});

client.on(Events.InteractionCreate, async (interaction) => {
  if (!interaction.isChatInputCommand() || !interaction.guild) return;
  const reply = (content) => interaction.reply({ content, flags: MessageFlags.Ephemeral });

  try {
    if (interaction.commandName === "เข้าห้อง") {
      const channel =
        interaction.options.getChannel("ห้อง") ?? interaction.member?.voice?.channel;
      if (!channel?.isVoiceBased()) {
        return reply("❌ เข้าห้องเสียงก่อน หรือเลือกห้องในคำสั่ง");
      }
      const me = interaction.guild.members.me;
      const perms = channel.permissionsFor(me);
      if (!perms?.has(PermissionFlagsBits.ViewChannel) || !perms.has(PermissionFlagsBits.Connect)) {
        return reply("❌ บอทไม่มีสิทธิ์ดู/เชื่อมต่อห้องนั้น (ต้องมี View Channel และ Connect)");
      }
      wanted[interaction.guildId] = channel.id;
      saveWanted();
      clearTimeout(rejoinTimers.get(interaction.guildId));
      rejoinTimers.delete(interaction.guildId);
      joinChannel(channel);
      return reply(`✅ เข้าห้อง ${channel} แล้ว (บอทจะอยู่ค้างและเข้าเองหลังรีสตาร์ท)`);
    }

    if (interaction.commandName === "ออกห้อง") {
      delete wanted[interaction.guildId];
      saveWanted();
      clearTimeout(rejoinTimers.get(interaction.guildId));
      rejoinTimers.delete(interaction.guildId);
      getVoiceConnection(interaction.guildId)?.destroy();
      return reply("👋 ออกจากห้องเสียงแล้ว");
    }
  } catch (e) {
    console.error("[INTERACTION ERROR]", e);
    if (!interaction.replied && !interaction.deferred) await reply("❌ เกิดข้อผิดพลาด ลองใหม่อีกครั้ง").catch(() => {});
  }
});

// บอทถูกลากย้ายห้อง / ถูกเตะออกจากห้องเสียง -> เข้าห้องที่ตั้งไว้ใหม่
// และแจ้งใน log เมื่อมีคนเริ่มแชร์หน้าจอ/สตรีม (เหมือน on_voice_state_update เดิม)
client.on(Events.VoiceStateUpdate, (oldState, newState) => {
  if (newState.id === client.user.id) {
    const target = wanted[newState.guild.id];
    if (target && newState.channelId !== target) scheduleRejoin(newState.guild.id);
    return;
  }
  if (newState.channel && newState.streaming && !oldState.streaming) {
    console.log(`${newState.member?.user.username ?? newState.id} is in ${newState.channel.name} and started streaming.`);
  }
});

process.on("unhandledRejection", (e) => console.error("[UNHANDLED]", e));

if (!BOT_TOKEN) {
  console.error("ยังไม่ได้ตั้งค่า DISCORD_TOKEN");
  process.exit(1);
}
client.login(BOT_TOKEN);
