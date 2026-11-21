import asyncio
import io
import json
import time
import traceback
from typing import Optional, Dict, Any, List

import aiohttp
import discord
from discord.ext import commands

API_BASE        = "https://xworms.xyz/apiv2.php"
MASTER_SECRET   = "XWORMS_SECRET_2024"
CRON_SECRET     = "CRON_CHANGE_ME_123"
BOT_TOKEN       = ""
DEFAULT_GUILD   = 0
ALLOWED_USER_IDS: List[int] = []
POLL_INTERVAL   = 3
POLL_TIMEOUT    = 1800


class APIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=90),
                connector=aiohttp.TCPConnector(ssl=False),
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        s = await self.session()
        try:
            async with s.get(self.base_url, params=params) as r:
                try:
                    data = await r.json(content_type=None)
                except Exception:
                    text = await r.text()
                    return {"status": "error", "_http": r.status, "message": text[:400]}
                if isinstance(data, dict):
                    data["_http"] = r.status
                return data
        except asyncio.TimeoutError:
            return {"status": "error", "message": "timeout"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def health(self):
        return await self.call({"action": "health"})

    async def diag(self):
        return await self.call({"action": "diag"})

    async def start_join(
        self,
        guild_id: int,
        bot_token: Optional[str] = None,
        bot_tokens: Optional[List[str]] = None,
        admin_name: str = "discord-bot",
    ):
        p: Dict[str, Any] = {
            "action": "start_join",
            "guild_id": str(guild_id),
            "admin_name": admin_name,
        }
        if bot_tokens:
            p["bot_tokens"] = ",".join(bot_tokens)
        elif bot_token:
            p["bot_token"] = bot_token
        return await self.call(p)

    async def job_status(self, job_id: str):
        return await self.call({"action": "job_status", "job_id": job_id})

    async def cancel_job(self, job_id: str):
        return await self.call({"action": "cancel_job", "job_id": job_id})

    async def list_jobs(self):
        return await self.call({"action": "list_jobs", "secret": MASTER_SECRET})

    async def validate_tokens(self):
        return await self.call({"action": "validate_tokens", "secret": MASTER_SECRET})

    async def clean_dead(self, dry: bool):
        return await self.call({
            "action": "clean_dead_tokens",
            "secret": MASTER_SECRET,
            "dry": "1" if dry else "0",
        })

    async def refresh_tokens(self, client_id: str, client_secret: str):
        return await self.call({
            "action": "refresh_tokens",
            "secret": MASTER_SECRET,
            "client_id": client_id,
            "client_secret": client_secret,
        })

    async def reset_joins(self, guild_id: int, user_id: str = ""):
        p = {"action": "reset_joins", "secret": MASTER_SECRET, "guild_id": str(guild_id)}
        if user_id:
            p["user_id"] = user_id
        return await self.call(p)

    async def get_token_info(self, user_id: str):
        return await self.call({
            "action": "get_token_info",
            "secret": MASTER_SECRET,
            "user_id": user_id,
        })

    async def get_users(self):
        return await self.call({"action": "get_users", "secret": MASTER_SECRET})

    async def get_logs(self):
        return await self.call({"action": "get_logs", "secret": MASTER_SECRET})

    async def create_key(self, days: int, max_uses: int, note: str = ""):
        return await self.call({
            "action": "create_key",
            "secret": MASTER_SECRET,
            "days": str(days),
            "max_uses": str(max_uses),
            "note": note,
        })

    async def list_keys(self):
        return await self.call({"action": "list_keys", "secret": MASTER_SECRET})

    async def revoke_key(self, target_key: str):
        return await self.call({
            "action": "revoke_key",
            "secret": MASTER_SECRET,
            "target_key": target_key,
        })

    async def delete_key(self, target_key: str):
        return await self.call({
            "action": "delete_key",
            "secret": MASTER_SECRET,
            "target_key": target_key,
        })

    async def run_worker(self, job_id: str):
        return await self.call({"action": "run_worker", "job_id": job_id})

    async def add_bot_token(self, token: str):
        return await self.call({
            "action": "add_bot_token",
            "secret": MASTER_SECRET,
            "token": token,
        })

    async def add_bot_tokens(self, tokens: List[str]):
        return await self.call({
            "action": "add_bot_tokens",
            "secret": MASTER_SECRET,
            "tokens": ",".join(tokens),
        })

    async def list_bot_tokens(self):
        return await self.call({"action": "list_bot_tokens", "secret": MASTER_SECRET})

    async def delete_bot_token(self, token: str):
        return await self.call({
            "action": "delete_bot_token",
            "secret": MASTER_SECRET,
            "token": token,
        })

    async def clear_bot_tokens(self):
        return await self.call({"action": "clear_bot_tokens", "secret": MASTER_SECRET})


API = APIClient(API_BASE)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

ACTIVE_JOBS: Dict[int, str] = {}


def _allowed(ctx) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return ctx.author.id in ALLOWED_USER_IDS


def _bar(idx, total, size=20):
    if total <= 0:
        return "░" * size
    filled = int(size * idx / total)
    return "█" * filled + "░" * (size - filled)


def _fmt_job_progress(job):
    total = int(job.get("total_files", 0))
    processed = int(job.get("processed", 0))
    success = int(job.get("success", 0))
    failed = int(job.get("failed", 0))
    skipped = int(job.get("skipped", 0))
    status = job.get("status", "?")
    duration = job.get("duration_s", 0)
    bot_count = job.get("bot_count", 0)
    pct = (processed / total * 100) if total else 0
    bar = _bar(processed, total)
    return (
        f"สถานะ: {status}\n"
        f"[{bar}] {processed}/{total} ({pct:.1f}%)\n"
        f"สำเร็จ: {success} | ล้มเหลว: {failed} | ข้าม: {skipped}\n"
        f"บอทใน pool: {bot_count}\n"
        f"เวลา: {duration}s"
    )


async def _poll_job(ctx, job_id: str, msg: discord.Message):
    started = time.time()
    last_text = ""
    data = {}

    while True:
        if time.time() - started > POLL_TIMEOUT:
            await msg.edit(content=f"หมดเวลา polling job `{job_id}`\nสถานะล่าสุด:\n{last_text}")
            ACTIVE_JOBS.pop(ctx.channel.id, None)
            return

        data = await API.job_status(job_id)
        if data.get("status") != "success":
            await asyncio.sleep(POLL_INTERVAL)
            continue

        job = data.get("job", {})
        status = job.get("status", "?")
        last_text = _fmt_job_progress(job)

        try:
            await msg.edit(content=f"Job `{job_id}`\n{last_text}")
        except Exception:
            pass

        if status in ("completed", "cancelled", "failed"):
            break

        await asyncio.sleep(POLL_INTERVAL)

    job = data.get("job", {})
    results = job.get("results", [])

    final = (
        f"เสร็จสิ้น job `{job_id}`\n"
        f"สถานะ: {job.get('status')}\n"
        f"ทั้งหมด: {job.get('total_files', 0)}\n"
        f"ประมวลผล: {job.get('processed', 0)}\n"
        f"สำเร็จ: {job.get('success', 0)}\n"
        f"ล้มเหลว: {job.get('failed', 0)}\n"
        f"ข้าม: {job.get('skipped', 0)}\n"
        f"เวลา: {job.get('duration_s', 0)}s"
    )
    try:
        await msg.edit(content=final)
    except Exception:
        await ctx.send(final)

    if results:
        try:
            payload = json.dumps(
                {"job_id": job_id, "results": results},
                indent=2, ensure_ascii=False,
            ).encode("utf-8")
            await ctx.send(file=discord.File(
                fp=io.BytesIO(payload),
                filename=f"job_{job_id}_results.json",
            ))
        except Exception:
            pass

    ACTIVE_JOBS.pop(ctx.channel.id, None)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("ใช้คำสั่งผิด — พิมพ์ !help")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply(f"argument ไม่ถูกต้อง: {error}")
    else:
        await ctx.reply(f"เกิดข้อผิดพลาด: {error}")
        traceback.print_exc()


@bot.command(name="discord")
async def cmd_discord(ctx, guild_id: int = None, *bot_tokens_extra):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    target = guild_id or DEFAULT_GUILD
    if not target:
        return await ctx.reply("ระบุ Guild ID: !discord 123456789012345678 [bot_token1 bot_token2 ...]")

    extra = [t for t in bot_tokens_extra if t]
    msg = await ctx.reply("กำลังส่ง start_join ไปที่ API...")

    if extra:
        data = await API.start_join(target, bot_tokens=extra, admin_name=str(ctx.author))
        mode_txt = f"ใช้บอทที่ระบุ ({len(extra)} ตัว)"
    else:
        data = await API.start_join(target, admin_name=str(ctx.author))
        mode_txt = "ใช้ bot pool อัตโนมัติ"

    if data.get("status") != "started":
        return await msg.edit(content=f"เริ่มงานไม่สำเร็จ:\n```json\n{json.dumps(data, ensure_ascii=False)[:1500]}\n```")

    job_id = data.get("job_id")
    if not job_id:
        return await msg.edit(content=f"API ไม่ส่ง job_id:\n{data}")

    ACTIVE_JOBS[ctx.channel.id] = job_id

    warn = ""
    if not data.get("spawned"):
        warn = "\n(worker ไม่ถูก spawn — จะรอ cron process_queue มารับ job)"

    await msg.edit(content=(
        f"เริ่ม job `{job_id}`\n"
        f"โหมด: {data.get('mode')}\n"
        f"บอท: {mode_txt} ({data.get('bot_count', 0)} ตัว)\n"
        f"ไฟล์: {data.get('total_files')}{warn}\n"
        f"กำลังติดตามสถานะ..."
    ))
    await _poll_job(ctx, job_id, msg)


@bot.command(name="join")
async def cmd_join(ctx, guild_id: int = None, *bot_tokens_extra):
    await cmd_discord(ctx, guild_id, *bot_tokens_extra)


@bot.command(name="stop")
async def cmd_stop(ctx, job_id: str = None):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    jid = job_id or ACTIVE_JOBS.get(ctx.channel.id)
    if not jid:
        return await ctx.reply("ไม่มี job ที่กำลังทำงาน — ระบุ job_id ก็ได้")
    data = await API.cancel_job(jid)
    await ctx.reply(f"ผลการยกเลิก `{jid}`:\n```json\n{json.dumps(data, ensure_ascii=False)[:800]}\n```")


@bot.command(name="job")
async def cmd_job(ctx, job_id: str):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.job_status(job_id)
    if data.get("status") != "success":
        return await ctx.reply(f"ไม่พบ job:\n```json\n{json.dumps(data, ensure_ascii=False)[:800]}\n```")
    job = data["job"]
    await ctx.reply(f"Job `{job_id}`\n{_fmt_job_progress(job)}")


@bot.command(name="jobs")
async def cmd_jobs(ctx):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.list_jobs()
    if data.get("status") != "success":
        return await ctx.reply(f"ดึงรายการไม่สำเร็จ:\n{json.dumps(data, ensure_ascii=False)[:800]}")
    jobs = data.get("jobs", [])
    if not jobs:
        return await ctx.reply("ไม่มี job")
    lines = [f"Job ทั้งหมด: {len(jobs)}"]
    for j in jobs[:20]:
        lines.append(
            f"- `{j.get('job_id')}` | {j.get('status')} | "
            f"guild={j.get('guild_id')} | ok={j.get('success')}/{j.get('total_files')} | "
            f"bots={j.get('bot_count', '?')}"
        )
    if len(jobs) > 20:
        lines.append(f"... และอีก {len(jobs) - 20}")
    await ctx.reply("\n".join(lines))


@bot.command(name="addbot")
async def cmd_addbot(ctx, token: str):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.add_bot_token(token)
    await ctx.reply(f"```json\n{json.dumps(data, ensure_ascii=False)[:800]}\n```")


@bot.command(name="addbots")
async def cmd_addbots(ctx, *tokens):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    if not tokens:
        return await ctx.reply("ระบุ token อย่างน้อย 1 ตัว: !addbots TOKEN1 TOKEN2 ...")
    data = await API.add_bot_tokens(list(tokens))
    await ctx.reply(f"```json\n{json.dumps(data, ensure_ascii=False)[:1200]}\n```")


@bot.command(name="listbots")
async def cmd_listbots(ctx):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.list_bot_tokens()
    if data.get("status") != "success":
        return await ctx.reply(f"ดึงไม่สำเร็จ:\n```json\n{json.dumps(data, ensure_ascii=False)[:800]}\n```")
    tokens = data.get("tokens", [])
    if not tokens:
        return await ctx.reply("pool ว่าง — เพิ่มด้วย !addbot หรือ !addbots")
    lines = [f"บอทใน pool: {len(tokens)} ตัว"]
    for i, t in enumerate(tokens, 1):
        lines.append(f"{i}. `{t.get('preview')}` (len={t.get('length')})")
    await ctx.reply("\n".join(lines))


@bot.command(name="delbot")
async def cmd_delbot(ctx, token: str):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.delete_bot_token(token)
    await ctx.reply(f"```json\n{json.dumps(data, ensure_ascii=False)[:800]}\n```")


@bot.command(name="clearbots")
async def cmd_clearbots(ctx):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.clear_bot_tokens()
    await ctx.reply(f"```json\n{json.dumps(data, ensure_ascii=False)[:600]}\n```")


@bot.command(name="validate")
async def cmd_validate(ctx):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    msg = await ctx.reply("กำลังตรวจสอบ token ผ่าน API...")
    data = await API.validate_tokens()
    if data.get("status") != "success":
        return await msg.edit(content=f"ตรวจสอบไม่สำเร็จ:\n```json\n{json.dumps(data, ensure_ascii=False)[:1200]}\n```")
    await msg.edit(content=(
        f"ตรวจสอบเสร็จ\n"
        f"ทั้งหมด: {data.get('total')}\n"
        f"ใช้งานได้: {data.get('valid')}\n"
        f"เสีย: {data.get('dead')}\n"
        f"ไม่มี token: {data.get('no_token')}"
    ))
    dead_list = data.get("dead_list") or []
    if dead_list:
        payload = json.dumps(dead_list, indent=2, ensure_ascii=False).encode("utf-8")
        await ctx.send(file=discord.File(fp=io.BytesIO(payload), filename="dead_tokens.json"))


@bot.command(name="clean")
async def cmd_clean(ctx, mode: str = "1"):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    dry = mode != "0"
    msg = await ctx.reply(f"กำลังสแกน token เสีย ({'ทดสอบ' if dry else 'ลบจริง'})...")
    data = await API.clean_dead(dry)
    if data.get("status") != "success":
        return await msg.edit(content=f"สแกนไม่สำเร็จ:\n```json\n{json.dumps(data, ensure_ascii=False)[:1200]}\n```")
    await msg.edit(content=(
        f"สแกนเสร็จ\n"
        f"โหมด: {'ทดสอบ' if dry else 'ลบจริง'}\n"
        f"ไฟล์ทั้งหมด: {data.get('total')}\n"
        f"เสีย: {data.get('moved')}\n"
        f"ข้าม: {data.get('skipped')}"
    ))


@bot.command(name="refresh")
async def cmd_refresh(ctx, client_id: str, client_secret: str):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    msg = await ctx.reply("กำลัง refresh token ทั้งหมด...")
    data = await API.refresh_tokens(client_id, client_secret)
    if data.get("status") != "success":
        return await msg.edit(content=f"refresh ไม่สำเร็จ:\n```json\n{json.dumps(data, ensure_ascii=False)[:1200]}\n```")
    await msg.edit(content=(
        f"refresh เสร็จ\n"
        f"ทั้งหมด: {data.get('total')}\n"
        f"refresh สำเร็จ: {data.get('refreshed')}\n"
        f"ล้มเหลว: {data.get('failed')}\n"
        f"ไม่มี refresh_token: {data.get('no_rt')}"
    ))


@bot.command(name="resetjoins")
async def cmd_resetjoins(ctx, guild_id: int, user_id: str = ""):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.reset_joins(guild_id, user_id)
    if data.get("status") != "success":
        return await ctx.reply(f"reset ไม่สำเร็จ:\n```json\n{json.dumps(data, ensure_ascii=False)[:800]}\n```")
    await ctx.reply((
        f"reset joins กิลด์ {guild_id}\n"
        f"ไฟล์ที่อัปเดต: {data.get('files_updated')}\n"
        f"entries ที่ลบ: {data.get('entries_removed')}"
    ))


@bot.command(name="info")
async def cmd_info(ctx, user_id: str):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.get_token_info(user_id)
    if data.get("status") != "success":
        return await ctx.reply(f"ไม่พบข้อมูล:\n```json\n{json.dumps(data, ensure_ascii=False)[:800]}\n```")
    await ctx.reply((
        f"User: {data.get('username')} ({data.get('user_id')})\n"
        f"Token alive: {data.get('token_alive')} (code={data.get('token_code')})\n"
        f"Joins: {data.get('joins_count')}\n"
        f"ได้ token: {data.get('obtained_at')}\n"
        f"refresh: {data.get('refreshed_at')}"
    ))


@bot.command(name="users")
async def cmd_users(ctx):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.get_users()
    if data.get("status") != "success":
        return await ctx.reply(f"ดึงไม่สำเร็จ:\n```json\n{json.dumps(data, ensure_ascii=False)[:800]}\n```")
    users = data.get("users", [])
    if not users:
        return await ctx.reply("ไม่มีผู้ใช้")
    payload = json.dumps(users, indent=2, ensure_ascii=False).encode("utf-8")
    await ctx.reply(f"ผู้ใช้ทั้งหมด: {len(users)}")
    await ctx.send(file=discord.File(fp=io.BytesIO(payload), filename="users.json"))


@bot.command(name="logs")
async def cmd_logs(ctx):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.get_logs()
    if data.get("status") != "success":
        return await ctx.reply(f"ดึงไม่สำเร็จ:\n```json\n{json.dumps(data, ensure_ascii=False)[:800]}\n```")
    logs = data.get("logs", [])
    if not logs:
        return await ctx.reply("ยังไม่มี log")
    payload = json.dumps(logs, indent=2, ensure_ascii=False).encode("utf-8")
    await ctx.reply(f"log ทั้งหมด: {len(logs)}")
    await ctx.send(file=discord.File(fp=io.BytesIO(payload), filename="logs.json"))


@bot.command(name="health")
async def cmd_health(ctx):
    data = await API.health()
    await ctx.reply(f"```json\n{json.dumps(data, indent=2, ensure_ascii=False)[:1800]}\n```")


@bot.command(name="diag")
async def cmd_diag(ctx):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.diag()
    await ctx.reply(f"```json\n{json.dumps(data, indent=2, ensure_ascii=False)[:1800]}\n```")


@bot.command(name="keys")
async def cmd_keys(ctx):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.list_keys()
    if data.get("status") != "success":
        return await ctx.reply(f"ดึงไม่สำเร็จ:\n```json\n{json.dumps(data, ensure_ascii=False)[:800]}\n```")
    keys = data.get("keys", [])
    if not keys:
        return await ctx.reply("ยังไม่มี key")
    lines = [f"Key ทั้งหมด: {len(keys)}"]
    for k in keys[:25]:
        state = "revoked" if k.get("revoked") else "active"
        lines.append(f"- `{k.get('key')}` | {state} | uses={k.get('uses',0)}/{k.get('max_uses',0)}")
    if len(keys) > 25:
        lines.append(f"... และอีก {len(keys) - 25}")
    await ctx.reply("\n".join(lines))


@bot.command(name="newkey")
async def cmd_newkey(ctx, days: int = 30, max_uses: int = 0, note: str = ""):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.create_key(days, max_uses, note)
    if data.get("status") != "success":
        return await ctx.reply(f"สร้างไม่สำเร็จ:\n```json\n{json.dumps(data, ensure_ascii=False)[:800]}\n```")
    await ctx.reply(f"สร้าง key สำเร็จ:\n`{data.get('key')}`\nวัน: {days}, uses สูงสุด: {max_uses}")


@bot.command(name="revoke")
async def cmd_revoke(ctx, target_key: str):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.revoke_key(target_key)
    await ctx.reply(f"```json\n{json.dumps(data, ensure_ascii=False)[:600]}\n```")


@bot.command(name="delkey")
async def cmd_delkey(ctx, target_key: str):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    data = await API.delete_key(target_key)
    await ctx.reply(f"```json\n{json.dumps(data, ensure_ascii=False)[:600]}\n```")


@bot.command(name="runworker")
async def cmd_runworker(ctx, job_id: str):
    if not _allowed(ctx):
        return await ctx.reply("ไม่มีสิทธิ์")
    msg = await ctx.reply(f"สั่ง run_worker `{job_id}`...")
    data = await API.run_worker(job_id)
    await msg.edit(content=f"```json\n{json.dumps(data, ensure_ascii=False)[:600]}\n```")


@bot.command(name="status")
async def cmd_status(ctx):
    await ctx.reply((
        f"บอท: {bot.user}\n"
        f"Ping: {round(bot.latency*1000)}ms\n"
        f"กิลด์: {len(bot.guilds)}\n"
        f"Active job ใน channel นี้: {ACTIVE_JOBS.get(ctx.channel.id, 'ไม่มี')}"
    ))


@bot.command(name="help")
async def cmd_help(ctx):
    await ctx.reply((
        "**=== Join / Job ===**\n"
        "`!discord <guild_id> [bot_token1 bot_token2 ...]` - เริ่ม join (ไม่ระบุ token = ใช้ pool)\n"
        "`!join <guild_id> [...]` - เหมือน !discord\n"
        "`!stop [job_id]` - ยกเลิก job\n"
        "`!job <job_id>` - ดูสถานะ job เดียว\n"
        "`!jobs` - list job ทั้งหมด\n"
        "`!runworker <job_id>` - run_worker\n"
        "\n**=== Bot Token Pool ===**\n"
        "`!addbot <token>` - เพิ่มบอท 1 ตัว\n"
        "`!addbots <t1> <t2> ...` - เพิ่มหลายตัว\n"
        "`!listbots` - ดูบอทใน pool\n"
        "`!delbot <token>` - ลบบอท\n"
        "`!clearbots` - ล้าง pool\n"
        "\n**=== Token Tools ===**\n"
        "`!validate` - validate_tokens\n"
        "`!clean [1|0]` - clean_dead_tokens (1=ทดสอบ, 0=ลบจริง)\n"
        "`!refresh <client_id> <client_secret>` - refresh_tokens\n"
        "`!resetjoins <guild_id> [user_id]` - reset_joins\n"
        "`!info <user_id>` - get_token_info\n"
        "`!users` - get_users\n"
        "`!logs` - get_logs\n"
        "\n**=== Key Management ===**\n"
        "`!keys` - list_keys\n"
        "`!newkey [days] [max_uses] [note]` - create_key\n"
        "`!revoke <key>` - revoke_key\n"
        "`!delkey <key>` - delete_key\n"
        "\n**=== System ===**\n"
        "`!health` - health\n"
        "`!diag` - diag\n"
        "`!status` - สถานะบอท"
    ))


def main():
    if not BOT_TOKEN or len(BOT_TOKEN) < 50:
        raise SystemExit("ตั้ง BOT_TOKEN ในไฟล์")
    try:
        bot.run(BOT_TOKEN, log_handler=None)
    except discord.LoginFailure:
        raise SystemExit("Bot token ไม่ถูกต้อง")
    finally:
        try:
            asyncio.run(API.close())
        except Exception:
            pass


if __name__ == "__main__":
    main()
