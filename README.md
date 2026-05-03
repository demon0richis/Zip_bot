# 🤖 Telegram ZIP Bot + MKV→MP4 Converter

Real-time progress, live message editing, Railway hosted.

---

## 🚀 Railway pe Deploy kaise karo

### Step 1 — GitHub pe push karo

```bash
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/TERA_USERNAME/zipbot.git
git push -u origin main
```

### Step 2 — Railway pe project banao

1. [railway.app](https://railway.app) pe jao → **New Project**
2. **Deploy from GitHub repo** select karo
3. Apna `zipbot` repo select karo
4. Railway auto Dockerfile detect karega ✅

### Step 3 — Environment Variables daalo

Railway Dashboard → **Variables** tab → Add karo:

| Variable     | Value                    | Required |
|--------------|--------------------------|----------|
| `BOT_TOKEN`  | `1234567890:AAF...`      | ✅ Yes   |
| `ADMIN_ID`   | `987654321`              | No       |
| `MAX_FILE_MB`| `50`                     | No       |
| `LOG_LEVEL`  | `INFO`                   | No       |

### Step 4 — Deploy!

Variables save karo → Railway auto deploy karega 🎉

---

## 💻 Local pe chalana hai?

```bash
# Clone karo
git clone https://github.com/TERA_USERNAME/zipbot.git
cd zipbot

# .env banao
cp .env.example .env
# .env file mein BOT_TOKEN daalo

# ffmpeg install karo
sudo apt install ffmpeg       # Linux
brew install ffmpeg           # Mac
# Windows: https://ffmpeg.org/download.html

# Dependencies install karo
pip install -r requirements.txt

# Run!
python main.py
```

---

## 📋 Bot Commands

| Command    | Kaam                          |
|------------|-------------------------------|
| `/start`   | Home screen + mode buttons    |
| `/convert` | MKV→MP4 mode on               |
| `/help`    | Full help message             |

---

## ✅ Features

- 📦 ZIP URL ya file upload → extract → sab files bhejta hai
- 🎬 MKV → MP4 auto conversion (ffmpeg, no quality loss)
- 📊 Live progress box (har 2 sec message edit hota hai)
- 🔄 Concurrent users support
- 🛡️ Flood protection + error handling
- ⚡ Fast: video stream copy (no re-encode)

---

## ⚠️ Limits

- Telegram Bot API max file size: **50 MB**
- Isse badi files skip ho jayengi warning ke saath
- Railway free tier mein disk space limited hai — badi ZIP files ke liye paid plan lo
