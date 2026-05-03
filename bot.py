import os
            current_job = None
            queue.task_done()


# =========================
# COMMANDS
# =========================

@app.on_message(filters.private & filters.command(["start", "help"]))
async def start_cmd(_, message: Message):
    await message.reply_text(
        "👋 **Send me a video file** and I will convert it to MP4.\n\n"
        "Supported: MKV, MP4, MOV, WEBM, AVI\n\n"
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
async def handle_media(_, message: Message):
    media = message.document or message.video
    if not media:
        return

    file_name = getattr(media, "file_name", None) or f"video_{message.id}.mkv"
    ext = Path(file_name).suffix.lower()

    if ext not in ALLOWED_EXTS:
        await message.reply_text(
            f"❌ Unsupported file type: `{ext}`\n\nSend: MKV / MP4 / MOV / WEBM / AVI"
        )
        return

    if message.chat.id in active_jobs:
        await message.reply_text("⏳ A job is already running in this chat.")
        return

    clean_name = safe_name(Path(file_name).stem)
    job_dir = DOWNLOAD_DIR / f"job_{message.chat.id}_{message.id}_{int(time.time())}"
    job_dir.mkdir(parents=True, exist_ok=True)

    input_path = job_dir / f"{clean_name}{ext}"
    output_path = job_dir / f"{clean
