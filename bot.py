import os
import time
import math
import asyncio
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message
from dotenv import load_dotenv
import humanize

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Client(
    "converter_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

os.makedirs("temp", exist_ok=True)


# ==========================
# FORMATTERS
# ==========================

def format_size(size):
    return humanize.naturalsize(size)


def progress_bar(percent):
    filled = int(percent / 10)
    return "█" * filled + "░" * (10 - filled)


async def progress(current, total, message, start, stage):
    now = time.time()
    diff = now - start

    if diff == 0:
        return

    speed = current / diff
    percent = current * 100 / total

    elapsed = time.strftime("%H:%M:%S", time.gmtime(diff))

    eta = (total - current) / speed if speed > 0 else 0
    eta = time.strftime("%H:%M:%S", time.gmtime(eta))

    text = f"""
⚡ {stage}

app.run()
