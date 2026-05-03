import os
import re
import time
import shutil
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict

from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from pyrogram.types import Message
import humanize

# =======================
# CONFIG
# =======================

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN in .env")

BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "work"
WORK_DIR.mkdir(exist_ok=True)

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

ALLOWED_EXTS = {".mkv", ".mp4", ".mov", ".webm", ".avi", ".flv", ".m4v"}
MAX_QUEUE_PER_CHAT = 1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("converter")

app = Client(
    "railway_converter_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# =======================
# MODELS
# =======================

@dataclass
class Job:
    chat_id: int
    user_id: int
    message_id: int
    file_name: str
    input_path: Path
    output_path: Path
    status_msg: Optional[Message] = None
    started_at: float = field(default_factory=time.time)
    cancelled: bool = False
    stage: str = "queued"

queue: asyncio.Queue[Job] = asyncio.Queue()
active_jobs: Dict[int, Job] = {}
current_job: Optional[Job] = None

# =======================
# HELPERS
# =======================

def clean_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or f"file_{int(time.time())}"

def human_size(num: float) -> str:
    try:
        return humanize.naturalsize(num, binary=True)
    except Exception:
        return f"{num:.2f} B"

def fmt_time(seconds: float) -> str:
    if not seconds or seconds <= 0 or seconds == float("inf"):
        return "--:--:--"
    return time.strftime("%H:%M:%S", time.gmtime(seconds))

def progress_bar(percent: float, blocks: int = 12) -> str:
    percent = max(0, min(100, percent))
    filled = int((percent / 100) * blocks)
    return "█" * filled + "░" * (blocks - filled)

def pct(current: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, (current * 100.0) / total))

async def safe_edit(msg: Message, text: str):
    try:
        await msg.edit_text(text)
    except Exception:
        pass

def status_text(stage: str, current: float, total: float, speed: float, elapsed: float) -> str:
    percent = pct(current, total)
    eta = (total - current) / speed if speed > 0 else 0
    return (
        f"⚡ **{stage}**\n\n"
        f"[`{progress_bar(percent)}`] **{percent:.2f}%**\n\n"
        f"📦 **Done:** `{human_size(current)}` / `{human_size(total)}`\n"
        f"🚀 **Speed:** `{human_size(speed)}/s` \n"
        f"⏳ **ETA:** `{fmt_time(eta)}`\n"
        f"⌛ **Elapsed:** `{fmt_time(elapsed)}`"
    )

async def telegram_progress(current: int, total: int, msg: Message, started: float, stage: str):
    elapsed = max(time.time() - started, 0.001)
    speed = current / elapsed
    await safe_edit(msg, status_text(stage, current, total, speed, elapsed))

async def ffprobe_duration(path: Path) -> float:
    proc = await asyncio.create_subprocess_exec(
        FFPROBE,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except Exception:
        return 0.0

async def run_ffmpeg_convert(job: Job):
    duration = await ffprobe_duration(job.input_path)
    if duration <= 0:
        duration = 1.0

    job.stage = "converting"
    await safe_edit(job.status_msg, "🔄 **Converting...**\n\nPlease wait")

    cmd = [
        FFMPEG, "-hide_banner", "-y",
        "-i", str(job.input_path),
        "-map", "0",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-c:s", "copy",
        "-progress", "pipe:1",
        "-nostats",
        str(job.output_path)
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    started = time.time()
    last_update = 0.0
    out_time_ms = 0.0

    while True:
        if job.cancelled:
            proc.kill()
            raise asyncio.CancelledError("Cancelled by user")

        line = await proc.stdout.readline()
        if not line:
            if proc.returncode is not None:
                break
            if proc.stdout.at_eof():
                break
            await asyncio.sleep(0.2)
            continue

        s = line.decode("utf-8", errors="ignore").strip()

        if s.startswith("out_time_ms="):
            try:
                out_time_ms = float(s.split("=", 1)[1])
            except Exception:
                pass

        if s == "progress=continue" and (time.time() - last_update) >= 2.0:
            last_update = time.time()
            current_sec = min(out_time_ms / 1_000_000.0, duration)
            speed = current_sec / max(time.time() - started, 0.001)
            eta = (duration - current_sec) / speed if speed > 0 else 0
            percent = pct(current_sec, duration)

            text = (
                f"🔄 **Converting MKV → MP4**\n\n"
                f"[`{progress_bar(percent)}`] **{percent:.2f}%**\n\n"
                f"🎞 **Processed:** `{fmt_time(current_sec)}` / `{fmt_time(duration)}`\n"
                f"🚀 **Speed:** `{speed:.2f}x`\n"
                f"⏳ **ETA:** `{fmt_time(eta)}`\n"
                f"⌛ **Elapsed:** `{fmt_time(time.time() - started)}`"
            )
            await safe_edit(job.status_msg, text)

    rc = await proc.wait()
    if rc != 0:
        err = ""
        try:
            err = (await proc.stderr.read()).decode("utf-8", errors="ignore")
        except Exception:
            pass
        raise RuntimeError(f"FFmpeg failed. {err[:700]}")

async def process_job(job: Job):
    try:
        job.stage = "downloading"
        await safe_edit(job.status_msg, "⬇️ **Downloading...**\n\nStarting download")

        await app.download_media(
            message=job.message_id,
            file_name=str(job.input_path),
            progress=telegram_progress,
            progress_args=(job.status_msg, job.started_at, "Downloading")
        )

        if job.cancelled:
            raise asyncio.CancelledError("Cancelled after download")

        await run_ffmpeg_convert(job)

        if job.cancelled:
            raise asyncio.CancelledError("Cancelled before upload")

        job.stage = "uploading"
        upload_start = time.time()
        await safe_edit(job.status_msg, "⬆️ **Uploading...**\n\nStarting upload")

        await app.send_document(
            chat_id=job.chat_id,
            document=str(job.output_path),
            caption=(
                f"✅ **Converted Successfully**\n"
                f"📄 `{job.output_path.name}`\n"
                f"🎬 MKV → MP4"
            ),
            progress=telegram_progress,
            progress_args=(job.status_msg, upload_start, "Uploading")
        )

        await safe_edit(job.status_msg, "✅ **Done**")

    except asyncio.CancelledError:
        await safe_edit(job.status_msg, "🛑 **Cancelled**")
    except Exception as e:
        log.exception("Job failed")
        await safe_edit(job.status_msg, f"❌ **Error:** `{str(e)[:900]}`")
    finally:
        active_jobs.pop(job.chat_id, None)
        try:
            if job.input_path.exists():
                job.input_path.unlink()
        except Exception:
            pass
        try:
            if job.output_path.exists():
                job.output_path.unlink()
        except Exception:
            pass
        try:
            if job.input_path.parent.exists():
                shutil.rmtree(job.input_path.parent, ignore_errors=True)
        except Exception:
            pass

async def worker():
    global current_job
    while True:
        job = await queue.get()
        current_job = job
        try:
            await process_job(job)
        finally:
            current_job = None
            queue.task_done()

# =======================
# COMMANDS
# =======================

@app.on_message(filters.private & filters.command(["start", "help"]))
async def start_cmd(_, message: Message):
    await message.reply_text(
        "👋 **Send me a video file** and I will convert it to MP4.\n\n"
        "Supported: MKV, MP4, MOV, WEBM, AVI, FLV, M4V\n\n"
        "Commands:\n"
        "/start - start bot\n"
        "/help - help\n"
        "/cancel - cancel current job"
    )

@app.on_message(filters.private & filters.command("cancel"))
async def cancel_cmd(_, message: Message):
    job = active_jobs.get(message.chat.id)
    if not job:
        await message.reply_text("No active job in this chat.")
        return
    job.cancelled = True
    await message.reply_text("Stopping current job...")

@app.on_message(filters.private & (filters.document | filters.video))
async def media_handler(_, message: Message):
    media = message.document or message.video
    if not media:
        return

    file_name = getattr(media, "file_name", None) or f"video_{message.id}.mkv"
    ext = Path(file_name).suffix.lower()

    if ext not in ALLOWED_EXTS:
        await message.reply_text(
            f"❌ Unsupported file type: `{ext}`\n\n"
            f"Send: MKV / MP4 / MOV / WEBM / AVI / FLV / M4V"
        )
        return

    if message.chat.id in active_jobs:
        await message.reply_text("⏳ A job is already running in this chat.")
        return

    clean = clean_name(Path(file_name).stem)
    job_dir = WORK_DIR / f"job_{message.chat.id}_{message.id}_{int(time.time())}"
    job_dir.mkdir(parents=True, exist_ok=True)

    input_path = job_dir / f"{clean}{ext}"
    output_path = job_dir / f"{clean}.mp4"

    status = await message.reply_text("🟦 **Queued...**")

    job = Job(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        message_id=message.id,
        file_name=file_name,
        input_path=input_path,
        output_path=output_path,
        status_msg=status
    )

    active_jobs[message.chat.id] = job
    await queue.put(job)
    await safe_edit(status, "🟨 **Added to queue**\n\nYour file will be processed soon.")

@app.on_message(filters.private & filters.command("status"))
async def status_cmd(_, message: Message):
    if current_job and current_job.chat_id == message.chat.id:
        await message.reply_text(
            f"**Active Job**\n\n"
            f"Stage: `{current_job.stage}`\n"
            f"File: `{current_job.file_name}`\n"
            f"Queue size: `{queue.qsize()}`"
        )
    else:
        await message.reply_text(f"No active job.\nQueue size: `{queue.qsize()}`")

# =======================
# MAIN
# =======================

async def main():
    await app.start()
    asyncio.create_task(worker())
    log.info("Bot started")
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
