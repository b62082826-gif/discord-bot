import os
import json
import logging
import datetime
import threading
import asyncio
from collections import deque
from datetime import timezone, timedelta

import discord
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from flask import Flask

load_dotenv()  # โหลดค่าจากไฟล์ .env เข้าสู่ environment variables

# ---------------------------------------------------------
# Logging: สำคัญมากเวลารันแบบ 24/7 เพื่อดูว่าบอทหลุด/error ตรงไหน
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("bobbot")

# ---------------------------------------------------------
# ธีมสี/สไตล์กลาง — ใช้ให้ทุก Embed ในบอทหน้าตาไปทิศทางเดียวกัน
# ---------------------------------------------------------
class Theme:
    PRIMARY = discord.Color.from_rgb(114, 137, 218)     # ม่วง-ฟ้า (โทนหลักของบอท)
    SUCCESS = discord.Color.from_rgb(87, 242, 135)       # เขียวมิ้นต์
    DANGER = discord.Color.from_rgb(237, 66, 69)         # แดง
    WARNING = discord.Color.from_rgb(255, 186, 73)       # ส้ม/เหลือง
    INFO = discord.Color.from_rgb(88, 164, 255)          # ฟ้าสด
    TICKET = discord.Color.from_rgb(59, 165, 93)         # เขียวเข้ม
    SCRIPTHUB = discord.Color.from_rgb(153, 69, 255)     # ม่วงสด

    DIVIDER = "─────────────────────"


# ---------------------------------------------------------
# Custom Emoji ของบอท (Application Emojis)
# — emoji พวกนี้ผูกกับตัวบอทเอง ใช้ได้ทุกเซิร์ฟเวอร์โดยไม่ต้องมีบอทอยู่ในเซิร์ฟที่อัปโหลดไว้
# โหลดเข้า cache ตอน on_ready แล้วเรียกใช้ผ่านฟังก์ชัน E(key, fallback)
# ---------------------------------------------------------
CUSTOM_EMOJI_NAMES = {
    # ระบบ/สถานะ (ปรับตามหน้าตาจริงที่เห็นในรูป)
    "success": "spbluetick",          # ✅ เครื่องหมายถูกวงกลม เหมาะกับ "สำเร็จ" ที่สุด
    "check": "bluecheckmark",         # เครื่องหมายถูกเฉย ๆ (ใช้แทน success ได้เหมือนกัน)
    "verified": "verifiedids",        # โล่เขียว+ถูก
    "not_verified": "nonverifiedids", # โล่เทา (ยังไม่ยืนยัน/ปฏิเสธ)
    "certified": "certified",         # วงกลมเขียว+ถูก
    "info": "info",
    "lock": "lock",
    "star": "starids",
    "star_shiny": "bluestarshiny",
    "star_outline": "starblue",
    "thumbsup": "bluethumbsup",
    "heart": "blueheart",
    "heart_outline": "bluedrawingheart",
    "arrow": "darkbluearrow",
    "staff": "bluestaffbadge",
    "moderator": "moderator",         # โล่ม่วง — ใช้กับข้อความ mod โดยเฉพาะ
    "blue_moderator": "bluemoderator",
    "mod_shield": "modshieldicon",
    "ticket": "ticketicon",           # หน้าตาเหมือนตั๋ว/เพชร ใช้กับระบบทิกเก็ตตรง ๆ
    "shield": "shield",
    "link": "link",
    "web": "webicon",
    "discord_logo": "discordlogo",
    "legit": "legit",
    "warning": "exclamation",
    "error": "xoflash",
    "glowing_dot": "glowingdotblue",
    "planet": "blueplanet",
    "lines": "lines",
    "gift": "giftingpatron",

    # Emoji มุก (Pepe/Joobi) — ใช้แต่งข้อความทั่วไปที่ไม่ใช่การลงโทษ/ระบบจริงจัง
    "fun_clap": "pepeclap",
    "fun_love": "pepeheart",
    "fun_nervous": "pepenervous",
    "fun_wow": "pepewow",
    "fun_perfect": "pepeperfect",
    "fun_cry": "crying",
    "fun_ohno": "joobiohno",
    "fun_huh": "joobihuh",
    "fun_wink": "joobiwink2",
    "fun_thumbsup": "joobithumbsup",
    "fun_laughter": "joobilaughter",
    "fun_rage": "raiva",
    "fun_ok": "pepeok",
    "fun_stare": "pepestaring",
    "fun_banger": "pepebanger",
    "fun_gamer": "gamer",
    "fun_crewmate": "bluecrewmate",
}

# เก็บ Emoji object ของแอปบอทหลังโหลดจาก Discord (ตอน on_ready)
custom_emoji_cache: dict[str, "discord.Emoji"] = {}


def E(key: str, fallback: str = "❓") -> str:
    """คืนค่า custom emoji ของบอทตาม key ความหมาย ถ้าไม่พบ/ยังไม่โหลด จะคืน unicode fallback แทน (ไม่มีวันพัง)"""
    emoji_name = CUSTOM_EMOJI_NAMES.get(key)
    if emoji_name:
        emoji = custom_emoji_cache.get(emoji_name)
        if emoji:
            return str(emoji)
    return fallback


# glyph ยูนิโค้ดที่ใช้ในข้อความ -> key ความหมายที่จะแปลงเป็น custom emoji อัตโนมัติ
_UNICODE_TO_EMOJI_KEY = {
    "✅": "success",
    "⭐": "star",
    "🎫": "ticket",
    "🔒": "lock",
    "🛡️": "shield",
    "⚠️": "warning",
    "❌": "error",
    "🔗": "link",
    "🌐": "web",
}


def themify(text: str) -> str:
    """แทนที่ unicode emoji ในข้อความด้วย custom emoji ของบอท (ถ้ามี) โดยอัตโนมัติ"""
    if not text:
        return text
    for glyph, key in _UNICODE_TO_EMOJI_KEY.items():
        if glyph in text:
            text = text.replace(glyph, E(key, glyph))
    return text


def base_embed(
    title: str,
    description: str = None,
    color: discord.Color = Theme.PRIMARY,
    guild: discord.Guild = None,
    timestamp: bool = True,
) -> discord.Embed:
    """สร้าง Embed พื้นฐานที่มีสไตล์เดียวกันทั้งบอท (สี/footer/timestamp)"""
    embed = discord.Embed(
        title=themify(title),
        description=themify(description),
        color=color,
        timestamp=datetime.datetime.now(timezone.utc) if timestamp else None,
    )
    footer_icon = guild.icon.url if guild and guild.icon else (bot.user.display_avatar.url if bot.user else None)
    footer_text = f"{guild.name}" if guild else (bot.user.name if bot.user else "BOB_BOT")
    embed.set_footer(text=f"✨ {footer_text}", icon_url=footer_icon)
    return embed


# ---------------------------------------------------------
# Keep-alive HTTP server (สำหรับ Render Free Plan)
# ---------------------------------------------------------
# Render free tier จะ sleep service ถ้าไม่มี HTTP request เข้ามาใน 15 นาที
# เปิด Flask server เล็ก ๆ ไว้ ให้บริการ ping ภายนอก (เช่น UptimeRobot) ยิงเข้ามาได้
keep_alive_app = Flask(__name__)


@keep_alive_app.route("/")
def keep_alive_home():
    return "BOB_BOT is alive!", 200


def run_keep_alive_server():
    port = int(os.getenv("PORT", 10000))  # Render จะกำหนด PORT ผ่าน env ให้อัตโนมัติ
    keep_alive_app.run(host="0.0.0.0", port=port)


def start_keep_alive():
    thread = threading.Thread(target=run_keep_alive_server, daemon=True)
    thread.start()
    logger.info("เริ่ม keep-alive HTTP server แล้ว")


# ---------------------------------------------------------
# อ่านค่า TOKEN ให้ถูกต้อง (แก้บั๊กเดิมที่เอา token ไปเป็น "ชื่อ" env var)
# ---------------------------------------------------------
# แก้ไขให้เหลือเฉพาะชื่อตัวแปรในวงเล็บ
TOKEN = os.getenv("BOT_TOKEN")

# ---------------------------------------------------------
# ระบบ AI ตอบแชท (Google Gemini API)
# ---------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "gemini-3.6-flash")

genai_client = None
if GEMINI_API_KEY:
    genai_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    logger.warning("ไม่พบ GEMINI_API_KEY — ระบบ AI ตอบแชทจะทำงานไม่ได้จนกว่าจะตั้งค่าใน .env")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
bot.startup_done = False  # ใช้กันไม่ให้ sync คำสั่ง/โหลด emoji ซ้ำทุกครั้งที่ reconnect (กัน global rate limit)

# ---------- ระบบเก็บค่ายศยืนยันตัวตนต่อเซิร์ฟเวอร์ ----------
VERIFY_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "verify_config.json")


def load_verify_config() -> dict:
    if os.path.exists(VERIFY_CONFIG_PATH):
        try:
            with open(VERIFY_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("อ่านไฟล์ verify_config.json ไม่ได้ จะเริ่มด้วยค่าว่าง")
            return {}
    return {}


def save_verify_config(config: dict) -> None:
    with open(VERIFY_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


verify_config = load_verify_config()  # { "guild_id": role_id }


# ---------- ระบบเก็บค่าเมนูรับยศ (Reaction Role) ----------
REACTIONROLE_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "reactionrole_config.json")


def load_reactionrole_config() -> dict:
    if os.path.exists(REACTIONROLE_CONFIG_PATH):
        try:
            with open(REACTIONROLE_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("อ่านไฟล์ reactionrole_config.json ไม่ได้ จะเริ่มด้วยค่าว่าง")
            return {}
    return {}


def save_reactionrole_config(config: dict) -> None:
    with open(REACTIONROLE_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# โครงสร้าง: { "guild_id": { "message_id": { "emoji_str": role_id } } }
reactionrole_config = load_reactionrole_config()


# ---------- ระบบเก็บค่าทิกเก็ต (Ticket) ----------
TICKET_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "ticket_config.json")


def load_ticket_config() -> dict:
    if os.path.exists(TICKET_CONFIG_PATH):
        try:
            with open(TICKET_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("อ่านไฟล์ ticket_config.json ไม่ได้ จะเริ่มด้วยค่าว่าง")
            return {}
    return {}


def save_ticket_config(config: dict) -> None:
    with open(TICKET_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# โครงสร้าง: { "guild_id": {"category_id": int, "support_role_id": int} }
ticket_config = load_ticket_config()


# ---------- ระบบเก็บค่าแผงแจกไฟล์/เทมเพลต (Script/File Hub Panel) ----------
SCRIPTHUB_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "scripthub_config.json")
SCRIPTHUB_FILES_DIR = os.path.join(os.path.dirname(__file__), "scripthub_files")
os.makedirs(SCRIPTHUB_FILES_DIR, exist_ok=True)


def load_scripthub_config() -> dict:
    if os.path.exists(SCRIPTHUB_CONFIG_PATH):
        try:
            with open(SCRIPTHUB_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("อ่านไฟล์ scripthub_config.json ไม่ได้ จะเริ่มด้วยค่าว่าง")
            return {}
    return {}


def save_scripthub_config(config: dict) -> None:
    with open(SCRIPTHUB_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# โครงสร้าง:
# { "guild_id": {
#     "channel_id": int, "message_id": int,
#     "title": str, "description": str, "image_url": str|None,
#     "items": [ {"label": str, "description": str, "content": str|None,
#                 "file_path": str|None, "file_name": str|None} ]
# } }
scripthub_config = load_scripthub_config()


# ---------- ระบบเก็บค่า AI ตอบแชท ----------
AI_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "ai_config.json")


def load_ai_config() -> dict:
    if os.path.exists(AI_CONFIG_PATH):
        try:
            with open(AI_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("อ่านไฟล์ ai_config.json ไม่ได้ จะเริ่มด้วยค่าว่าง")
            return {}
    return {}


def save_ai_config(config: dict) -> None:
    with open(AI_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# โครงสร้าง: { "guild_id": {"enabled": bool, "channel_id": int|None, "persona": str|None} }
ai_config = load_ai_config()

DEFAULT_AI_PERSONA = (
    "คุณคือ BOB_BOT ผู้ช่วย AI ประจำเซิร์ฟเวอร์ Discord พูดจาเป็นกันเอง สุภาพ กระชับ ไม่ยืดเยื้อ "
    "ตอบเป็นภาษาไทยเป็นหลัก (ยกเว้นผู้ใช้พิมพ์ภาษาอื่นมาก็ตอบภาษานั้นได้) "
    "ถ้าไม่แน่ใจให้บอกตามตรงว่าไม่แน่ใจ อย่าแต่งข้อมูลขึ้นมาเอง และหลีกเลี่ยงเนื้อหาที่ไม่เหมาะสม"
)

# เก็บบทสนทนาล่าสุดต่อห้อง (อยู่ในหน่วยความจำเท่านั้น หายเมื่อบอทรีสตาร์ท — ถือเป็นความจำระยะสั้นพอ)
AI_HISTORY_LIMIT = 12  # เก็บแค่ 12 ข้อความล่าสุดต่อห้อง (รวม user+assistant) กัน context ยาวเกิน/ค่าใช้จ่ายสูง
ai_conversations: dict[int, deque] = {}


def get_ai_history(channel_id: int) -> deque:
    if channel_id not in ai_conversations:
        ai_conversations[channel_id] = deque(maxlen=AI_HISTORY_LIMIT)
    return ai_conversations[channel_id]


async def generate_ai_reply(channel_id: int, persona: str, user_name: str, user_message: str) -> str:
    """เรียก Google Gemini API (SDK ใหม่ google-genai) เพื่อสร้างคำตอบ โดยใช้ประวัติแชทสั้น ๆ ของห้องนั้นประกอบ context"""
    if not genai_client:
        return "❌ ยังไม่ได้ตั้งค่า GEMINI_API_KEY บนเซิร์ฟเวอร์ที่รันบอท กรุณาแจ้งผู้ดูแลบอทให้ตั้งค่าใน .env"

    history = get_ai_history(channel_id)
    # SDK ใหม่ต้องการให้แต่ละ part เป็น dict {"text": ...} แทนสตริงตรง ๆ แบบ SDK เก่า
    new_turn = {"role": "user", "parts": [{"text": f"{user_name}: {user_message}"}]}
    contents = list(history) + [new_turn]

    def call_api():
        return genai_client.models.generate_content(
            model=AI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=persona),
        )

    try:
        response = await asyncio.to_thread(call_api)
    except Exception:
        logger.exception("เรียก Gemini API ไม่สำเร็จ")
        return "❌ เรียกใช้งาน AI ไม่สำเร็จตอนนี้ กรุณาลองใหม่อีกครั้งภายหลัง"

    reply_text = (getattr(response, "text", None) or "").strip()
    if not reply_text:
        reply_text = "🤔 ขอโทษด้วย ตอนนี้ตอบไม่ได้ ลองถามใหม่อีกครั้งนะ"

    # เก็บทั้งคำถามและคำตอบไว้เป็น context สำหรับข้อความถัดไปในห้องเดียวกัน
    # Gemini ใช้ role "model" แทน "assistant"
    history.append(new_turn)
    history.append({"role": "model", "parts": [{"text": reply_text}]})
    return reply_text


def split_for_discord(text: str, limit: int = 1900) -> list:
    """ตัดข้อความยาวให้พอดีกับลิมิต 2000 ตัวอักษรของ Discord ต่อหนึ่งข้อความ"""
    if len(text) <= limit:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        chunks.append(remaining[:limit])
        remaining = remaining[limit:]
    return chunks


def safe_filename_part(text: str, fallback: str = "item") -> str:
    """กรองข้อความให้เหลือเฉพาะอักขระที่ปลอดภัยสำหรับใช้ประกอบชื่อไฟล์/พาธ (กัน path traversal)"""
    cleaned = "".join(c for c in text if c.isalnum() or c in "._- ").strip()
    return cleaned or fallback


# =========================================================
# ระบบยืนยันตัวตน (Verification) — กดปุ่มแล้วรับยศทันที
# =========================================================
class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # ปุ่มถาวร ใช้ได้ตลอดแม้บอทรีสตาร์ท

    @discord.ui.button(
        label="ยืนยันตัวตน",
        style=discord.ButtonStyle.success,
        emoji="⭐",
        custom_id="bobbot_verify_button",
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild.id)
        role_id = verify_config.get(guild_id)

        if not role_id:
            await interaction.response.send_message(
                embed=base_embed(
                    "ยังไม่ได้ตั้งค่า",
                    "❌ ยังไม่ได้ตั้งค่ายศยืนยันตัวตนสำหรับเซิร์ฟเวอร์นี้\nกรุณาแจ้งแอดมินให้ใช้คำสั่ง `/setupverify`",
                    color=Theme.WARNING,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(int(role_id))
        if not role:
            await interaction.response.send_message(
                embed=base_embed(
                    "ไม่พบยศ",
                    "❌ ไม่พบยศที่ตั้งค่าไว้ (อาจถูกลบไปแล้ว) กรุณาแจ้งแอดมิน",
                    color=Theme.DANGER,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
            return

        if role in interaction.user.roles:
            await interaction.response.send_message(
                embed=base_embed("ยืนยันแล้ว", "✅ คุณยืนยันตัวตนไปแล้ว", color=Theme.SUCCESS, guild=interaction.guild),
                ephemeral=True,
            )
            return

        try:
            await interaction.user.add_roles(role, reason="ยืนยันตัวตนผ่านปุ่ม")
            await interaction.response.send_message(
                embed=base_embed(
                    "ยืนยันตัวตนสำเร็จ 🎉",
                    f"คุณได้รับยศ {role.mention} เรียบร้อยแล้ว ยินดีต้อนรับ!",
                    color=Theme.SUCCESS,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=base_embed(
                    "ผิดพลาด",
                    "❌ บอทไม่มีสิทธิ์มอบยศนี้ (ตรวจสอบว่ายศของบอทอยู่สูงกว่ายศที่ต้องการมอบ)",
                    color=Theme.DANGER,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )


# =========================================================
# ระบบทิกเก็ต (Ticket System)
# =========================================================
class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # ปุ่มถาวร

    @discord.ui.button(
        label="เปิดทิกเก็ต",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="bobbot_ticket_open",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        guild_id = str(guild.id)
        conf = ticket_config.get(guild_id)

        if not conf or not conf.get("category_id"):
            await interaction.response.send_message(
                embed=base_embed(
                    "ยังไม่ได้ตั้งค่า",
                    "❌ ยังไม่ได้ตั้งค่าระบบทิกเก็ต กรุณาแจ้งแอดมินให้ใช้คำสั่ง `/setupticket`",
                    color=Theme.WARNING,
                    guild=guild,
                ),
                ephemeral=True,
            )
            return

        category = guild.get_channel(int(conf["category_id"]))
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                embed=base_embed(
                    "ไม่พบหมวดหมู่",
                    "❌ ไม่พบหมวดหมู่ที่ตั้งค่าไว้ (อาจถูกลบไปแล้ว) กรุณาแจ้งแอดมิน",
                    color=Theme.DANGER,
                    guild=guild,
                ),
                ephemeral=True,
            )
            return

        support_role = guild.get_role(int(conf["support_role_id"])) if conf.get("support_role_id") else None

        # ใช้ user ID แทนชื่อผู้ใช้ในการตั้งชื่อห้อง กัน error จากอักขระพิเศษ/ภาษาอื่นที่ Discord ไม่รับ
        existing_name = f"ticket-{interaction.user.id}"
        for ch in category.text_channels:
            if ch.name == existing_name:
                await interaction.response.send_message(
                    embed=base_embed(
                        "มีทิกเก็ตอยู่แล้ว",
                        f"❌ คุณมีทิกเก็ตที่เปิดอยู่แล้วที่ {ch.mention}",
                        color=Theme.WARNING,
                        guild=guild,
                    ),
                    ephemeral=True,
                )
                return

        await interaction.response.defer(ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, read_message_history=True
            ),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        try:
            ticket_channel = await guild.create_text_channel(
                name=existing_name,
                category=category,
                overwrites=overwrites,
                topic=f"ticket_owner_id:{interaction.user.id}",
                reason=f"เปิดทิกเก็ตโดย {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=base_embed(
                    "ผิดพลาด",
                    "❌ บอทไม่มีสิทธิ์สร้างห้องในหมวดหมู่นี้ กรุณาตรวจสอบสิทธิ์ของบอท",
                    color=Theme.DANGER,
                    guild=guild,
                ),
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            logger.exception(f"สร้างห้องทิกเก็ตไม่สำเร็จสำหรับ {interaction.user}")
            await interaction.followup.send(
                embed=base_embed(
                    "ผิดพลาด",
                    "❌ สร้างห้องทิกเก็ตไม่สำเร็จ กรุณาลองใหม่อีกครั้ง",
                    color=Theme.DANGER,
                    guild=guild,
                ),
                ephemeral=True,
            )
            return

        embed = base_embed(
            "🎫 ทิกเก็ตของคุณ",
            (
                f"สวัสดี {interaction.user.mention} ทีมงานจะเข้ามาช่วยเหลือคุณเร็ว ๆ นี้\n"
                f"{Theme.DIVIDER}\n"
                "กรุณาอธิบายปัญหาหรือคำขอของคุณด้านล่าง ทีมงานจะรีบตอบกลับโดยเร็วที่สุด 💬"
            ),
            color=Theme.TICKET,
            guild=guild,
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        if support_role:
            embed.add_field(name="👥 ทีมงานที่ดูแล", value=support_role.mention, inline=True)
        embed.add_field(name="👤 เปิดโดย", value=interaction.user.mention, inline=True)

        await ticket_channel.send(
            content=support_role.mention if support_role else None,
            embed=embed,
            view=TicketCloseView(),
        )
        await interaction.followup.send(
            embed=base_embed(
                "เปิดทิกเก็ตสำเร็จ ✅",
                f"เปิดทิกเก็ตแล้วที่ {ticket_channel.mention}",
                color=Theme.SUCCESS,
                guild=guild,
            ),
            ephemeral=True,
        )


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # ปุ่มถาวร

    @discord.ui.button(
        label="ปิดทิกเก็ต",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="bobbot_ticket_close",
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        guild_id = str(interaction.guild.id)
        conf = ticket_config.get(guild_id, {})
        support_role_id = conf.get("support_role_id")

        is_owner = False
        if channel.topic and "ticket_owner_id:" in channel.topic:
            try:
                owner_id = int(channel.topic.split("ticket_owner_id:")[1].strip())
                is_owner = owner_id == interaction.user.id
            except ValueError:
                pass

        has_support_role = bool(
            support_role_id and interaction.guild.get_role(int(support_role_id)) in interaction.user.roles
        )
        can_close = is_owner or has_support_role or interaction.user.guild_permissions.manage_channels

        if not can_close:
            await interaction.response.send_message(
                embed=base_embed("ไม่มีสิทธิ์", "❌ คุณไม่มีสิทธิ์ปิดทิกเก็ตนี้", color=Theme.DANGER, guild=interaction.guild),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=base_embed(
                "🔒 กำลังปิดทิกเก็ต",
                f"ห้องนี้จะถูกลบใน 5 วินาที โดย {interaction.user.mention} แล้วเจอกันใหม่ {E('fun_wink', '👋')}",
                color=Theme.WARNING,
                guild=interaction.guild,
            )
        )
        logger.info(f"ทิกเก็ต {channel.name} ถูกปิดโดย {interaction.user}")
        await discord.utils.sleep_until(datetime.datetime.now(timezone.utc) + timedelta(seconds=5))
        try:
            await channel.delete(reason=f"ปิดทิกเก็ตโดย {interaction.user}")
        except discord.NotFound:
            pass


# =========================================================
# ระบบแผงแจกไฟล์/เทมเพลต (Script/File Hub Panel)
# — ผู้ใช้เลือกรายการจาก dropdown แล้วบอทจะส่งไฟล์/ข้อความเข้า DM ให้อัตโนมัติ
# =========================================================
class ScriptHubSelect(discord.ui.Select):
    def __init__(self, guild_id: int, items: list):
        options = [
            discord.SelectOption(
                label=item["label"][:100],
                description=(item.get("description") or "")[:100],
                value=item["label"],
                emoji="📎" if item.get("file_path") else "💬",
            )
            for item in items[:25]  # Discord จำกัดตัวเลือกใน select ไว้ที่ 25
        ]
        if not options:
            options = [discord.SelectOption(label="ยังไม่มีรายการ", value="__empty__", emoji="📭")]
        super().__init__(
            placeholder="✨ เลือกสคริปต์/ไฟล์ที่ต้องการ...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"scripthub_select_{guild_id}",
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "__empty__":
            await interaction.response.send_message(
                embed=base_embed(
                    "ยังไม่มีรายการ",
                    "❌ ยังไม่มีรายการให้เลือก กรุณาแจ้งแอดมินให้เพิ่มด้วย `/scripthub_additem`",
                    color=Theme.WARNING,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
            return

        conf = scripthub_config.get(str(self.guild_id), {})
        items = conf.get("items", [])
        chosen = next((i for i in items if i["label"] == self.values[0]), None)

        if not chosen:
            await interaction.response.send_message(
                embed=base_embed(
                    "ไม่พบรายการ",
                    "❌ ไม่พบรายการนี้แล้ว (อาจถูกลบไป) กรุณากด Refresh Menu แล้วลองใหม่",
                    color=Theme.DANGER,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            files = None
            file_path = chosen.get("file_path")
            if file_path and os.path.exists(file_path):
                files = [discord.File(file_path, filename=chosen.get("file_name") or os.path.basename(file_path))]

            dm_content = chosen.get("content") or f"นี่คือไฟล์ **{chosen['label']}** ของคุณค่ะ"
            await interaction.user.send(content=dm_content, files=files)
            await interaction.followup.send(
                embed=base_embed(
                    "ส่งสำเร็จ ✅",
                    f"ส่ง **{chosen['label']}** เข้า DM ให้แล้ว ตรวจสอบกล่องข้อความส่วนตัวได้เลยครับ 📬 {E('fun_clap', '👏')}",
                    color=Theme.SUCCESS,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=base_embed(
                    "ส่ง DM ไม่ได้",
                    "❌ กรุณาเปิดรับข้อความส่วนตัวจากสมาชิกในเซิร์ฟเวอร์นี้ก่อน (ตั้งค่า Privacy Settings)",
                    color=Theme.DANGER,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
        except discord.HTTPException:
            logger.exception(f"ส่งไฟล์ scripthub ไม่สำเร็จ: {chosen['label']}")
            await interaction.followup.send(
                embed=base_embed(
                    "เกิดข้อผิดพลาด",
                    "❌ เกิดข้อผิดพลาดระหว่างส่งไฟล์ กรุณาลองใหม่อีกครั้ง",
                    color=Theme.DANGER,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )


class ScriptHubRefreshButton(discord.ui.Button):
    def __init__(self, guild_id: int):
        super().__init__(
            label="Refresh Menu",
            style=discord.ButtonStyle.secondary,
            emoji="🔄",
            custom_id=f"scripthub_refresh_{guild_id}",
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        conf = scripthub_config.get(str(self.guild_id), {})
        items = conf.get("items", [])
        new_view = ScriptHubView(self.guild_id, items)
        await interaction.response.edit_message(view=new_view)


class ScriptHubView(discord.ui.View):
    def __init__(self, guild_id: int, items: list):
        super().__init__(timeout=None)  # ปุ่ม/เมนูถาวร ใช้ได้ตลอดแม้บอทรีสตาร์ท
        self.add_item(ScriptHubSelect(guild_id, items))
        self.add_item(ScriptHubRefreshButton(guild_id))


def build_scripthub_embed(conf: dict) -> discord.Embed:
    embed = discord.Embed(
        title=themify(f"📂 {conf.get('title') or 'SCRIPT HUB PANEL'}"),
        description=themify(
            f"{conf.get('description') or 'เลือกสคริปต์ที่ต้องการจากเมนูด้านล่าง แล้วบอทจะส่งเข้า DM ให้ทันที'}\n"
            f"{Theme.DIVIDER}\n"
            "📥 **วิธีใช้:** กดที่เมนู ▾ เลือกรายการ รอรับข้อความทาง DM"
        ),
        color=Theme.SCRIPTHUB,
        timestamp=datetime.datetime.now(timezone.utc),
    )
    if conf.get("image_url"):
        embed.set_image(url=conf["image_url"])
    embed.set_thumbnail(url=bot.user.display_avatar.url if bot.user else None)
    items_count = len(conf.get("items", []))
    embed.set_footer(
        text=f"✨ {bot.user.name if bot.user else 'BOB_BOT'} • {items_count} รายการพร้อมให้บริการ",
        icon_url=bot.user.display_avatar.url if bot.user else None,
    )
    return embed


async def load_custom_emojis():
    """โหลด Application Emoji ของบอทเข้า cache เพื่อให้ E()/themify() เรียกใช้ได้ทันที"""
    try:
        app_emojis = await bot.fetch_application_emojis()
        custom_emoji_cache.clear()
        custom_emoji_cache.update({emoji.name: emoji for emoji in app_emojis})
        logger.info(f"โหลด custom emoji ของบอทแล้ว {len(custom_emoji_cache)} ตัว")
    except discord.HTTPException:
        logger.exception("โหลด custom emoji ของบอทไม่สำเร็จ (จะใช้ unicode emoji แทนไปก่อน)")


@bot.event
async def on_ready():
    logger.info(f"เข้าสู่ระบบในชื่อ {bot.user} (ID: {bot.user.id})")

    # ทำงานหนัก (เรียก API จริง) แค่ครั้งเดียวต่อการรันโปรเซส กัน global rate limit
    # ถ้า reconnect บ่อย ๆ (เช่น hosting ไม่เสถียร) จะไม่ยิง sync/emoji ซ้ำจนโดนบล็อก
    if not bot.startup_done:
        await load_custom_emojis()
        try:
            synced = await bot.tree.sync()
            logger.info(f"ซิงค์ slash command แล้ว {len(synced)} คำสั่ง")
        except discord.HTTPException:
            logger.exception(
                "ซิงค์คำสั่งไม่สำเร็จ (อาจโดน rate limit ชั่วคราว) — คำสั่งเก่ายังใช้งานได้ปกติ จะลองใหม่ตอนรีสตาร์ทครั้งหน้า"
            )
        except Exception:
            logger.exception("เกิดข้อผิดพลาดตอนซิงค์คำสั่ง")
        bot.startup_done = True

    # ส่วนนี้เป็นแค่การลงทะเบียน view ใน local (ไม่เรียก API) ปลอดภัยที่จะทำซ้ำทุกครั้งที่ on_ready
    verify_view = VerifyView()
    ticket_open_view = TicketOpenView()
    ticket_close_view = TicketCloseView()

    # แพตช์ emoji บนปุ่มถาวรให้เป็น custom emoji ของบอท (ถ้ามี) หลังจากโหลด cache แล้ว
    verify_view.verify_button.emoji = E("star", "⭐")
    ticket_open_view.open_ticket.emoji = E("ticket", "🎫")
    ticket_close_view.close_ticket.emoji = E("lock", "🔒")

    bot.add_view(verify_view)  # ลงทะเบียนปุ่มถาวรใหม่ทุกครั้งที่บอทออนไลน์/รีสตาร์ท
    bot.add_view(ticket_open_view)
    bot.add_view(ticket_close_view)
    # ลงทะเบียนแผงแจกไฟล์/เทมเพลตของทุกเซิร์ฟเวอร์ที่เคยตั้งค่าไว้
    for guild_id_str, conf in scripthub_config.items():
        try:
            bot.add_view(ScriptHubView(int(guild_id_str), conf.get("items", [])))
        except (ValueError, TypeError):
            logger.warning(f"ลงทะเบียนแผง scripthub ของ guild {guild_id_str} ไม่สำเร็จ")

    # เปิดสถานะอัตโนมัติทุกครั้งที่บอทออนไลน์ (กันกรณีรีสตาร์ทแล้วลืมสั่งใหม่)
    if not update_status.is_running():
        update_status.start()


@bot.event
async def on_disconnect():
    logger.warning("บอทหลุดการเชื่อมต่อกับ Discord (discord.py จะพยายามเชื่อมต่อใหม่อัตโนมัติ)")


@bot.event
async def on_resumed():
    logger.info("เชื่อมต่อกับ Discord กลับมาได้แล้ว")


@bot.event
async def on_message(message: discord.Message):
    # ยังคงให้ command แบบ prefix (ถ้ามีในอนาคต) ทำงานได้ตามปกติ
    await bot.process_commands(message)

    if message.author.bot or not message.guild:
        return

    guild_id = str(message.guild.id)
    conf = ai_config.get(guild_id)
    if not conf or not conf.get("enabled"):
        return

    bot_mentioned = bot.user in message.mentions
    target_channel_id = conf.get("channel_id")
    in_target_channel = target_channel_id is not None and message.channel.id == int(target_channel_id)

    # ตอบเมื่อ: ถูกแท็ก @บอท ในห้องไหนก็ได้ของกิลด์นี้ หรืออยู่ในห้องที่ตั้งค่าไว้ให้ AI ตอบทุกข้อความ
    if not bot_mentioned and not in_target_channel:
        return

    user_text = message.content
    for mention in message.mentions:
        user_text = user_text.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    user_text = user_text.strip()
    if not user_text:
        return

    persona = conf.get("persona") or DEFAULT_AI_PERSONA

    try:
        async with message.channel.typing():
            reply_text = await generate_ai_reply(
                message.channel.id, persona, message.author.display_name, user_text
            )
    except discord.Forbidden:
        return  # บอทไม่มีสิทธิ์พิมพ์/ส่งข้อความในห้องนี้

    for chunk in split_for_discord(reply_text):
        try:
            await message.reply(chunk, mention_author=False)
        except discord.HTTPException:
            logger.exception("ส่งคำตอบ AI ไม่สำเร็จ")
            break


# =========================================================
# ระบบอัปเดตสถานะบอท (จำนวนเซิร์ฟ/สมาชิก/เวลา)
# =========================================================
DAYS_TH = {
    "Monday": "จันทร์",
    "Tuesday": "อังคาร",
    "Wednesday": "พุธ",
    "Thursday": "พฤหัสบดี",
    "Friday": "ศุกร์",
    "Saturday": "เสาร์",
    "Sunday": "อาทิตย์",
}


# แก้จาก 5 วินาที เป็น 20 วินาที: Discord จำกัดความถี่การอัปเดต presence
# การอัปเดตถี่เกินไปเสี่ยงโดน rate limit หรือหลุดการเชื่อมต่อ
@tasks.loop(seconds=20)
async def update_status():
    try:
        guild_count = len(bot.guilds)
        total_members = sum(g.member_count or 0 for g in bot.guilds)

        now = datetime.datetime.now(timezone(timedelta(hours=7)))
        day_eng = now.strftime("%A")
        day_th = DAYS_TH.get(day_eng, day_eng)
        time_now = now.strftime("%H:%M:%S")

        status_text = (
            f"{guild_count}เซิร์ฟ·⌒ﾞ🍇 {total_members}คนᔕ:･ﾟ🍃 "
            f"วัน {day_th}:･ﾟ☀️ เวลา:･ﾟ({time_now})·⌒ﾞ📆"
        )

        activity = discord.Activity(type=discord.ActivityType.watching, name=status_text)
        await bot.change_presence(activity=activity)
    except Exception:
        # กันไม่ให้ loop ตายทั้งชุดถ้ามี error ชั่วคราวระหว่างอัปเดตสถานะ
        logger.exception("เกิดข้อผิดพลาดระหว่างอัปเดตสถานะ")


@update_status.before_loop
async def before_update_status():
    await bot.wait_until_ready()


@update_status.error
async def update_status_error(error):
    logger.exception(f"update_status loop error: {error}")


@bot.tree.command(name="setupverify", description="ตั้งค่าและส่งข้อความระบบยืนยันตัวตน (กดปุ่มรับยศ)")
@app_commands.describe(role="ยศที่จะมอบให้เมื่อกดยืนยันตัวตน")
@app_commands.checks.has_permissions(manage_roles=True)
async def setupverify(interaction: discord.Interaction, role: discord.Role):
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            embed=base_embed(
                "ยศสูงเกินไป",
                "❌ ยศที่เลือกอยู่สูงกว่าหรือเท่ากับยศของบอท กรุณาเลื่อนยศบอทให้สูงกว่ายศนี้ก่อน",
                color=Theme.DANGER,
                guild=interaction.guild,
            ),
            ephemeral=True,
        )
        return

    verify_config[str(interaction.guild.id)] = role.id
    save_verify_config(verify_config)

    embed = base_embed(
        "⭐ ยืนยันตัวตนเพื่อเข้าใช้งานเซิร์ฟเวอร์",
        (
            f"คลิกปุ่ม **ยืนยันตัวตน** ด้านล่างเพื่อรับยศ {role.mention}\n"
            f"{Theme.DIVIDER}\n"
            "การยืนยันตัวตนจะช่วยปลดล็อกห้องต่าง ๆ ภายในเซิร์ฟเวอร์ให้คุณ ✅"
        ),
        color=Theme.PRIMARY,
        guild=interaction.guild,
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    await interaction.response.send_message(
        embed=base_embed("ตั้งค่าสำเร็จ ✅", "กำลังส่งข้อความยืนยันตัวตน...", color=Theme.SUCCESS, guild=interaction.guild),
        ephemeral=True,
    )
    await interaction.channel.send(embed=embed, view=VerifyView())


# =========================================================
# ยูทิลิตี้: ตรวจสอบสิทธิ์
# =========================================================
def is_mod():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.manage_messages
    return app_commands.check(predicate)


# =========================================================
# หมวด: Moderation (ดูแลสมาชิก/ลบข้อความ)
# =========================================================

@bot.tree.command(name="clear", description="ลบข้อความในห้องนี้ตามจำนวนที่กำหนด")
@app_commands.describe(amount="จำนวนข้อความที่จะลบ (1-100)")
@is_mod()
async def clear(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(
        embed=base_embed(
            "ลบข้อความสำเร็จ 🧹",
            f"ลบข้อความไปแล้ว **{len(deleted)}** ข้อความ สะอาดเอี่ยม {E('fun_clap', '👏')}",
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


@bot.tree.command(name="warn", description="เตือนสมาชิก")
@app_commands.describe(member="สมาชิกที่ต้องการเตือน", reason="เหตุผล")
@is_mod()
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "ไม่ระบุเหตุผล"):
    embed = base_embed(
        "⚠️ คำเตือน",
        f"{member.mention} ถูกเตือนโดย {interaction.user.mention}",
        color=Theme.WARNING,
        guild=interaction.guild,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="📄 เหตุผล", value=reason, inline=False)
    await interaction.response.send_message(embed=embed)
    try:
        await member.send(
            embed=base_embed(
                "คุณถูกเตือน ⚠️",
                f"คุณถูกเตือนในเซิร์ฟเวอร์ **{interaction.guild.name}**",
                color=Theme.WARNING,
                guild=interaction.guild,
            ).add_field(name="📄 เหตุผล", value=reason, inline=False)
        )
    except discord.Forbidden:
        pass


@bot.tree.command(name="kick", description="เตะสมาชิกออกจากเซิร์ฟเวอร์")
@app_commands.describe(member="สมาชิกที่ต้องการเตะ", reason="เหตุผล")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "ไม่ระบุเหตุผล"):
    try:
        await member.kick(reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=base_embed("ไม่มีสิทธิ์", "❌ บอทไม่มีสิทธิ์เตะสมาชิกคนนี้ (ตรวจสอบลำดับยศของบอท)", color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return
    embed = base_embed("👢 เตะสมาชิกออกแล้ว", f"{member.mention} ถูกเตะออกจากเซิร์ฟเวอร์", color=Theme.WARNING, guild=interaction.guild)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="📄 เหตุผล", value=reason, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ban", description="แบนสมาชิกออกจากเซิร์ฟเวอร์")
@app_commands.describe(member="สมาชิกที่ต้องการแบน", reason="เหตุผล")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "ไม่ระบุเหตุผล"):
    try:
        await member.ban(reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=base_embed("ไม่มีสิทธิ์", "❌ บอทไม่มีสิทธิ์แบนสมาชิกคนนี้ (ตรวจสอบลำดับยศของบอท)", color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return
    embed = base_embed("🔨 แบนสมาชิกแล้ว", f"{member.mention} ถูกแบนออกจากเซิร์ฟเวอร์", color=Theme.DANGER, guild=interaction.guild)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="📄 เหตุผล", value=reason, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="timeout", description="ปิดปากสมาชิกชั่วคราว (timeout)")
@app_commands.describe(member="สมาชิก", minutes="ระยะเวลา (นาที)", reason="เหตุผล")
@is_mod()
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 10080], reason: str = "ไม่ระบุเหตุผล"):
    duration = datetime.timedelta(minutes=minutes)
    try:
        await member.timeout(duration, reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=base_embed("ไม่มีสิทธิ์", "❌ บอทไม่มีสิทธิ์ timeout สมาชิกคนนี้ (ตรวจสอบลำดับยศของบอท)", color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return
    embed = base_embed("🔇 ปิดปากชั่วคราว", f"{member.mention} ถูกปิดปากเป็นเวลา **{minutes} นาที**", color=Theme.WARNING, guild=interaction.guild)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="📄 เหตุผล", value=reason, inline=False)
    await interaction.response.send_message(embed=embed)


# =========================================================
# หมวด: จัดการยศ/บทบาท (Role Management)
# =========================================================

@bot.tree.command(name="addrole", description="เพิ่มยศให้สมาชิก")
@app_commands.describe(member="สมาชิก", role="ยศที่ต้องการเพิ่ม")
@app_commands.checks.has_permissions(manage_roles=True)
async def addrole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.add_roles(role)
    await interaction.response.send_message(
        embed=base_embed(
            "เพิ่มยศสำเร็จ ✅",
            f"เพิ่มยศ {role.mention} ให้ {member.mention} แล้ว {E('fun_thumbsup', '👍')}",
            color=Theme.SUCCESS,
            guild=interaction.guild,
        )
    )


@bot.tree.command(name="removerole", description="ลบยศออกจากสมาชิก")
@app_commands.describe(member="สมาชิก", role="ยศที่ต้องการลบ")
@app_commands.checks.has_permissions(manage_roles=True)
async def removerole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    await interaction.response.send_message(
        embed=base_embed(
            "ลบยศสำเร็จ ➖",
            f"ลบยศ {role.mention} ออกจาก {member.mention} แล้ว {E('fun_ohno', '😅')}",
            color=Theme.WARNING,
            guild=interaction.guild,
        )
    )


@bot.tree.command(name="nick", description="เปลี่ยนชื่อเล่นของสมาชิก")
@app_commands.describe(member="สมาชิก", new_nick="ชื่อเล่นใหม่")
@app_commands.checks.has_permissions(manage_nicknames=True)
async def nick(interaction: discord.Interaction, member: discord.Member, new_nick: str):
    await member.edit(nick=new_nick)
    await interaction.response.send_message(
        embed=base_embed(
            "เปลี่ยนชื่อเล่นสำเร็จ ✏️",
            f"เปลี่ยนชื่อเล่นของ {member.mention} เป็น **{new_nick}** แล้ว {E('fun_laughter', '😂')}",
            color=Theme.SUCCESS,
            guild=interaction.guild,
        )
    )


# =========================================================
# หมวด: ระบบรับยศด้วยรีแอค (Reaction Role Menu)
# =========================================================

@bot.tree.command(name="rolemenu_create", description="สร้างข้อความเมนูรับยศ (ยังไม่มีตัวเลือก ให้ใช้ /rolemenu_add ต่อ)")
@app_commands.describe(title="หัวข้อของเมนู", description="คำอธิบายของเมนู")
@app_commands.checks.has_permissions(manage_roles=True)
async def rolemenu_create(interaction: discord.Interaction, title: str, description: str = "รีแอคอิโมจิด้านล่างเพื่อรับ/ถอดยศ"):
    embed = base_embed(f"🎭 {title}", f"{description}\n{Theme.DIVIDER}", color=Theme.PRIMARY, guild=interaction.guild)
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    await interaction.response.send_message(
        embed=base_embed("กำลังสร้าง ✅", "กำลังสร้างเมนูรับยศ...", color=Theme.SUCCESS, guild=interaction.guild),
        ephemeral=True,
    )
    msg = await interaction.channel.send(embed=embed)

    guild_id = str(interaction.guild.id)
    reactionrole_config.setdefault(guild_id, {})[str(msg.id)] = {}
    save_reactionrole_config(reactionrole_config)

    await interaction.edit_original_response(
        content=f"✅ สร้างเมนูเรียบร้อย ใช้คำสั่ง `/rolemenu_add message_id:{msg.id}` เพื่อเพิ่มตัวเลือกยศ"
    )


@bot.tree.command(name="rolemenu_add", description="เพิ่มตัวเลือก อิโมจิ+ยศ เข้าไปในเมนูรับยศ")
@app_commands.describe(message_id="ID ของข้อความเมนู (จาก /rolemenu_create)", emoji="อิโมจิที่จะใช้ (พิมพ์หรือวางอิโมจิ)", role="ยศที่จะมอบเมื่อรีแอค")
@app_commands.checks.has_permissions(manage_roles=True)
async def rolemenu_add(interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            embed=base_embed("ยศสูงเกินไป", "❌ ยศที่เลือกอยู่สูงกว่าหรือเท่ากับยศของบอท กรุณาเลื่อนยศบอทให้สูงกว่ายศนี้ก่อน", color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    guild_id = str(interaction.guild.id)
    guild_conf = reactionrole_config.get(guild_id, {})
    if message_id not in guild_conf:
        await interaction.response.send_message(
            embed=base_embed("ไม่พบเมนู", "❌ ไม่พบเมนูนี้ กรุณาสร้างด้วย `/rolemenu_create` ก่อน", color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    try:
        target_msg = await interaction.channel.fetch_message(int(message_id))
    except (discord.NotFound, ValueError):
        await interaction.response.send_message(
            embed=base_embed("ไม่พบข้อความ", "❌ ไม่พบข้อความนี้ในห้องนี้ กรุณาใช้คำสั่งในห้องเดียวกับที่สร้างเมนู", color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    try:
        await target_msg.add_reaction(emoji)
    except discord.HTTPException:
        await interaction.response.send_message(
            embed=base_embed("อิโมจิไม่ถูกต้อง", "❌ อิโมจิไม่ถูกต้อง หรือบอทใช้อิโมจินี้ไม่ได้", color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    guild_conf[message_id][emoji] = role.id
    save_reactionrole_config(reactionrole_config)

    embed = target_msg.embeds[0]
    embed.add_field(name=emoji, value=role.mention, inline=True)
    await target_msg.edit(embed=embed)

    await interaction.response.send_message(
        embed=base_embed("เพิ่มตัวเลือกสำเร็จ ✅", f"เพิ่ม {emoji} → {role.mention} เข้าเมนูแล้ว", color=Theme.SUCCESS, guild=interaction.guild),
        ephemeral=True,
    )


@bot.tree.command(name="rolemenu_remove", description="ลบตัวเลือก อิโมจิ ออกจากเมนูรับยศ")
@app_commands.describe(message_id="ID ของข้อความเมนู", emoji="อิโมจิที่จะลบออก")
@app_commands.checks.has_permissions(manage_roles=True)
async def rolemenu_remove(interaction: discord.Interaction, message_id: str, emoji: str):
    guild_id = str(interaction.guild.id)
    guild_conf = reactionrole_config.get(guild_id, {})
    mapping = guild_conf.get(message_id)

    if not mapping or emoji not in mapping:
        await interaction.response.send_message(
            embed=base_embed("ไม่พบตัวเลือก", "❌ ไม่พบตัวเลือกนี้ในเมนู", color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    del mapping[emoji]
    save_reactionrole_config(reactionrole_config)

    try:
        target_msg = await interaction.channel.fetch_message(int(message_id))
        await target_msg.clear_reaction(emoji)
        embed = target_msg.embeds[0]
        embed.clear_fields()
        for e, rid in mapping.items():
            r = interaction.guild.get_role(rid)
            embed.add_field(name=e, value=r.mention if r else "(ยศถูกลบ)", inline=True)
        await target_msg.edit(embed=embed)
    except (discord.NotFound, ValueError, discord.HTTPException):
        pass

    await interaction.response.send_message(
        embed=base_embed("ลบตัวเลือกสำเร็จ ✅", f"ลบ {emoji} ออกจากเมนูแล้ว", color=Theme.SUCCESS, guild=interaction.guild),
        ephemeral=True,
    )


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id or payload.guild_id is None:
        return

    guild_conf = reactionrole_config.get(str(payload.guild_id))
    if not guild_conf:
        return
    mapping = guild_conf.get(str(payload.message_id))
    if not mapping:
        return

    emoji_str = str(payload.emoji)
    role_id = mapping.get(emoji_str)
    if not role_id:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    role = guild.get_role(role_id)
    if not role:
        return

    try:
        member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
    except discord.NotFound:
        return

    try:
        await member.add_roles(role, reason="รับยศผ่านเมนูรีแอค")
    except discord.Forbidden:
        logger.warning(f"ไม่มีสิทธิ์มอบยศ {role} ให้ {member} ผ่านเมนูรีแอค")


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id or payload.guild_id is None:
        return

    guild_conf = reactionrole_config.get(str(payload.guild_id))
    if not guild_conf:
        return
    mapping = guild_conf.get(str(payload.message_id))
    if not mapping:
        return

    emoji_str = str(payload.emoji)
    role_id = mapping.get(emoji_str)
    if not role_id:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    role = guild.get_role(role_id)
    if not role:
        return

    try:
        member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
    except discord.NotFound:
        return

    try:
        await member.remove_roles(role, reason="ถอดยศผ่านเมนูรีแอค")
    except discord.Forbidden:
        logger.warning(f"ไม่มีสิทธิ์ถอดยศ {role} จาก {member} ผ่านเมนูรีแอค")


# =========================================================
# หมวด: ระบบทิกเก็ต (Ticket System) — คำสั่งตั้งค่า
# =========================================================

@bot.tree.command(name="setupticket", description="ตั้งค่าและส่งข้อความระบบเปิดทิกเก็ต")
@app_commands.describe(category="หมวดหมู่ที่จะสร้างห้องทิกเก็ต", support_role="ยศทีมงานที่จะเห็นทิกเก็ต (ไม่ใส่ก็ได้)")
@app_commands.checks.has_permissions(manage_guild=True)
async def setupticket(interaction: discord.Interaction, category: discord.CategoryChannel, support_role: discord.Role = None):
    guild_id = str(interaction.guild.id)
    ticket_config[guild_id] = {
        "category_id": category.id,
        "support_role_id": support_role.id if support_role else None,
    }
    save_ticket_config(ticket_config)

    embed = base_embed(
        "🎫 ติดต่อทีมงาน",
        (
            "กดปุ่มด้านล่างเพื่อเปิดทิกเก็ตส่วนตัวสำหรับติดต่อทีมงาน\n"
            f"{Theme.DIVIDER}\n"
            "ทีมงานจะเข้ามาช่วยเหลือคุณโดยเร็วที่สุด 💬"
        ),
        color=Theme.TICKET,
        guild=interaction.guild,
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    await interaction.response.send_message(
        embed=base_embed("ตั้งค่าสำเร็จ ✅", "กำลังส่งข้อความระบบทิกเก็ต...", color=Theme.SUCCESS, guild=interaction.guild),
        ephemeral=True,
    )
    await interaction.channel.send(embed=embed, view=TicketOpenView())


@bot.tree.command(name="closeticket", description="ปิดทิกเก็ตปัจจุบัน (ใช้ในห้องทิกเก็ตเท่านั้น)")
async def closeticket(interaction: discord.Interaction):
    channel = interaction.channel
    guild_id = str(interaction.guild.id)
    conf = ticket_config.get(guild_id, {})

    if not channel.topic or "ticket_owner_id:" not in channel.topic:
        await interaction.response.send_message(
            embed=base_embed("ไม่ใช่ห้องทิกเก็ต", "❌ ห้องนี้ไม่ใช่ห้องทิกเก็ต", color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    owner_id = int(channel.topic.split("ticket_owner_id:")[1].strip())
    support_role_id = conf.get("support_role_id")
    has_support_role = bool(
        support_role_id and interaction.guild.get_role(int(support_role_id)) in interaction.user.roles
    )
    can_close = owner_id == interaction.user.id or has_support_role or interaction.user.guild_permissions.manage_channels

    if not can_close:
        await interaction.response.send_message(
            embed=base_embed("ไม่มีสิทธิ์", "❌ คุณไม่มีสิทธิ์ปิดทิกเก็ตนี้", color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        embed=base_embed("🔒 กำลังปิดทิกเก็ต", f"ห้องนี้จะถูกลบใน 5 วินาที โดย {interaction.user.mention}", color=Theme.WARNING, guild=interaction.guild)
    )
    await discord.utils.sleep_until(datetime.datetime.now(timezone.utc) + timedelta(seconds=5))
    try:
        await channel.delete(reason=f"ปิดทิกเก็ตโดย {interaction.user}")
    except discord.NotFound:
        pass


# =========================================================
# หมวด: แผงแจกไฟล์/เทมเพลต (Script/File Hub Panel)
# =========================================================

@bot.tree.command(name="scripthub_setup", description="สร้าง/อัปเดตแผงแจกไฟล์-เทมเพลต (มีเมนู dropdown ให้เลือก)")
@app_commands.describe(
    title="หัวข้อของแผง เช่น SCRIPT HUB PANEL",
    description="คำอธิบายใต้หัวข้อ",
    image_url="URL รูปภาพประกอบ (ไม่ใส่ก็ได้)",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def scripthub_setup(
    interaction: discord.Interaction, title: str, description: str, image_url: str = None
):
    guild_id = str(interaction.guild.id)
    conf = scripthub_config.get(guild_id, {"items": []})
    conf["title"] = title
    conf["description"] = description
    conf["image_url"] = image_url

    embed = build_scripthub_embed(conf)
    view = ScriptHubView(interaction.guild.id, conf.get("items", []))

    await interaction.response.send_message(
        embed=base_embed("กำลังสร้างแผง ✅", "กำลังสร้างแผงแจกไฟล์...", color=Theme.SUCCESS, guild=interaction.guild),
        ephemeral=True,
    )
    msg = await interaction.channel.send(embed=embed, view=view)

    conf["channel_id"] = interaction.channel.id
    conf["message_id"] = msg.id
    scripthub_config[guild_id] = conf
    save_scripthub_config(scripthub_config)

    await interaction.edit_original_response(content="✅ สร้างแผงเรียบร้อย ใช้ /scripthub_additem เพื่อเพิ่มรายการต่อได้เลย")


@bot.tree.command(name="scripthub_additem", description="เพิ่มรายการไฟล์/เทมเพลตเข้าแผง (แนบไฟล์ หรือใส่ข้อความก็ได้)")
@app_commands.describe(
    label="ชื่อรายการที่จะแสดงในเมนู (สั้น ๆ ไม่เกิน 100 ตัวอักษร)",
    description="คำอธิบายสั้น ๆ ของรายการ (แสดงในเมนู)",
    content="ข้อความที่จะแนบไปกับ DM (ไม่ใส่ก็ได้ ถ้าแนบไฟล์)",
    file="ไฟล์ที่จะส่งให้ผู้ใช้ (ไม่ใส่ก็ได้ ถ้ามีแค่ข้อความ)",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def scripthub_additem(
    interaction: discord.Interaction,
    label: str,
    description: str = "",
    content: str = None,
    file: discord.Attachment = None,
):
    if not content and not file:
        await interaction.response.send_message(
            embed=base_embed("ข้อมูลไม่ครบ", "❌ ต้องใส่อย่างน้อยหนึ่งอย่าง: ข้อความ (content) หรือไฟล์แนบ (file)", color=Theme.WARNING, guild=interaction.guild),
            ephemeral=True,
        )
        return

    guild_id = str(interaction.guild.id)
    conf = scripthub_config.get(guild_id)
    if not conf:
        await interaction.response.send_message(
            embed=base_embed("ยังไม่ได้สร้างแผง", "❌ ยังไม่ได้สร้างแผงในเซิร์ฟเวอร์นี้ กรุณาใช้ `/scripthub_setup` ก่อน", color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    items = conf.setdefault("items", [])
    if any(i["label"] == label for i in items):
        await interaction.response.send_message(
            embed=base_embed("ชื่อซ้ำ", "❌ มีรายการชื่อนี้อยู่แล้ว กรุณาใช้ชื่ออื่น", color=Theme.WARNING, guild=interaction.guild),
            ephemeral=True,
        )
        return
    if len(items) >= 25:
        await interaction.response.send_message(
            embed=base_embed("เต็มแล้ว", "❌ แผงนี้มีรายการครบ 25 แล้ว (ข้อจำกัดของ Discord)", color=Theme.WARNING, guild=interaction.guild),
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    file_path = None
    file_name = None
    if file:
        guild_dir = os.path.join(SCRIPTHUB_FILES_DIR, guild_id)
        os.makedirs(guild_dir, exist_ok=True)
        # sanitize ทั้ง label และชื่อไฟล์ก่อนประกอบเป็น path จริง กัน path traversal
        safe_label = safe_filename_part(label, fallback="item")
        safe_name = safe_filename_part(file.filename, fallback="file")
        file_path = os.path.join(guild_dir, f"{safe_label}_{safe_name}")
        await file.save(file_path)
        file_name = file.filename

    items.append(
        {
            "label": label,
            "description": description,
            "content": content,
            "file_path": file_path,
            "file_name": file_name,
        }
    )
    save_scripthub_config(scripthub_config)

    # อัปเดตแผงที่แสดงอยู่จริง (ถ้ามี) ให้เมนูมีตัวเลือกใหม่ทันที
    updated_live = False
    if conf.get("channel_id") and conf.get("message_id"):
        try:
            channel = interaction.guild.get_channel(int(conf["channel_id"]))
            msg = await channel.fetch_message(int(conf["message_id"]))
            await msg.edit(embed=build_scripthub_embed(conf), view=ScriptHubView(interaction.guild.id, items))
            updated_live = True
        except (discord.NotFound, discord.Forbidden, AttributeError):
            pass

    note = "และอัปเดตแผงที่แสดงอยู่ให้แล้ว" if updated_live else "(หาแผงที่แสดงอยู่ไม่เจอ ลองกด Refresh Menu บนแผงเอง)"
    await interaction.followup.send(
        embed=base_embed("เพิ่มรายการสำเร็จ ✅", f"เพิ่มรายการ **{label}** เรียบร้อย {note}", color=Theme.SUCCESS, guild=interaction.guild),
        ephemeral=True,
    )


@bot.tree.command(name="scripthub_removeitem", description="ลบรายการไฟล์/เทมเพลตออกจากแผง")
@app_commands.describe(label="ชื่อรายการที่ต้องการลบ")
@app_commands.checks.has_permissions(manage_guild=True)
async def scripthub_removeitem(interaction: discord.Interaction, label: str):
    guild_id = str(interaction.guild.id)
    conf = scripthub_config.get(guild_id)
    if not conf or not conf.get("items"):
        await interaction.response.send_message(
            embed=base_embed("ไม่มีรายการ", "❌ ยังไม่มีรายการใด ๆ ในแผงนี้", color=Theme.WARNING, guild=interaction.guild),
            ephemeral=True,
        )
        return

    items = conf["items"]
    target = next((i for i in items if i["label"] == label), None)
    if not target:
        await interaction.response.send_message(
            embed=base_embed("ไม่พบรายการ", "❌ ไม่พบรายการนี้", color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    items.remove(target)
    if target.get("file_path") and os.path.exists(target["file_path"]):
        try:
            os.remove(target["file_path"])
        except OSError:
            pass
    save_scripthub_config(scripthub_config)

    updated_live = False
    if conf.get("channel_id") and conf.get("message_id"):
        try:
            channel = interaction.guild.get_channel(int(conf["channel_id"]))
            msg = await channel.fetch_message(int(conf["message_id"]))
            await msg.edit(embed=build_scripthub_embed(conf), view=ScriptHubView(interaction.guild.id, items))
            updated_live = True
        except (discord.NotFound, discord.Forbidden, AttributeError):
            pass

    note = "และอัปเดตแผงที่แสดงอยู่ให้แล้ว" if updated_live else "(ลองกด Refresh Menu บนแผงเอง)"
    await interaction.response.send_message(
        embed=base_embed("ลบรายการสำเร็จ ✅", f"ลบรายการ **{label}** แล้ว {note}", color=Theme.SUCCESS, guild=interaction.guild),
        ephemeral=True,
    )


@bot.tree.command(name="scripthub_listitems", description="ดูรายการไฟล์/เทมเพลตทั้งหมดในแผงของเซิร์ฟเวอร์นี้")
@app_commands.checks.has_permissions(manage_guild=True)
async def scripthub_listitems(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    conf = scripthub_config.get(guild_id)
    items = conf.get("items", []) if conf else []

    if not items:
        await interaction.response.send_message(
            embed=base_embed("ว่างเปล่า", "📭 ยังไม่มีรายการในแผงนี้", color=Theme.WARNING, guild=interaction.guild),
            ephemeral=True,
        )
        return

    lines = []
    for i in items:
        kind = "📎 ไฟล์" if i.get("file_path") else "💬 ข้อความ"
        lines.append(f"**• {i['label']}** — {i.get('description') or '-'}  `{kind}`")

    embed = base_embed(
        "📋 รายการในแผงแจกไฟล์/เทมเพลต",
        "\n".join(lines),
        color=Theme.SCRIPTHUB,
        guild=interaction.guild,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# หมวด: ระบบ AI ตอบแชท (Google Gemini)
# =========================================================

@bot.tree.command(name="ai_setup", description="ตั้งค่าระบบ AI ตอบแชทสำหรับเซิร์ฟเวอร์นี้")
@app_commands.describe(
    channel="ห้องที่ต้องการให้ AI ตอบทุกข้อความ (ไม่ใส่ = ตอบเฉพาะตอนถูกแท็ก @บอท เท่านั้น)",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def ai_setup(interaction: discord.Interaction, channel: discord.TextChannel = None):
    guild_id = str(interaction.guild.id)
    conf = ai_config.get(guild_id, {"enabled": True, "channel_id": None, "persona": None})
    conf["enabled"] = True
    conf["channel_id"] = channel.id if channel else None
    ai_config[guild_id] = conf
    save_ai_config(ai_config)

    where = channel.mention if channel else "การแท็ก @บอท ในห้องไหนก็ได้ของเซิร์ฟเวอร์นี้"
    await interaction.response.send_message(
        embed=base_embed(
            "ตั้งค่า AI สำเร็จ ✅",
            f"เปิดใช้งานระบบ AI ตอบแชทแล้ว\nขอบเขตการตอบ: {where}",
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


@bot.tree.command(name="ai_toggle", description="เปิด/ปิดระบบ AI ตอบแชทสำหรับเซิร์ฟเวอร์นี้")
@app_commands.describe(enabled="เปิด (True) หรือ ปิด (False)")
@app_commands.checks.has_permissions(manage_guild=True)
async def ai_toggle(interaction: discord.Interaction, enabled: bool):
    guild_id = str(interaction.guild.id)
    conf = ai_config.get(guild_id, {"enabled": True, "channel_id": None, "persona": None})
    conf["enabled"] = enabled
    ai_config[guild_id] = conf
    save_ai_config(ai_config)

    status_text = "เปิดใช้งาน ✅" if enabled else "ปิดใช้งาน ⛔"
    await interaction.response.send_message(
        embed=base_embed(
            "อัปเดตแล้ว",
            f"ระบบ AI ตอบแชท: {status_text}",
            color=Theme.SUCCESS if enabled else Theme.WARNING,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


@bot.tree.command(name="ai_persona", description="ตั้งค่าบุคลิก/กติกาพื้นฐานของ AI (system prompt)")
@app_commands.describe(persona="คำอธิบายบุคลิก/กติกาที่ต้องการให้ AI ยึดถือ")
@app_commands.checks.has_permissions(manage_guild=True)
async def ai_persona(interaction: discord.Interaction, persona: str):
    guild_id = str(interaction.guild.id)
    conf = ai_config.get(guild_id, {"enabled": True, "channel_id": None, "persona": None})
    conf["persona"] = persona
    ai_config[guild_id] = conf
    save_ai_config(ai_config)

    await interaction.response.send_message(
        embed=base_embed(
            "ตั้งค่าบุคลิกสำเร็จ ✅",
            "อัปเดต persona ของ AI แล้ว ข้อความถัดไปจะใช้กติกาใหม่นี้",
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


@bot.tree.command(name="ai_reset", description="ล้างความจำการสนทนา AI ของห้องนี้")
@app_commands.checks.has_permissions(manage_messages=True)
async def ai_reset(interaction: discord.Interaction):
    ai_conversations.pop(interaction.channel.id, None)
    await interaction.response.send_message(
        embed=base_embed(
            "ล้างความจำแล้ว ✅",
            "AI จะเริ่มบทสนทนาใหม่ในห้องนี้ (ไม่มีประวัติเก่าติดมา)",
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


# =========================================================
# หมวด: คำสั่งทั่วไป (General Commands)
# =========================================================

@bot.tree.command(name="ping", description="ตรวจสอบความหน่วงของบอท")
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    if latency_ms < 150:
        color, mood = Theme.SUCCESS, E("fun_perfect", "😎")
    elif latency_ms < 300:
        color, mood = Theme.WARNING, E("fun_ok", "😐")
    else:
        color, mood = Theme.DANGER, E("fun_nervous", "😬")
    embed = base_embed("🏓 Pong!", f"ความหน่วงของบอทตอนนี้อยู่ที่ **{latency_ms}ms** {mood}", color=color, guild=interaction.guild)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="userinfo", description="ดูข้อมูลสมาชิก")
@app_commands.describe(member="สมาชิกที่ต้องการดูข้อมูล (ไม่ใส่ = ตัวเอง)")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed = base_embed(f"👤 ข้อมูลของ {member.display_name}", color=Theme.INFO, guild=interaction.guild)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🏷️ ชื่อผู้ใช้", value=str(member), inline=True)
    embed.add_field(name="🆔 ID", value=f"`{member.id}`", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="📥 เข้าร่วมเซิร์ฟเวอร์เมื่อ", value=member.joined_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="🎂 สร้างบัญชีเมื่อ", value=member.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    embed.add_field(name=f"🎭 ยศ ({len(roles)})", value=", ".join(roles) if roles else "ไม่มี", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="serverinfo", description="ดูข้อมูลเซิร์ฟเวอร์")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = base_embed(f"🏰 {guild.name}", color=Theme.PRIMARY, guild=guild)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    if guild.banner:
        embed.set_image(url=guild.banner.url)
    embed.add_field(name="👑 เจ้าของ", value=guild.owner.mention if guild.owner else "-", inline=True)
    embed.add_field(name="👥 จำนวนสมาชิก", value=f"{guild.member_count:,}", inline=True)
    embed.add_field(name="🚀 บูสต์", value=f"ระดับ {guild.premium_tier} ({guild.premium_subscription_count} บูสต์)", inline=True)
    embed.add_field(name="📅 สร้างเมื่อ", value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="💬 จำนวนห้อง", value=len(guild.channels), inline=True)
    embed.add_field(name="🎭 จำนวนยศ", value=len(guild.roles), inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="poll", description="สร้างโพลแบบง่าย (โหวต 👍/👎)")
@app_commands.describe(question="คำถามของโพล")
async def poll(interaction: discord.Interaction, question: str):
    embed = base_embed(
        "📊 โพลใหม่",
        f"**{question}**\n{Theme.DIVIDER}\nกดรีแอคด้านล่างเพื่อโหวต {E('fun_gamer', '🎮')}",
        color=Theme.INFO,
        guild=interaction.guild,
    )
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")


@bot.tree.command(name="say", description="ให้บอทพูดข้อความแทนคุณ")
@app_commands.describe(message="ข้อความที่ต้องการให้บอทพูด")
@is_mod()
async def say(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(
        embed=base_embed(
            "ส่งข้อความแล้ว ✅",
            f"ข้อความถูกส่งเรียบร้อย {E('fun_wink', '😉')}",
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )
    await interaction.channel.send(message)


@bot.tree.command(name="help", description="แสดงรายการคำสั่งทั้งหมด")
async def help_command(interaction: discord.Interaction):
    embed = base_embed(
        "📖 คำสั่งทั้งหมดของ BOB_BOT",
        f"รวมทุกคำสั่งที่ใช้งานได้ในเซิร์ฟเวอร์นี้\n{Theme.DIVIDER}",
        color=Theme.PRIMARY,
        guild=interaction.guild,
    )
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.add_field(
        name="🛡️ Moderation",
        value="`/clear` `/warn` `/kick` `/ban` `/timeout`",
        inline=False
    )
    embed.add_field(
        name="🎭 จัดการยศ",
        value="`/addrole` `/removerole` `/nick`",
        inline=False
    )
    embed.add_field(
        name="💬 ทั่วไป",
        value="`/ping` `/userinfo` `/serverinfo` `/poll` `/say`",
        inline=False
    )
    embed.add_field(
        name="⭐ ยืนยันตัวตน",
        value="`/setupverify` — ตั้งค่า+ส่งข้อความยืนยันตัวตน (กดปุ่มรับยศ)",
        inline=False
    )
    embed.add_field(
        name="🎭 เมนูรับยศด้วยรีแอค",
        value=(
            "`/rolemenu_create` — สร้างเมนูรับยศ\n"
            "`/rolemenu_add` — เพิ่มอิโมจิ+ยศเข้าเมนู\n"
            "`/rolemenu_remove` — ลบอิโมจิออกจากเมนู"
        ),
        inline=False
    )
    embed.add_field(
        name="🎫 ระบบทิกเก็ต",
        value=(
            "`/setupticket` — ตั้งค่า+ส่งข้อความเปิดทิกเก็ต\n"
            "`/closeticket` — ปิดทิกเก็ตปัจจุบัน (หรือกดปุ่มในห้องทิกเก็ต)"
        ),
        inline=False
    )
    embed.add_field(
        name="📂 แผงแจกไฟล์/เทมเพลต (Script Hub)",
        value=(
            "`/scripthub_setup` — สร้าง/อัปเดตแผง (มีเมนู dropdown)\n"
            "`/scripthub_additem` — เพิ่มรายการไฟล์/ข้อความเข้าแผง\n"
            "`/scripthub_removeitem` — ลบรายการออกจากแผง\n"
            "`/scripthub_listitems` — ดูรายการทั้งหมดในแผง"
        ),
        inline=False
    )
    embed.add_field(
        name="🤖 AI ตอบแชท",
        value=(
            "`/ai_setup` — เปิดใช้งาน + เลือกห้องที่ให้ AI ตอบทุกข้อความ (ไม่เลือก = ตอบเมื่อถูกแท็ก)\n"
            "`/ai_toggle` — เปิด/ปิดระบบ\n"
            "`/ai_persona` — ตั้งค่าบุคลิก/กติกาของ AI\n"
            "`/ai_reset` — ล้างความจำการสนทนาของห้องนี้"
        ),
        inline=False
    )
    await interaction.response.send_message(embed=embed)


# =========================================================
# จัดการข้อผิดพลาด (Error Handling)
# =========================================================
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้"
    elif isinstance(error, app_commands.CheckFailure):
        msg = "❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้"
    else:
        # ไม่ส่ง raw error message กลับไปหาผู้ใช้ (กันหลุด internal detail) — เก็บรายละเอียดไว้ใน log แทน
        msg = "❌ เกิดข้อผิดพลาดขณะทำคำสั่งนี้ กรุณาลองใหม่อีกครั้ง"
        logger.exception(f"Unhandled app command error: {error}")

    embed = base_embed("เกิดข้อผิดพลาด", msg, color=Theme.DANGER, guild=interaction.guild if interaction.guild else None)

    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        logger.error(
            "ไม่พบ DISCORD_TOKEN — กรุณาสร้างไฟล์ .env (ดูตัวอย่างใน .env.example) "
            "แล้วใส่ DISCORD_TOKEN=โทเคนของคุณ ก่อนรันบอท"
        )
    else:
        start_keep_alive()  # เปิด HTTP server เล็ก ๆ ไว้ก่อน เพื่อให้ Render ping ได้
        try:
            # discord.py มี reconnect logic ในตัวอยู่แล้วสำหรับการหลุดชั่วคราว
            bot.run(TOKEN, log_handler=None)
        except discord.LoginFailure:
            logger.error("Token ไม่ถูกต้อง กรุณาตรวจสอบค่า DISCORD_TOKEN ใน .env")
        except Exception:
            logger.exception("บอทหยุดทำงานเพราะเกิดข้อผิดพลาดที่ไม่คาดคิด")
            raise  # ให้ตัวคุมโปรเซสภายนอก (systemd/pm2) จับแล้วรีสตาร์ทให้
