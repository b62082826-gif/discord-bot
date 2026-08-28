import os
import json
import logging
import datetime
from datetime import timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

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
# อ่านค่า TOKEN ให้ถูกต้อง (แก้บั๊กเดิมที่เอา token ไปเป็น "ชื่อ" env var)
# ---------------------------------------------------------
# แก้ไขให้เหลือเฉพาะชื่อตัวแปรในวงเล็บ
TOKEN = os.getenv("BOT_TOKEN")
_raw_secret_id = os.getenv("SECRET_STATUS_USER_ID", "1524722784817909811")

SECRET_STATUS_USER_ID = int(_raw_secret_id) if _raw_secret_id.isdigit() else 0

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

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


# โครงสร้าง: { "guild_id": {"category_id": int, "support_role_id": int, "ticket_count": int} }
ticket_config = load_ticket_config()


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
                "❌ ยังไม่ได้ตั้งค่ายศยืนยันตัวตนสำหรับเซิร์ฟเวอร์นี้ กรุณาแจ้งแอดมินให้ใช้คำสั่ง /setupverify",
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(int(role_id))
        if not role:
            await interaction.response.send_message(
                "❌ ไม่พบยศที่ตั้งค่าไว้ (อาจถูกลบไปแล้ว) กรุณาแจ้งแอดมิน", ephemeral=True
            )
            return

        if role in interaction.user.roles:
            await interaction.response.send_message("✅ คุณยืนยันตัวตนไปแล้ว", ephemeral=True)
            return

        try:
            await interaction.user.add_roles(role, reason="ยืนยันตัวตนผ่านปุ่ม")
            await interaction.response.send_message(
                f"🎉 ยืนยันตัวตนสำเร็จ! คุณได้รับยศ {role.mention} แล้ว", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ บอทไม่มีสิทธิ์มอบยศนี้ (ตรวจสอบว่ายศของบอทอยู่สูงกว่ายศที่ต้องการมอบ)",
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
                "❌ ยังไม่ได้ตั้งค่าระบบทิกเก็ต กรุณาแจ้งแอดมินให้ใช้คำสั่ง /setupticket",
                ephemeral=True,
            )
            return

        category = guild.get_channel(int(conf["category_id"]))
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "❌ ไม่พบหมวดหมู่ที่ตั้งค่าไว้ (อาจถูกลบไปแล้ว) กรุณาแจ้งแอดมิน", ephemeral=True
            )
            return

        support_role = guild.get_role(int(conf["support_role_id"])) if conf.get("support_role_id") else None

        # กันไม่ให้เปิดทิกเก็ตซ้ำ ถ้ามีห้องเปิดอยู่แล้ว
        existing_name = f"ticket-{interaction.user.name}".lower().replace(" ", "-")
        for ch in category.text_channels:
            if ch.name == existing_name:
                await interaction.response.send_message(
                    f"❌ คุณมีทิกเก็ตที่เปิดอยู่แล้วที่ {ch.mention}", ephemeral=True
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
                "❌ บอทไม่มีสิทธิ์สร้างห้องในหมวดหมู่นี้ กรุณาตรวจสอบสิทธิ์ของบอท", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🎫 ทิกเก็ตของคุณ",
            description=(
                f"สวัสดี {interaction.user.mention} ทีมงานจะเข้ามาช่วยเหลือคุณเร็ว ๆ นี้\n"
                "กรุณาอธิบายปัญหาหรือคำขอของคุณด้านล่าง"
            ),
            color=discord.Color.blue(),
        )
        if support_role:
            embed.add_field(name="ทีมงานที่ดูแล", value=support_role.mention, inline=False)

        await ticket_channel.send(
            content=support_role.mention if support_role else None,
            embed=embed,
            view=TicketCloseView(),
        )
        await interaction.followup.send(f"✅ เปิดทิกเก็ตแล้วที่ {ticket_channel.mention}", ephemeral=True)


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
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ปิดทิกเก็ตนี้", ephemeral=True)
            return

        await interaction.response.send_message("🔒 กำลังปิดทิกเก็ต... ห้องนี้จะถูกลบใน 5 วินาที")
        logger.info(f"ทิกเก็ต {channel.name} ถูกปิดโดย {interaction.user}")
        await discord.utils.sleep_until(datetime.datetime.now(timezone.utc) + timedelta(seconds=5))
        try:
            await channel.delete(reason=f"ปิดทิกเก็ตโดย {interaction.user}")
        except discord.NotFound:
            pass


@bot.event
async def on_ready():
    logger.info(f"เข้าสู่ระบบในชื่อ {bot.user} (ID: {bot.user.id})")
    bot.add_view(VerifyView())  # ลงทะเบียนปุ่มถาวรใหม่ทุกครั้งที่บอทออนไลน์/รีสตาร์ท
    bot.add_view(TicketOpenView())
    bot.add_view(TicketCloseView())
    try:
        synced = await bot.tree.sync()
        logger.info(f"ซิงค์ slash command แล้ว {len(synced)} คำสั่ง")
    except Exception as e:
        logger.exception(f"เกิดข้อผิดพลาดตอนซิงค์คำสั่ง: {e}")

    # เปิดสถานะลับอัตโนมัติทุกครั้งที่บอทออนไลน์ (กันกรณีรีสตาร์ทแล้วลืมสั่งใหม่)
    if not update_status.is_running():
        update_status.start()


@bot.event
async def on_disconnect():
    logger.warning("บอทหลุดการเชื่อมต่อกับ Discord (discord.py จะพยายามเชื่อมต่อใหม่อัตโนมัติ)")


@bot.event
async def on_resumed():
    logger.info("เชื่อมต่อกับ Discord กลับมาได้แล้ว")


# =========================================================
# ระบบสถานะลับ (Secret Status) — เฉพาะเจ้าของบอทเท่านั้น
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


@tasks.loop(seconds=5)
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
            "❌ ยศที่เลือกอยู่สูงกว่าหรือเท่ากับยศของบอท กรุณาเลื่อนยศบอทให้สูงกว่ายศนี้ก่อน",
            ephemeral=True,
        )
        return

    verify_config[str(interaction.guild.id)] = role.id
    save_verify_config(verify_config)

    embed = discord.Embed(
        title="⭐ ยืนยันตัวตนผ่านปุ่มด้านล่าง",
        description="คลิกปุ่มด้านล่างเพื่อยืนยันตัวตนของคุณค่ะ",
        color=discord.Color.purple(),
    )
    embed.set_footer(text=f"Powered by {bot.user.name}")

    await interaction.response.send_message("✅ ตั้งค่าระบบยืนยันตัวตนเรียบร้อย กำลังส่งข้อความ...", ephemeral=True)
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
    await interaction.followup.send(f"🧹 ลบข้อความแล้ว {len(deleted)} ข้อความ", ephemeral=True)


@bot.tree.command(name="warn", description="เตือนสมาชิก")
@app_commands.describe(member="สมาชิกที่ต้องการเตือน", reason="เหตุผล")
@is_mod()
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "ไม่ระบุเหตุผล"):
    embed = discord.Embed(
        title="⚠️ คำเตือน",
        description=f"{member.mention} ถูกเตือนโดย {interaction.user.mention}",
        color=discord.Color.yellow(),
        timestamp=datetime.datetime.now()
    )
    embed.add_field(name="เหตุผล", value=reason)
    await interaction.response.send_message(embed=embed)
    try:
        await member.send(f"คุณถูกเตือนในเซิร์ฟเวอร์ **{interaction.guild.name}**\nเหตุผล: {reason}")
    except discord.Forbidden:
        pass


@bot.tree.command(name="kick", description="เตะสมาชิกออกจากเซิร์ฟเวอร์")
@app_commands.describe(member="สมาชิกที่ต้องการเตะ", reason="เหตุผล")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "ไม่ระบุเหตุผล"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 เตะ {member.mention} ออกแล้ว | เหตุผล: {reason}")


@bot.tree.command(name="ban", description="แบนสมาชิกออกจากเซิร์ฟเวอร์")
@app_commands.describe(member="สมาชิกที่ต้องการแบน", reason="เหตุผล")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "ไม่ระบุเหตุผล"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 แบน {member.mention} แล้ว | เหตุผล: {reason}")


@bot.tree.command(name="timeout", description="ปิดปากสมาชิกชั่วคราว (timeout)")
@app_commands.describe(member="สมาชิก", minutes="ระยะเวลา (นาที)", reason="เหตุผล")
@is_mod()
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 10080], reason: str = "ไม่ระบุเหตุผล"):
    duration = datetime.timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    await interaction.response.send_message(f"🔇 {member.mention} ถูกปิดปาก {minutes} นาที | เหตุผล: {reason}")


# =========================================================
# หมวด: จัดการยศ/บทบาท (Role Management)
# =========================================================

@bot.tree.command(name="addrole", description="เพิ่มยศให้สมาชิก")
@app_commands.describe(member="สมาชิก", role="ยศที่ต้องการเพิ่ม")
@app_commands.checks.has_permissions(manage_roles=True)
async def addrole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.add_roles(role)
    await interaction.response.send_message(f"✅ เพิ่มยศ {role.mention} ให้ {member.mention} แล้ว")


@bot.tree.command(name="removerole", description="ลบยศออกจากสมาชิก")
@app_commands.describe(member="สมาชิก", role="ยศที่ต้องการลบ")
@app_commands.checks.has_permissions(manage_roles=True)
async def removerole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    await interaction.response.send_message(f"➖ ลบยศ {role.mention} ออกจาก {member.mention} แล้ว")


@bot.tree.command(name="nick", description="เปลี่ยนชื่อเล่นของสมาชิก")
@app_commands.describe(member="สมาชิก", new_nick="ชื่อเล่นใหม่")
@app_commands.checks.has_permissions(manage_nicknames=True)
async def nick(interaction: discord.Interaction, member: discord.Member, new_nick: str):
    await member.edit(nick=new_nick)
    await interaction.response.send_message(f"✏️ เปลี่ยนชื่อเล่นของ {member.mention} เป็น **{new_nick}** แล้ว")


# =========================================================
# หมวด: ระบบรับยศด้วยรีแอค (Reaction Role Menu)
# =========================================================

@bot.tree.command(name="rolemenu_create", description="สร้างข้อความเมนูรับยศ (ยังไม่มีตัวเลือก ให้ใช้ /rolemenu_add ต่อ)")
@app_commands.describe(title="หัวข้อของเมนู", description="คำอธิบายของเมนู")
@app_commands.checks.has_permissions(manage_roles=True)
async def rolemenu_create(interaction: discord.Interaction, title: str, description: str = "รีแอคอิโมจิด้านล่างเพื่อรับ/ถอดยศ"):
    embed = discord.Embed(title=f"🎭 {title}", description=description, color=discord.Color.purple())
    embed.set_footer(text="รีแอคเพื่อรับยศ | เอารีแอคออกเพื่อถอดยศ")
    await interaction.response.send_message("✅ กำลังสร้างเมนู...", ephemeral=True)
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
            "❌ ยศที่เลือกอยู่สูงกว่าหรือเท่ากับยศของบอท กรุณาเลื่อนยศบอทให้สูงกว่ายศนี้ก่อน", ephemeral=True
        )
        return

    guild_id = str(interaction.guild.id)
    guild_conf = reactionrole_config.get(guild_id, {})
    if message_id not in guild_conf:
        await interaction.response.send_message(
            "❌ ไม่พบเมนูนี้ กรุณาสร้างด้วย /rolemenu_create ก่อน", ephemeral=True
        )
        return

    try:
        target_msg = await interaction.channel.fetch_message(int(message_id))
    except (discord.NotFound, ValueError):
        await interaction.response.send_message(
            "❌ ไม่พบข้อความนี้ในห้องนี้ กรุณาใช้คำสั่งในห้องเดียวกับที่สร้างเมนู", ephemeral=True
        )
        return

    try:
        await target_msg.add_reaction(emoji)
    except discord.HTTPException:
        await interaction.response.send_message("❌ อิโมจิไม่ถูกต้อง หรือบอทใช้อิโมจินี้ไม่ได้", ephemeral=True)
        return

    guild_conf[message_id][emoji] = role.id
    save_reactionrole_config(reactionrole_config)

    embed = target_msg.embeds[0]
    embed.add_field(name=emoji, value=role.mention, inline=True)
    await target_msg.edit(embed=embed)

    await interaction.response.send_message(f"✅ เพิ่ม {emoji} → {role.mention} เข้าเมนูแล้ว", ephemeral=True)


@bot.tree.command(name="rolemenu_remove", description="ลบตัวเลือก อิโมจิ ออกจากเมนูรับยศ")
@app_commands.describe(message_id="ID ของข้อความเมนู", emoji="อิโมจิที่จะลบออก")
@app_commands.checks.has_permissions(manage_roles=True)
async def rolemenu_remove(interaction: discord.Interaction, message_id: str, emoji: str):
    guild_id = str(interaction.guild.id)
    guild_conf = reactionrole_config.get(guild_id, {})
    mapping = guild_conf.get(message_id)

    if not mapping or emoji not in mapping:
        await interaction.response.send_message("❌ ไม่พบตัวเลือกนี้ในเมนู", ephemeral=True)
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

    await interaction.response.send_message(f"✅ ลบ {emoji} ออกจากเมนูแล้ว", ephemeral=True)


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
    member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
    if not role or not member:
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
    member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
    if not role or not member:
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

    embed = discord.Embed(
        title="🎫 ระบบทิกเก็ต",
        description="กดปุ่มด้านล่างเพื่อเปิดทิกเก็ตติดต่อทีมงาน",
        color=discord.Color.blue(),
    )
    embed.set_footer(text=f"Powered by {bot.user.name}")

    await interaction.response.send_message("✅ ตั้งค่าระบบทิกเก็ตเรียบร้อย กำลังส่งข้อความ...", ephemeral=True)
    await interaction.channel.send(embed=embed, view=TicketOpenView())


@bot.tree.command(name="closeticket", description="ปิดทิกเก็ตปัจจุบัน (ใช้ในห้องทิกเก็ตเท่านั้น)")
async def closeticket(interaction: discord.Interaction):
    channel = interaction.channel
    guild_id = str(interaction.guild.id)
    conf = ticket_config.get(guild_id, {})

    if not channel.topic or "ticket_owner_id:" not in channel.topic:
        await interaction.response.send_message("❌ ห้องนี้ไม่ใช่ห้องทิกเก็ต", ephemeral=True)
        return

    owner_id = int(channel.topic.split("ticket_owner_id:")[1].strip())
    support_role_id = conf.get("support_role_id")
    has_support_role = bool(
        support_role_id and interaction.guild.get_role(int(support_role_id)) in interaction.user.roles
    )
    can_close = owner_id == interaction.user.id or has_support_role or interaction.user.guild_permissions.manage_channels

    if not can_close:
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ปิดทิกเก็ตนี้", ephemeral=True)
        return

    await interaction.response.send_message("🔒 กำลังปิดทิกเก็ต... ห้องนี้จะถูกลบใน 5 วินาที")
    await discord.utils.sleep_until(datetime.datetime.now(timezone.utc) + timedelta(seconds=5))
    try:
        await channel.delete(reason=f"ปิดทิกเก็ตโดย {interaction.user}")
    except discord.NotFound:
        pass


# =========================================================
# หมวด: คำสั่งทั่วไป (General Commands)
# =========================================================

@bot.tree.command(name="ping", description="ตรวจสอบความหน่วงของบอท")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! ({round(bot.latency * 1000)}ms)")


@bot.tree.command(name="userinfo", description="ดูข้อมูลสมาชิก")
@app_commands.describe(member="สมาชิกที่ต้องการดูข้อมูล (ไม่ใส่ = ตัวเอง)")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed = discord.Embed(title=f"ข้อมูลของ {member.display_name}", color=discord.Color.blurple())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ชื่อผู้ใช้", value=str(member), inline=True)
    embed.add_field(name="ID", value=member.id, inline=True)
    embed.add_field(name="เข้าร่วมเซิร์ฟเวอร์เมื่อ", value=member.joined_at.strftime("%d/%m/%Y"), inline=False)
    embed.add_field(name="สร้างบัญชีเมื่อ", value=member.created_at.strftime("%d/%m/%Y"), inline=False)
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    embed.add_field(name="ยศ", value=", ".join(roles) if roles else "ไม่มี", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="serverinfo", description="ดูข้อมูลเซิร์ฟเวอร์")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=guild.name, color=discord.Color.green())
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="เจ้าของ", value=guild.owner.mention if guild.owner else "-", inline=True)
    embed.add_field(name="จำนวนสมาชิก", value=guild.member_count, inline=True)
    embed.add_field(name="สร้างเมื่อ", value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="จำนวนห้อง", value=len(guild.channels), inline=True)
    embed.add_field(name="จำนวนยศ", value=len(guild.roles), inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="poll", description="สร้างโพลแบบง่าย (โหวต 👍/👎)")
@app_commands.describe(question="คำถามของโพล")
async def poll(interaction: discord.Interaction, question: str):
    embed = discord.Embed(title="📊 โพล", description=question, color=discord.Color.orange())
    embed.set_footer(text=f"สร้างโดย {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")


@bot.tree.command(name="say", description="ให้บอทพูดข้อความแทนคุณ")
@app_commands.describe(message="ข้อความที่ต้องการให้บอทพูด")
@is_mod()
async def say(interaction: discord.Interaction, message: str):
    await interaction.response.send_message("ส่งข้อความแล้ว ✅", ephemeral=True)
    await interaction.channel.send(message)


@bot.tree.command(name="help", description="แสดงรายการคำสั่งทั้งหมด")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 คำสั่งทั้งหมดของ BOB_BOT", color=discord.Color.purple())
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
        msg = f"❌ เกิดข้อผิดพลาด: {error}"
        logger.exception(f"Unhandled app command error: {error}")

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        logger.error(
            "ไม่พบ DISCORD_TOKEN — กรุณาสร้างไฟล์ .env (ดูตัวอย่างใน .env.example) "
            "แล้วใส่ DISCORD_TOKEN=โทเคนของคุณ ก่อนรันบอท"
        )
    else:
        try:
            # discord.py มี reconnect logic ในตัวอยู่แล้วสำหรับการหลุดชั่วคราว
            bot.run(TOKEN, log_handler=None)
        except discord.LoginFailure:
            logger.error("Token ไม่ถูกต้อง กรุณาตรวจสอบค่า DISCORD_TOKEN ใน .env")
        except Exception:
            logger.exception("บอทหยุดทำงานเพราะเกิดข้อผิดพลาดที่ไม่คาดคิด")
            raise  # ให้ตัวคุมโปรเซสภายนอก (systemd/pm2) จับแล้วรีสตาร์ทให้
