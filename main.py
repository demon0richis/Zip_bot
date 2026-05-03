"""
╔══════════════════════════════════════════════════════╗
║   🤖 Telegram ZIP Bot + MKV→MP4 Converter           ║
║   Railway Production Ready | Live Progress           ║
╚══════════════════════════════════════════════════════╝

Features:
  ✅ ZIP download via URL or file upload
  ✅ Auto extract → send all files
  ✅ MKV → MP4 auto conversion (ffmpeg)
  ✅ Real-time live progress box (message edit)
  ✅ Flood protection & error handling
  ✅ Env-based config (Railway compatible)
  ✅ Large file warning (50MB Telegram limit)
  ✅ /start, /convert, /help commands
  ✅ Inline keyboard mode switcher
"""

import os
import zipfile
import requests
import tempfile
import logging
import time
import asyncio
import subprocess
import shutil
from dotenv import load_dotenv

from telegram import (
    Update, Message,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.error import RetryAfter, BadRequest

# ══════════════════════════════════════════════
#  CONFIG — reads from .env or Railway Variables
# ══════════════════════════════════════════════
load_dotenv()

BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
ADMIN_ID    = int(os.environ.get("ADMIN_ID", "0"))   # Optional: your Telegram user ID
MAX_FILE_MB = int(os.environ.get("MAX_FILE_MB", "50"))
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024

# ── Logging ──────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger("ZipBot")

# ── State ─────────────────────────────────────
convert_mode_users: set[int] = set()


# ══════════════════════════════════════════════
#  FORMATTERS
# ══════════════════════════════════════════════
def fmt_size(b: int) -> str:
    if b >= 1024**3: return f"{b/1024**3:.2f} GB"
    if b >= 1024**2: return f"{b/1024**2:.2f} MB"
    if b >= 1024:    return f"{b/1024:.2f} KB"
    return f"{b} B"

def fmt_speed(bps: float) -> str:
    if bps >= 1024**2: return f"{bps/1024**2:.2f} MB/s"
    if bps >= 1024:    return f"{bps/1024:.2f} KB/s"
    return f"{bps:.0f} B/s"

def fmt_eta(sec: float) -> str:
    if sec <= 0 or sec == float("inf"): return "---"
    sec = int(sec)
    if sec >= 3600: return f"{sec//3600}h {(sec%3600)//60}m"
    if sec >= 60:   return f"{sec//60}m {sec%60}s"
    return f"{sec}s"

def trim(s: str, n: int) -> str:
    return s if len(s) <= n else "…" + s[-(n-1):]


# ══════════════════════════════════════════════
#  PROGRESS BOXES  (Telegram monospace tables)
# ══════════════════════════════════════════════
def _box(rows: list[tuple[str,str]], W1=10, W2=24) -> str:
    top = f"┏{'━'*(W1+2)}┳{'━'*(W2+2)}┓"
    sep = f"┣{'━'*(W1+2)}╋{'━'*(W2+2)}┫"
    bot = f"┗{'━'*(W1+2)}┻{'━'*(W2+2)}┛"
    lines = ["```", top]
    for i, (k, v) in enumerate(rows):
        lines.append(f"┃ {k:<{W1}} ┃ {v:<{W2}} ┃")
        if i < len(rows) - 1:
            lines.append(sep)
    lines += [bot, "```"]
    return "\n".join(lines)

def progress_box(status, percent, done, total, speed, eta,
                 file="", sent=0, total_files=0) -> str:
    rows = [
        ("Status",   status),
        ("Progress", f"{percent:.2f}%"),
        ("Size",     f"{fmt_size(done)} / {fmt_size(total)}"),
        ("Speed",    fmt_speed(speed)),
        ("ETA",      fmt_eta(eta)),
    ]
    if total_files > 0:
        rows.append(("Files", f"{sent} / {total_files}"))
    if file:
        rows.append(("File", trim(file, 24)))
    return _box(rows)

def convert_box(status, percent, cur_t, dur, speed, eta, filename="") -> str:
    bar = "█" * int(percent/5) + "░" * (20 - int(percent/5))
    rows = [
        ("Status",   status),
        ("Progress", f"{percent:.1f}%"),
        ("Bar",      bar),
        ("Time",     f"{fmt_eta(cur_t)} / {fmt_eta(dur)}"),
        ("Speed",    f"{speed:.2f}x" if speed > 0 else "---"),
        ("ETA",      fmt_eta(eta)),
    ]
    if filename:
        rows.append(("File", trim(filename, 24)))
    return _box(rows)

def done_box(sent, failed, total_size, elapsed) -> str:
    rows = [
        ("✅ Sent",    f"{sent} file(s)"),
        ("❌ Failed",  f"{failed} file(s)"),
        ("Total Size", fmt_size(total_size)),
        ("Time Taken", fmt_eta(elapsed)),
    ]
    return "🎉 *Sab kuch ho gaya!*\n" + _box(rows, W1=12, W2=20)

def convert_done_box(inp, out, size, elapsed) -> str:
    rows = [
        ("✅ Status",  "Complete!"),
        ("Input",     trim(inp, 24)),
        ("Output",    trim(out, 24)),
        ("MP4 Size",  fmt_size(size)),
        ("Time",      fmt_eta(elapsed)),
    ]
    return "🎬 *Conversion Done!*\n" + _box(rows, W1=10, W2=24)


# ══════════════════════════════════════════════
#  SAFE EDIT  (Telegram flood + "not modified" safe)
# ══════════════════════════════════════════════
async def safe_edit(msg: Message, text: str, retries: int = 3):
    for attempt in range(retries):
        try:
            await msg.edit_text(text, parse_mode="Markdown")
            return
        except RetryAfter as e:
            logger.warning(f"FloodWait {e.retry_after}s")
            await asyncio.sleep(e.retry_after + 0.5)
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return   # Same content, ignore
            logger.warning(f"BadRequest edit: {e}")
            return
        except Exception as e:
            logger.warning(f"safe_edit attempt {attempt+1} failed: {e}")
            await asyncio.sleep(1)


# ══════════════════════════════════════════════
#  STREAM DOWNLOAD  (URL → disk, live progress)
# ══════════════════════════════════════════════
async def stream_download(url: str, dest: str, status_msg: Message,
                          total_size: int = 0, update_interval: float = 2.0) -> int:
    r = requests.get(url, stream=True, timeout=180,
                     headers={"User-Agent": "TelegramZipBot/1.0"})
    r.raise_for_status()

    if not total_size:
        total_size = int(r.headers.get("content-length", 0))

    downloaded = 0
    start_time = last_update = time.time()

    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=131072):   # 128 KB chunks
            if not chunk:
                continue
            f.write(chunk)
            downloaded += len(chunk)

            now     = time.time()
            elapsed = now - start_time
            speed   = downloaded / elapsed if elapsed > 0 else 0
            eta     = (total_size - downloaded) / speed if speed > 0 else 0
            pct     = (downloaded / total_size * 100) if total_size > 0 else 0

            if now - last_update >= update_interval:
                await safe_edit(status_msg, progress_box(
                    "Downloading", pct,
                    downloaded, total_size or downloaded,
                    speed, eta,
                ))
                last_update = now

    logger.info(f"Downloaded {fmt_size(downloaded)} from {url[:60]}")
    return downloaded


# ══════════════════════════════════════════════
#  FFMPEG HELPERS
# ══════════════════════════════════════════════
def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

def get_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0

async def convert_mkv_to_mp4(mkv_path: str, mp4_path: str,
                              status_msg: Message, filename: str) -> bool:
    """
    Fast MKV→MP4: copy video stream, transcode audio to AAC.
    Uses ffmpeg -progress pipe for real-time updates.
    """
    duration   = get_duration(mkv_path)
    start_time = last_update = time.time()
    cur_t = speed = 0.0

    cmd = [
        "ffmpeg", "-y", "-i", mkv_path,
        "-c:v", "copy",            # No video re-encode (ultra fast)
        "-c:a", "aac",             # AAC audio (MP4 compatible)
        "-b:a", "192k",
        "-c:s", "mov_text",        # Subtitle copy if present
        "-movflags", "+faststart", # Streamable MP4
        "-progress", "pipe:1",
        "-nostats",
        mp4_path,
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    while True:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            break
        line = line.strip()
        if not line:
            continue

        if line.startswith("out_time_ms="):
            try:
                cur_t = int(line.split("=")[1]) / 1_000_000
            except ValueError:
                pass
        elif line.startswith("speed="):
            try:
                raw = line.split("=")[1].replace("x", "").strip()
                speed = float(raw) if raw not in ("N/A", "0") else 0.0
            except ValueError:
                pass

        now = time.time()
        if now - last_update >= 2 and duration > 0:
            pct = min((cur_t / duration) * 100, 99.9)
            eta = (duration - cur_t) / speed if speed > 0 else 0
            await safe_edit(status_msg, convert_box(
                "Converting", pct, cur_t, duration, speed, eta, filename
            ))
            last_update = now

    proc.wait()
    success = proc.returncode == 0
    logger.info(f"ffmpeg exit={proc.returncode} for {filename}")
    return success


# ══════════════════════════════════════════════
#  SEND FILE HELPER
# ══════════════════════════════════════════════
async def send_file(update: Update, filepath: str, caption: str,
                    as_video: bool = False) -> bool:
    size = os.path.getsize(filepath)
    if size > MAX_FILE_BYTES:
        await update.message.reply_text(
            f"⚠️ `{os.path.basename(filepath)}` skip kiya\n"
            f"Size {fmt_size(size)} > limit {MAX_FILE_MB}MB",
            parse_mode="Markdown",
        )
        return False
    try:
        with open(filepath, "rb") as f:
            if as_video:
                await update.message.reply_video(
                    video=f,
                    filename=os.path.basename(filepath),
                    caption=caption,
                    parse_mode="Markdown",
                    supports_streaming=True,
                )
            else:
                await update.message.reply_document(
                    document=f,
                    filename=os.path.basename(filepath),
                    caption=caption,
                    parse_mode="Markdown",
                )
        return True
    except Exception as e:
        logger.error(f"send_file failed: {filepath} — {e}")
        await update.message.reply_text(
            f"❌ Send fail: `{os.path.basename(filepath)}`\n`{e}`",
            parse_mode="Markdown",
        )
        return False


# ══════════════════════════════════════════════
#  MKV CONVERSION FLOW
# ══════════════════════════════════════════════
async def handle_mkv_conversion(update: Update, context: ContextTypes.DEFAULT_TYPE, doc):
    uid = update.effective_user.id
    convert_mode_users.discard(uid)

    filename = doc.file_name
    mp4_name = os.path.splitext(filename)[0] + ".mp4"

    status_msg = await update.message.reply_text(
        f"🎬 *MKV mila:* `{trim(filename, 30)}`\n⏳ Download suru...",
        parse_mode="Markdown",
    )

    if not ffmpeg_available():
        await safe_edit(status_msg,
            "❌ *ffmpeg nahi mila!*\n\n"
            "Railway pe `nixpacks.toml` ya `Dockerfile` use karo.\n"
            "Local pe: `sudo apt install ffmpeg`"
        )
        return

    try:
        tg_file = await context.bot.get_file(doc.file_id)

        with tempfile.TemporaryDirectory() as tmpdir:
            mkv_path = os.path.join(tmpdir, filename)
            mp4_path = os.path.join(tmpdir, mp4_name)

            # 1. Download
            await stream_download(tg_file.file_path, mkv_path,
                                  status_msg, doc.file_size or 0)

            dur = get_duration(mkv_path)
            await safe_edit(status_msg, convert_box(
                "Converting", 0, 0, dur, 0, 0, filename
            ))

            # 2. Convert
            t0 = time.time()
            ok = await convert_mkv_to_mp4(mkv_path, mp4_path, status_msg, filename)
            elapsed = time.time() - t0

            if not ok or not os.path.exists(mp4_path):
                await safe_edit(status_msg, "❌ *Conversion fail!* ffmpeg error.")
                return

            mp4_size = os.path.getsize(mp4_path)
            await safe_edit(status_msg,
                f"📤 *Uploading MP4...* `{trim(mp4_name,30)}` ({fmt_size(mp4_size)})"
            )

            # 3. Send
            ok = await send_file(update, mp4_path,
                                 f"✅ *Converted!*\n📄 `{mp4_name}`\n📦 {fmt_size(mp4_size)}",
                                 as_video=True)
            if ok:
                await safe_edit(status_msg,
                    convert_done_box(filename, mp4_name, mp4_size, elapsed)
                )

    except Exception as e:
        logger.exception(f"MKV error: {e}")
        await safe_edit(status_msg, f"❌ *Error:*\n`{str(e)[:200]}`")


# ══════════════════════════════════════════════
#  ZIP EXTRACT + SEND FLOW
# ══════════════════════════════════════════════
async def extract_and_send(update: Update, status_msg: Message,
                           zip_path: str, tmpdir: str):
    extract_dir = os.path.join(tmpdir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)

    await safe_edit(status_msg, "⚙️ *Extracting ZIP...*")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
    except zipfile.BadZipFile:
        await safe_edit(status_msg, "❌ *Invalid ZIP file!* Corrupt ya wrong format.")
        return

    all_files: list[str] = []
    for root, _, files in os.walk(extract_dir):
        for fname in sorted(files):
            all_files.append(os.path.join(root, fname))

    if not all_files:
        await safe_edit(status_msg, "⚠️ ZIP empty hai, koi file nahi mili!")
        return

    mkv_files  = [f for f in all_files if f.lower().endswith(".mkv")]
    has_ffmpeg = ffmpeg_available()

    if mkv_files and has_ffmpeg:
        await update.message.reply_text(
            f"🎬 *{len(mkv_files)} MKV file(s) mili!*\n"
            "Automatically MP4 mein convert karunga 🔄",
            parse_mode="Markdown",
        )

    total_files = len(all_files)
    total_size  = sum(os.path.getsize(f) for f in all_files)
    sent = failed = uploaded = 0
    start_time = last_update = time.time()

    for filepath in all_files:
        rel_name  = os.path.relpath(filepath, extract_dir)
        file_size = os.path.getsize(filepath)
        is_mkv    = filepath.lower().endswith(".mkv")

        # Progress update
        now = time.time()
        if now - last_update >= 1.5 or (sent + failed) == 0:
            elapsed = now - start_time
            sp  = uploaded / elapsed if elapsed > 0 else 0
            eta = (total_size - uploaded) / sp if sp > 0 else 0
            pct = (uploaded / total_size * 100) if total_size > 0 else 0
            await safe_edit(status_msg, progress_box(
                "Uploading", pct, uploaded, total_size, sp, eta,
                file=os.path.basename(filepath),
                sent=sent, total_files=total_files,
            ))
            last_update = now

        # ── MKV path ──
        if is_mkv and has_ffmpeg:
            mp4_path = os.path.splitext(filepath)[0] + ".mp4"
            conv_msg = await update.message.reply_text(
                f"🔄 *Converting:* `{trim(os.path.basename(filepath), 30)}`",
                parse_mode="Markdown",
            )
            ok = await convert_mkv_to_mp4(
                filepath, mp4_path, conv_msg, os.path.basename(filepath)
            )
            if ok and os.path.exists(mp4_path):
                mp4_size = os.path.getsize(mp4_path)
                s = await send_file(
                    update, mp4_path,
                    f"🎬 `{rel_name}` → MP4\n📦 {fmt_size(mp4_size)}",
                    as_video=True,
                )
                if s:
                    sent += 1
                    await safe_edit(conv_msg, f"✅ `{os.path.basename(mp4_path)}` bheja!")
                else:
                    failed += 1
            else:
                await safe_edit(conv_msg, "⚠️ Convert fail — original MKV bhej raha hoon...")
                s = await send_file(update, filepath, f"📄 `{rel_name}`")
                sent += 1 if s else 0
                failed += 0 if s else 1

            uploaded += file_size
            continue

        # ── Normal file path ──
        s = await send_file(update, filepath, f"📄 `{rel_name}`")
        sent   += 1 if s else 0
        failed += 0 if s else 1
        uploaded += file_size

    elapsed_total = time.time() - start_time
    await safe_edit(status_msg, done_box(sent, failed, total_size, elapsed_total))


# ══════════════════════════════════════════════
#  COMMAND HANDLERS
# ══════════════════════════════════════════════
HELP_TEXT = (
    "🤖 *ZIP Bot + MKV Converter — Help*\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━\n"
    "*📦 ZIP Mode*\n"
    "  • ZIP URL paste karo\n"
    "  • Ya ZIP file upload karo\n"
    "  • MKV inside ZIP → auto convert!\n\n"
    "*🎬 MKV→MP4 Mode*\n"
    "  • `/convert` type karo\n"
    "  • Phir MKV file upload karo\n"
    "  • Fast copy conversion (no quality loss)\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━\n"
    "*Commands:*\n"
    "  /start — Home screen\n"
    "  /convert — MKV convert mode on\n"
    "  /help — Ye message\n\n"
    f"*Limits:* Max {MAX_FILE_MB}MB per file (Telegram limit)"
)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📦 ZIP Mode",  callback_data="mode_zip"),
        InlineKeyboardButton("🎬 MKV→MP4",  callback_data="mode_convert"),
        InlineKeyboardButton("❓ Help",      callback_data="mode_help"),
    ]])
    await update.message.reply_text(
        "🤖 *ZIP Bot — Live Progress + MKV Converter*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📦 *ZIP Mode*\n"
        "  URL paste karo ya ZIP file upload karo\n"
        "  MKV files ZIP mein ho → auto convert! 🔄\n\n"
        "🎬 *MKV→MP4 Mode*\n"
        "  Seedha MKV upload karo\n"
        "  Fast convert, no quality loss ⚡\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Neeche button dabao ya seedha file bhejo! 👇",
        parse_mode="Markdown",
        reply_markup=kb,
    )

async def cmd_convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    convert_mode_users.add(update.effective_user.id)
    await update.message.reply_text(
        "🎬 *MKV→MP4 Mode ON!*\n\n"
        "Ab apni `.mkv` file upload karo ⬆️\n"
        "Main convert karke MP4 bhej dunga!\n\n"
        "_/start se wapas jao_",
        parse_mode="Markdown",
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    uid = q.from_user.id
    await q.answer()

    if q.data == "mode_zip":
        convert_mode_users.discard(uid)
        await q.edit_message_text(
            "📦 *ZIP Mode Active!*\n\n"
            "• ZIP URL paste karo\n"
            "• Ya ZIP file upload karo 📎\n\n"
            "MKV files ZIP mein ho toh auto convert hoga 🔄",
            parse_mode="Markdown",
        )
    elif q.data == "mode_convert":
        convert_mode_users.add(uid)
        await q.edit_message_text(
            "🎬 *MKV→MP4 Mode Active!*\n\n"
            "Ab apni `.mkv` file upload karo ⬆️\n"
            "Fast convert, no re-encode! ⚡\n\n"
            "_/start se wapas jao_",
            parse_mode="Markdown",
        )
    elif q.data == "mode_help":
        await q.edit_message_text(HELP_TEXT, parse_mode="Markdown")


# ══════════════════════════════════════════════
#  MESSAGE HANDLERS
# ══════════════════════════════════════════════
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc   = update.message.document
    fname = (doc.file_name or "").lower()

    # MKV → convert
    if fname.endswith(".mkv"):
        await handle_mkv_conversion(update, context, doc)
        return

    # ZIP → extract + send
    if fname.endswith(".zip"):
        status_msg = await update.message.reply_text(
            "⏳ *ZIP aa rahi hai...*", parse_mode="Markdown"
        )
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = os.path.join(tmpdir, doc.file_name or "file.zip")
                await stream_download(
                    tg_file.file_path, zip_path,
                    status_msg, doc.file_size or 0,
                )
                await extract_and_send(update, status_msg, zip_path, tmpdir)
        except Exception as e:
            logger.exception(e)
            await safe_edit(status_msg, f"❌ *Error:*\n`{str(e)[:200]}`")
        return

    await update.message.reply_text(
        "⚠️ Sirf `.zip` ya `.mkv` files accept hoti hain!\n\n"
        "📦 ZIP → extract + send all files\n"
        "🎬 MKV → MP4 convert + send",
        parse_mode="Markdown",
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # ZIP URL
    if text.startswith("http") and ".zip" in text.lower():
        status_msg = await update.message.reply_text(
            "⏳ *Download suru...*", parse_mode="Markdown"
        )
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = os.path.join(tmpdir, "download.zip")
                try:
                    head = requests.head(text, timeout=10, allow_redirects=True)
                    total = int(head.headers.get("content-length", 0))
                except Exception:
                    total = 0
                await stream_download(text, zip_path, status_msg, total)
                await extract_and_send(update, status_msg, zip_path, tmpdir)
        except Exception as e:
            logger.exception(e)
            await safe_edit(status_msg, f"❌ *Error:*\n`{str(e)[:200]}`")
        return

    await update.message.reply_text(
        "❓ Samjha nahi!\n\n"
        "• ZIP URL bhejo: `https://example.com/file.zip`\n"
        "• Ya ZIP / MKV file upload karo 📎\n"
        "• `/help` — full guide",
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════
#  STARTUP CHECK
# ══════════════════════════════════════════════
def startup_checks():
    errors = []
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN environment variable set nahi hai!")
    if errors:
        for e in errors:
            logger.critical(f"❌ {e}")
        raise SystemExit(1)

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("🤖  Telegram ZIP Bot + MKV Converter")
    logger.info(f"    ffmpeg  : {'✅ Found' if ffmpeg_available() else '❌ NOT FOUND'}")
    logger.info(f"    Max size: {MAX_FILE_MB} MB")
    logger.info(f"    Admin ID: {ADMIN_ID or 'Not set'}")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════
def main():
    startup_checks()

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)       # Handle multiple users at once
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("convert", cmd_convert))
    app.add_handler(CommandHandler("help",    cmd_help))

    # Callbacks
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Messages
    app.add_handler(MessageHandler(filters.Document.ALL,           handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("✅ Bot polling suru ho gaya!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
