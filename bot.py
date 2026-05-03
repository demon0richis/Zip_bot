import os
import re
import shlex
import time
import shutil
import asyncio
import logging
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List

from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from pyrogram.types import Message
import humanize

# =========================
# CONFIG
# =========================

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID / API_HASH / BOT_TOKEN in .env")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"

ALLOWED_EXTS = {".mkv", ".mp4", ".mov", ".webm", ".avi"}
MAX_CONCURRENT_JOBS = 1

app = Client(
    "railway_converter_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=str(Path.cwd())
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("converter")


# =========================
# JOB MODEL
# =========================

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
    stage: str = "Queued"
    cancelled: bool = False


queue: asyncio.Queue[Job] = asyncio.Queue()
active_jobs: Dict[int, Job] = {}
current_job: Optional[Job] = None
job_lock = asyncio.Lock()
    output_path = job_dir / f"{clean
