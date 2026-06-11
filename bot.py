import os
import json
import datetime
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    ReplyKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ContextTypes,
    filters
)

TOKEN = os.environ.get("TOKEN") # Tokenni Render tizimidan oladi
ADMIN_ID = 5837813502
SOURCE_CHANNEL = "-1003926152488"

# Render sizga beradigan bepul URL manzil (Masalan: https://kino-bot.onrender.com)
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL") 
PORT = int(os.environ.get("PORT", 8000))

admins = {ADMIN_ID}
movies = {}      
channels = {"@mdcmovie": "MDC Movie"}  
users = set()          
daily_users = {}       

def load_data():
    global movies, channels, admins, users, daily_users
    if os.path.exists("movies.json"):
        with open("movies.json", "r", encoding="utf-8") as f:
            movies = json.load(f)
    if os.path.exists("channels.json"):
        with open("channels.json", "r", encoding="utf-8") as f:
            channels = json.load(f)
    if os.path.exists("admins.json"):
        with open("admins.json", "r", encoding="utf-8") as f:
            admins = set(json.load(f))
    else:
        admins = {ADMIN_ID}
    if os.path.exists("users.json"):
        with open("users.json", "r", encoding="utf-8") as f:
            users = set(json.load(f))
    if os.path.exists("daily_users.json"):
        with open("daily_users.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            daily_users = {k: set(v) for k, v in data.items()}

def save_data():
    with open("movies.json", "w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False, indent=4)
    with open("channels.json", "w", encoding="utf-8") as f:
        json.dump(channels, f, ensure_ascii=False, indent=4)
    with open("admins.json", "w", encoding="utf-8") as f:
        json.dump(list(admins), f, ensure_ascii=False, indent=4)
    with open("users.json", "w", encoding="utf-8") as f:
        json.dump(list(users), f, ensure_ascii=False, indent=4)
    with open("daily_users.json", "w", encoding="utf-8") as f:
        data = {k: list(v) for k, v in daily_users.items()}
        json.dump(data, f, ensure_ascii=False, indent=4)

load_data()

def is_admin(user_id):
    return user_id in admins

def is_main_admin(user_id):
    return user_id == ADMIN_ID

def track_user(user_id):
    changed = False
    if user_id not in users:
        users.add(user_id)
        changed = True
    today = datetime.date.today().strftime("%Y-%m-%d")
    if today not in daily_users:
        daily_users[today] = set()
    if user_id not in daily_users[today]:
        daily_users[today].add(user_id)
        changed = True
    if changed:
        save_data()

async def is_joined(bot, user_id):
    if not channels:
        return True
    for ch_id in channels.keys():
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            return False
    return True

async def get_subscription_keyboard(bot):
    keyboard = []
    for ch_id, ch_name in channels.items():
        try:
            chat = await bot.get_chat(ch_id)
            url = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else "https://t.me")
        except Exception:
            url = f"https://t.me/{str(ch_id).replace('@', '')}" if str(ch_id).startswith("@") else "https://t.me"
        keyboard.append([InlineKeyboardButton(f"📢 {ch_name}", url=url)])
    keyboard.append([InlineKeyboardButton("✅ Tekshirish", callback_data="check")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard(user_id):
    if is_main_admin(user_id):
        return ReplyKeyboardMarkup([
            ["➕ Kino qo'shish", "🗑️ Kino o'chirish"],
            ["📊 Statistika", "📋 Kodlar ro'yxati"],
            ["⚙️ Kanallarni boshqarish", "👑 Adminlarni boshqarish"],
            ["📣 Hammaga xabar yuborish"]
        ], resize_keyboard=True)
    else:
        return ReplyKeyboardMarkup([
            ["➕ Kino qo'shish", "🗑️ Kino o'chirish"],
            ["📊 Statistika", "📋 Kodlar ro'yxati"],
            ["⚙️ Kanallarni boshqarish"]
        ], resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)

async def go_to_main_panel(update, user_id):
    await update.message.reply_text(
        f"🏠 Bosh panel",
        reply_markup=get_admin_keyboard(user_id)
    )

async def send_welcome(update):
    start_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔍 Kinolarni qidirish", switch_inline_query_current_chat="")
    ]])
    welcome_text = (
        "👋 Assalomu alaykum, botimizga xush kelibsiz\n\n"
        "🎥 Bot orqali siz sevimli filmlar, seriallar va multfilmlarni sifatli formatda ko'rishingiz mumkin\n\n"
        "🚀 Shunchaki\n"
        "— Kino yoki serialning kodini yuboring\n"
        "— Pastdagi qidiruv bo'limidan foydalaning"
    )
    await update.message.reply_text(welcome_text, reply_markup=start_kb)

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    user_id = update.inline_query.from_user.id
    bot_obj = context.bot

    if not await is_joined(bot_obj, user_id):
        await update.inline_query.answer(
            [],
            switch_pm_text="📢 Avval kanallarga obuna bo'ling",
            switch_pm_parameter="start",
            cache_time=2
        )
        return

    if not query:
        return

    results = []
    for movie_code, data in movies.items():
        if isinstance(data, dict):
            name_in_db = data.get("name", f"Kino {movie_code}")
        else:
            name_in_db = f"Kino {movie_code}"

        if query in name_in_db.lower() or query == str(movie_code):
            results.append(
                InlineQueryResultArticle(
                    id=str(movie_code),
                    title=f"🎬 {name_in_db.upper()}",
                    description=f"📥 Bosing — kino yuboriladi | Kod: {movie_code}",
                    input_message_content=InputTextMessageContent(
                        message_text=str(movie_code)
                    )
                )
            )

    await update.inline_query.answer(results[:15], cache_time=2)

async def send_movie_by_code(chat_id, movie_code, bot, context):
    if movie_code in movies:
        db_data = movies[movie_code]
        pids = [db_data["video_id"]] if isinstance(db_data, dict) else db_data
        kino_inline_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔍 Qidirish", switch_inline_query_current_chat="")
        ]])
        for pid in pids:
            try:
                await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=SOURCE_CHANNEL,
                    message_id=int(pid),
                    reply_markup=kino_inline_kb
                )
            except Exception:
                await bot.send_message(chat_id=chat_id, text="❌ Film o'chirilgan yoki bot kanalda admin emas.")
        return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    track_user(user_id)
    args = context.args

    if args:
        start_param = args[0]
        if start_param.startswith("kino_"):
            movie_code = start_param.split("_")[1]
            if await is_joined(context.bot, user_id):
                await send_movie_by_code(update.effective_chat.id, movie_code, context.bot, context)
            else:
                reply_markup = await get_subscription_keyboard(context.bot)
                await update.message.reply_text("❗ Kinoni olish uchun kanallarga qo'shiling!", reply_markup=reply_markup)
            return

    if is_admin(user_id):
        context.user_data["admin_state"] = None
        context.user_data.pop("new_movie", None)
        role = "Asosiy Admin" if is_main_admin(user_id) else "Yordamchi Admin"
        await update.message.reply_text(f"👑 Salom {role}! Boshqaruv paneli:", reply_markup=get_admin_keyboard(user_id))
        return

    if not await is_joined(context.bot, user_id):
        reply_markup = await get_subscription_keyboard(context.bot)
        await update.message.reply_text("❗ Botdan foydalanish uchun kanallarga qo'shiling!", reply_markup=reply_markup)
        return

    await send_welcome(update)

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    track_user(user_id)
    text = update.message.text.strip()
    state = context.user_data.get("admin_state")

    if is_admin(user_id) and text == "❌ Bekor qilish":
        context.user_data["admin_state"] = None
        context.user_data.pop("new_movie", None)
        await go_to_main_panel(update, user_id)
        return

    if is_admin(user_id) and state:
        if state == "add_movie_name":
            context.user_data["new_movie"] = {"name": text}
            context.user_data["admin_state"] = "add_movie_desc"
            await update.message.reply_text("📝 2-Qadam: Kino ma'lumotlarini kiriting:", reply_markup=get_cancel_keyboard())
            return
        elif state == "add_movie_desc":
            context.user_data["new_movie"]["desc"] = text
            context.user_data["admin_state"] = "add_movie_code"
            await update.message.reply_text("🔑 3-Qadam: Kinoga beriladigan kodni kiriting:", reply_markup=get_cancel_keyboard())
            return
        elif state == "add_movie_code":
            context.user_data["new_movie"]["code"] = text
            context.user_data["admin_state"] = "add_movie_vid"
            await update.message.reply_text("📥 4-Qadam: Kanaldagi Post ID raqamini yuboring:", reply_markup=get_cancel_keyboard())
            return
        elif state == "add_movie_vid":
            if not text.isdigit():
                await update.message.reply_text("❌ Post ID faqat raqam bo'ladi. Qaytadan kiriting:", reply_markup=get_cancel_keyboard())
                return
            movie_data = context.user_data["new_movie"]
            movie_data["video_id"] = text
            preview = f"🎬 Nomi: {movie_data['name'].upper()}\n📝 Ma'lumot: {movie_data['desc']}\n🔑 Kod: {movie_data['code']}\n📥 Video ID: {movie_data['video_id']}\n\nTasdiqlaysizmi?"
            confirm_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Tasdiqlash", callback_data="confirm_save_movie"), InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")]])
            await update.message.reply_text(preview, reply_markup=confirm_kb)
            return
        elif state == "waiting_channel_add":
            parts = text.split(" ", 1)
            if len(parts) < 2:
                await update.message.reply_text("❌ Format xato!\n@kanal_username Kanal Nomi", reply_markup=get_cancel_keyboard())
                return
            channels[parts[0]] = parts[1]
            save_data()
            context.user_data["admin_state"] = None
            await update.message.reply_text(f"✅ Kanal qo'shildi: {parts[1]}")
            await go_to_main_panel(update, user_id)
            return

    if is_admin(user_id):
        if text == "➕ Kino qo'shish":
            context.user_data["admin_state"] = "add_movie_name"
            await update.message.reply_text("🎬 1-Qadam: Kino nomini kiriting:", reply_markup=get_cancel_keyboard())
            return
        elif text == "🗑️ Kino o'chirish":
            if not movies:
                await update.message.reply_text("❌ Bazada kino yo'q.")
                return
            keyboard = []
            for kod, m_data in movies.items():
                name = m_data.get("name", f"Kino {kod}").upper() if isinstance(m_data, dict) else f"Kino {kod}"
                keyboard.append([InlineKeyboardButton(f"🎬 {name} ({kod})", callback_data=f"del_movie_{kod}")])
            keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")])
            await update.message.reply_text("👇 Tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        elif text == "📊 Statistika":
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            today_count = len(daily_users.get(today_str, set()))
            await update.message.reply_text(f"📊 Statistika:\n\n👥 Jami: {len(users)}\n📅 Bugun: {today_count}\n🎬 Kinolar: {len(movies)}")
            return
        elif text == "📋 Kodlar ro'yxati":
            if not movies:
                await update.message.reply_text("Ro'yxat bo'sh.")
                return
            text_codes = "📋 Kodlar:\n\n"
            for kod, data in movies.items():
                name = data.get("name", "Nomsiz").upper() if isinstance(data, dict) else "Kino"
                text_codes += f"🔑 {kod} → {name}\n"
            await update.message.reply_text(text_codes)
            return

    if not await is_joined(context.bot, user_id):
        reply_markup = await get_subscription_keyboard(context.bot)
        await update.message.reply_text("❗ Avval kanallarga obuna bo'ling!", reply_markup=reply_markup)
        return

    if await send_movie_by_code(update.effective_chat.id, text, context.bot, context):
        return
    else:
        await update.message.reply_text("❌ Bunday kodli kino topilmadi.")

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "cancel_to_main":
        context.user_data["admin_state"] = None
        context.user_data.pop("new_movie", None)
        await query.answer()
        await query.message.delete()
        if is_admin(user_id):
            await context.bot.send_message(chat_id=query.message.chat_id, text="🏠 Bosh panel", reply_markup=get_admin_keyboard(user_id))
        return

    if data == "check":
        if await is_joined(context.bot, user_id):
            await query.answer("✅ Tasdiqlandi!")
            await send_welcome(query)
        else:
            await query.answer("❌ Hali obuna bo'linmagan!", show_alert=True)
        return

# WEBHOOK REJIMIDA ISHGA TUSHIRISH
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(InlineQueryHandler(inline_query_handler))
app.add_handler(CallbackQueryHandler(handle_callbacks))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

if RENDER_EXTERNAL_URL:
    # Render-da webhook orqali doimiy 24/7 ishga tushirish
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        secret_token="BotSecretToken123",
        webhook_url=f"{RENDER_EXTERNAL_URL}/webhook"
    )
else:
    # Agar kompyuterda ishga tushirsangiz oddiy reja
    print("Lokal rejimda ishga tushdi...")
    app.run_polling()
