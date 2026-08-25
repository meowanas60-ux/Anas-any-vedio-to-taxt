import os
import gc
import asyncio
import sqlite3
import logging
from datetime import datetime
import yt_dlp
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# Logging Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Configuration & Secrets
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

OWNER_ID = 7701549179
CHANNEL_1 = "@sahatanas"
CHANNEL_2 = "@sahatanass"
DB_FILE = "bot_data.db"

SEMAPHORE = asyncio.Semaphore(1)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            role TEXT DEFAULT 'free',
            created_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usage (
            user_id INTEGER,
            usage_date TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, usage_date)
        )
    ''')
    conn.commit()
    conn.close()

def get_user_role(user_id):
    if user_id == OWNER_ID:
        return 'owner'
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row:
        now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('INSERT INTO users (user_id, role, created_at) VALUES (?, "free", ?)', (user_id, now_str))
        conn.commit()
        role = 'free'
    else:
        role = row[0]
    conn.close()
    return role

def check_and_increment_quota(user_id):
    role = get_user_role(user_id)
    if role == 'owner':
        return True, "Unlimited"

    limit = 5 if role == 'vip' else 1
    today = datetime.utcnow().strftime('%Y-%m-%d')

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT count FROM usage WHERE user_id = ? AND usage_date = ?', (user_id, today))
    row = cursor.fetchone()
    current_count = row[0] if row else 0

    if current_count >= limit:
        conn.close()
        return False, f"{current_count}/{limit}"

    if row:
        cursor.execute('UPDATE usage SET count = count + 1 WHERE user_id = ? AND usage_date = ?', (user_id, today))
    else:
        cursor.execute('INSERT INTO usage (user_id, usage_date, count) VALUES (?, ?, 1)', (user_id, today))
    
    conn.commit()
    conn.close()
    return True, f"{current_count + 1}/{limit}"

def set_user_role(user_id, role):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, role, created_at) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET role = ?
    ''', (user_id, role, datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), role))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, role FROM users')
    rows = cursor.fetchall()
    conn.close()
    return rows

# --- Force Join System ---
async def is_user_member(bot, user_id, channel_username):
    try:
        member = await bot.get_chat_member(chat_id=channel_username.strip(), user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception as e:
        logging.error(f"Error checking channel {channel_username}: {e}")
        return False

async def check_force_join(bot, user_id):
    if user_id == OWNER_ID:
        return True
    ch1 = await is_user_member(bot, user_id, CHANNEL_1)
    ch2 = await is_user_member(bot, user_id, CHANNEL_2)
    return ch1 and ch2

def get_force_join_keyboard():
    c1 = CHANNEL_1.replace('@', '').strip()
    c2 = CHANNEL_2.replace('@', '').strip()
    buttons = [
        [InlineKeyboardButton("📢 Join Channel 1", url=f"https://t.me/{c1}")],
        [InlineKeyboardButton("📢 Join Channel 2", url=f"https://t.me/{c2}")],
        [InlineKeyboardButton("✅ Check / Verify", callback_data="check_join")]
    ]
    return InlineKeyboardMarkup(buttons)

def get_main_keyboard():
    buttons = [
        [InlineKeyboardButton("📞 Owner Support", url=f"tg://user?id={OWNER_ID}")],
        [InlineKeyboardButton("📊 My Quota Status", callback_data="my_quota")]
    ]
    return InlineKeyboardMarkup(buttons)

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_force_join(context.bot, user_id):
        await update.message.reply_text(
            "⚠️ **বট ব্যবহার করতে ২টি চ্যানেলে জয়েন করা বাধ্যতামূলক!**\n\nনিচের বাটনে চাপ দিয়ে জয়েন করুন এবং 'Check / Verify' বাটনে চাপ দিন:",
            reply_markup=get_force_join_keyboard(),
            parse_mode="Markdown"
        )
        return

    role = get_user_role(user_id)
    await update.message.reply_text(
        f"🤖 **AI Video & Image Analysis Bot**\n\n"
        f"আপনার অ্যাকাউন্ট টাইপ: `{role.upper()}`\n\n"
        f"✨ **বটের সুবিধাসমূহ:**\n"
        f"📹 **Video Link / File:** ভিডিও বিশ্লেষণ, সামারি, ট্রানস্ক্রিপ্ট ও ট্যাগ তৈরি।\n"
        f"🖼️ **Photo:** ছবিতে কী কী আছে তার নিখুঁত বিবরণ।\n\n"
        f"📩 যেকোনো ভিডিও লিংক, ফাইল বা ছবি পাঠান!",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

async def give_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        target_id = int(context.args[0])
        set_user_role(target_id, 'vip')
        await update.message.reply_text(f"✅ User `{target_id}` কে VIP এক্সেস দেওয়া হয়েছে।", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ ব্যবহার: `/giveaccess <user_id>`", parse_mode="Markdown")

async def remove_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        target_id = int(context.args[0])
        set_user_role(target_id, 'free')
        await update.message.reply_text(f"✅ User `{target_id}` এর VIP এক্সেস বাতিল করা হয়েছে।", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ ব্যবহার: `/removeaccess <user_id>`", parse_mode="Markdown")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    users = get_all_users()
    msg = "📋 **User List:**\n\n"
    for uid, r in users:
        msg += f"• `{uid}` — {r.upper()}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "check_join":
        if await check_force_join(context.bot, user_id):
            await query.edit_message_text("✅ ধন্যবাদ! আপনার ভেরিফিকেশন সফল হয়েছে। এখন কোনো ভিডিও বা ফটো পাঠান!")
        else:
            await query.answer("❌ আপনি এখনো ২টি চ্যানেলে জয়েন করেননি!", show_alert=True)
    elif query.data == "my_quota":
        role = get_user_role(user_id)
        limit = "Unlimited" if role == 'owner' else ("5/day" if role == 'vip' else "1/day")
        await query.message.reply_text(f"📊 **আপনার তথ্য:**\nID: `{user_id}`\nRole: `{role.upper()}`\nDaily Limit: `{limit}`", parse_mode="Markdown")

# Photo Handler
async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_force_join(context.bot, user_id):
        await update.message.reply_text("⚠️ **চ্যানেলগুলোতে জয়েন করুন!**", reply_markup=get_force_join_keyboard())
        return

    allowed, quota_str = check_and_increment_quota(user_id)
    if not allowed:
        await update.message.reply_text(f"🚫 **আজকের লিমিট শেষ!** ({quota_str})\nVIP পেতে যোগাযোগ করুন: `{OWNER_ID}`", parse_mode="Markdown")
        return

    status_msg = await update.message.reply_text("🎨 **ছবিটি এনালাইস করা হচ্ছে...**")
    photo_file = await update.message.photo[-1].get_file()
    temp_path = f"downloads/photo_{user_id}.jpg"

    try:
        await photo_file.download_to_drive(temp_path)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        with open(temp_path, 'rb') as img_file:
            response = model.generate_content([
                "Analyze this image in detail and describe everything present in Bengali language clearly.", 
                {'mime_type': 'image/jpeg', 'data': img_file.read()}
            ])
            
        await status_msg.edit_text(f"🖼️ **ছবিতে যা দেখা যাচ্ছে:**\n\n{response.text}", parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Image error: {e}")
        await status_msg.edit_text("❌ ছবি এনালাইস করতে সমস্যা হয়েছে।")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        gc.collect()

# Video Processing via Gemini Multi-modal Audio
async def process_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_force_join(context.bot, user_id):
        await update.message.reply_text("⚠️ **চ্যানেলগুলোতে জয়েন করুন!**", reply_markup=get_force_join_keyboard())
        return

    allowed, quota_str = check_and_increment_quota(user_id)
    if not allowed:
        await update.message.reply_text(f"🚫 **আজকের লিমিট শেষ!** ({quota_str})\nVIP পেতে যোগাযোগ করুন: `{OWNER_ID}`", parse_mode="Markdown")
        return

    async with SEMAPHORE:
        status_msg = await update.message.reply_text("⏳ **প্রসেসিং শুরু হচ্ছে...**")
        audio_path = f"downloads/audio_{user_id}.mp3"
        video_title = "Uploaded Video"
        duration = "Unknown"
        resolution = "Unknown"
        uploaded_gemini_file = None

        try:
            if update.message.text:
                url = update.message.text.strip()
                await status_msg.edit_text("📥 **ভিডিও থেকে অডিও প্রসেস করা হচ্ছে...**")
                
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '64'}],
                    'outtmpl': f'downloads/audio_{user_id}',
                    'quiet': True,
                    'max_filesize': 50 * 1024 * 1024
                }
                
                loop = asyncio.get_running_loop()
                def fetch_video_info():
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        return info.get('title', 'Video'), str(info.get('duration', 'N/A')), f"{info.get('height', '720')}p"

                video_title, duration, resolution = await loop.run_in_executor(None, fetch_video_info)
                
            elif update.message.video:
                await status_msg.edit_text("📥 **ভিডিও ফাইল ডাউনলোড করা হচ্ছে...**")
                file = await update.message.video.get_file()
                temp_video = f"downloads/vid_{user_id}.mp4"
                await file.download_to_drive(temp_video)
                
                proc = await asyncio.create_subprocess_exec(
                    'ffmpeg', '-y', '-i', temp_video, '-vn', '-acodec', 'libmp3lame', '-b:a', '64k', audio_path
                )
                await proc.communicate()
                if os.path.exists(temp_video):
                    os.remove(temp_video)
                resolution = f"{update.message.video.height}p"
                duration = f"{update.message.video.duration}s"

            # Gemini Audio Processing
            await status_msg.edit_text("🧠 **Gemini AI দিয়ে ভিডিও বিশ্লেষণ ও রিপোর্ট তৈরি হচ্ছে...**")
            
            loop = asyncio.get_running_loop()
            uploaded_gemini_file = await loop.run_in_executor(None, lambda: genai.upload_file(path=audio_path))

            prompt = f"""
Analyze the provided audio file from a video and output in Bengali:
📌 Title: {video_title}
📝 Summary: Provide a detailed summary of what is spoken or presented.
👤 Speaker & Speech Details: Key takeaways and speaker information.
🏷️ Tags/Topics: Top 5 relevant hashtags/topics.
🌍 Language: Main language detected.
📜 Transcript Snippet: First few sentences transcribed.
"""
            model = genai.GenerativeModel('gemini-1.5-flash')
            ai_response = await loop.run_in_executor(None, lambda: model.generate_content([uploaded_gemini_file, prompt]))

            output_text = (
                f"📌 **Title:** {video_title}\n"
                f"⏱️ **Duration:** {duration} | 📺 **Resolution:** {resolution}\n\n"
                f"{ai_response.text}"
            )

            await status_msg.edit_text(output_text, parse_mode="Markdown")

        except Exception as e:
            logging.error(f"Processing error: {e}")
            await status_msg.edit_text("❌ প্রসেস করতে ত্রুটি হয়েছে! অডিও ফাইল সাইজ অনেক বড় অথবা লিংকটি ইনভ্যালিড।")
        finally:
            if uploaded_gemini_file:
                try:
                    genai.delete_file(uploaded_gemini_file.name)
                except Exception:
                    pass
            if os.path.exists(audio_path):
                os.remove(audio_path)
            gc.collect()

def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN Missing!")
        return

    os.makedirs("downloads", exist_ok=True)
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("giveaccess", give_access))
    app.add_handler(CommandHandler("removeaccess", remove_access))
    app.add_handler(CommandHandler("listusers", list_users))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, process_photo))
    app.add_handler(MessageHandler((filters.TEXT & ~filters.COMMAND) | filters.VIDEO, process_video))

    print("Gemini AI Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
