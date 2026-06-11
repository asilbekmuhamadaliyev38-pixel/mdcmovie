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

# Render sizga beradigan bepul URL manzil
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

    results = []
    
    # Kinolarni eng oxirgi qo'shilganidan boshlab teskari tartibda saralash
    sorted_movies = list(movies.items())[::-1]

    for movie_code, data in sorted_movies:
        if isinstance(data, dict):
            name_in_db = data.get("name", f"Kino {movie_code}")
            desc_in_db = data.get("desc", "Sifatli formatda yuklab olish")
            poster_url = data.get("poster", None)
        else:
            name_in_db = f"Kino {movie_code}"
            desc_in_db = "Kino kodi orqali yuklash"
            poster_url = None

        # Agar qidiruv bo'sh bo'lsa hamma kinoni chiqaradi, yozilgan bo'lsa mos kelganini filter qiladi
        if not query or (query in name_in_db.lower() or query == str(movie_code)):
            results.append(
                InlineQueryResultArticle(
                    id=str(movie_code),
                    title=f"🎬 {name_in_db.upper()}",
                    description=f"{desc_in_db} | Kod: {movie_code}",
                    thumbnail_url=poster_url, # Rasmdagidek poster chiqishi uchun
                    input_message_content=InputTextMessageContent(
                        message_text=str(movie_code)
                    )
                )
            )

    await update.inline_query.answer(results[:25], cache_time=2)

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
            await update.message.reply_text("📝 2-Qadam: Kino ma'lumotlarini kiriting (sifati, tili...):", reply_markup=get_cancel_keyboard())
            return

        elif state == "add_movie_desc":
            context.user_data["new_movie"]["desc"] = text
            context.user_data["admin_state"] = "add_movie_code"
            await update.message.reply_text("🔑 3-Qadam: Kinoga beriladigan kodni kiriting:", reply_markup=get_cancel_keyboard())
            return

        elif state == "add_movie_code":
            context.user_data["new_movie"]["code"] = text
            context.user_data["admin_state"] = "add_movie_poster"
            await update.message.reply_text("🖼️ 4-Qadam: Kino posteri (rasm) havolasini (linkini) yuboring:", reply_markup=get_cancel_keyboard())
            return

        elif state == "add_movie_poster":
            context.user_data["new_movie"]["poster"] = text
            context.user_data["admin_state"] = "add_movie_vid"
            await update.message.reply_text("📥 5-Qadam: Kanaldagi Post ID raqamini yuboring:", reply_markup=get_cancel_keyboard())
            return

        elif state == "add_movie_vid":
            if not text.isdigit():
                await update.message.reply_text("❌ Post ID faqat raqam bo'ladi. Qaytadan kiriting:", reply_markup=get_cancel_keyboard())
                return
            movie_data = context.user_data["new_movie"]
            movie_data["video_id"] = text
            preview = (
                f"🎬 Nomi: {movie_data['name'].upper()}\n"
                f"📝 Ma'lumot: {movie_data['desc']}\n"
                f"🔑 Kod: {movie_data['code']}\n"
                f"🖼️ Poster: {movie_data['poster']}\n"
                f"📥 Video ID: {movie_data['video_id']}\n\n"
                f"Tasdiqlaysizmi?"
            )
            confirm_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Tasdiqlash", callback_data="confirm_save_movie"),
                 InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")]
            ])
            await update.message.reply_text(preview, reply_markup=confirm_kb)
            return

        elif state == "waiting_channel_add":
            parts = text.split(" ", 1)
            if len(parts) < 2:
                await update.message.reply_text("❌ Format xato!\nTo'g'ri format: @kanal_username Kanal Nomi", reply_markup=get_cancel_keyboard())
                return
            channels[parts[0]] = parts[1]
            save_data()
            context.user_data["admin_state"] = None
            await update.message.reply_text(f"✅ Kanal qo'shildi: {parts[1]}")
            await go_to_main_panel(update, user_id)
            return

        elif state == "waiting_channel_remove":
            if text in channels:
                del channels[text]
                save_data()
                context.user_data["admin_state"] = None
                await update.message.reply_text("✅ Kanal o'chirildi.")
                await go_to_main_panel(update, user_id)
            else:
                await update.message.reply_text("❌ Bunday kanal topilmadi. Qaytadan kiriting:", reply_markup=get_cancel_keyboard())
            return

        elif state == "waiting_admin_add" and is_main_admin(user_id):
            if not text.isdigit():
                await update.message.reply_text("❌ Faqat Telegram ID raqamini kiriting:", reply_markup=get_cancel_keyboard())
                return
            new_id = int(text)
            if new_id == ADMIN_ID:
                await update.message.reply_text("❌ Bu allaqachon asosiy admin!", reply_markup=get_cancel_keyboard())
                return
            admins.add(new_id)
            save_data()
            context.user_data["admin_state"] = None
            await update.message.reply_text(f"✅ Yangi admin qo'shildi!\nID: {new_id}")
            await go_to_main_panel(update, user_id)
            return

        elif state == "waiting_admin_remove" and is_main_admin(user_id):
            if not text.isdigit():
                await update.message.reply_text("❌ Faqat Telegram ID raqamini kiriting:", reply_markup=get_cancel_keyboard())
                return
            remove_id = int(text)
            if remove_id == ADMIN_ID:
                await update.message.reply_text("❌ Asosiy adminni o'chirib bo'lmaydi!", reply_markup=get_cancel_keyboard())
                return
            if remove_id in admins:
                admins.remove(remove_id)
                save_data()
                context.user_data["admin_state"] = None
                await update.message.reply_text(f"✅ Admin o'chirildi!\nID: {remove_id}")
                await go_to_main_panel(update, user_id)
            else:
                await update.message.reply_text("❌ Bunday admin topilmadi. Qaytadan kiriting:", reply_markup=get_cancel_keyboard())
            return

        elif state == "broadcast_wait" and is_main_admin(user_id):
            context.user_data["broadcast_text"] = text
            context.user_data["admin_state"] = None
            confirm_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Yuborish", callback_data="broadcast_confirm"),
                 InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")]
            ])
            await update.message.reply_text(
                f"📣 Xabar ko'rinishi:\n\n{text}\n\n"
                f"👥 {len(users)} ta foydalanuvchiga yuboriladi.\n"
                f"Tasdiqlaysizmi?",
                reply_markup=confirm_kb
            )
            return

    if is_admin(user_id):
        if text == "➕ Kino qo'shish":
            context.user_data["admin_state"] = "add_movie_name"
            await update.message.reply_text("🎬 1-Qadam: Kino nomini kiriting:", reply_markup=get_cancel_keyboard())
            return

        elif text == "🗑️ Kino o'chirish":
            if not movies:
                await update.message.reply_text("❌ Bazada hech qanday kino yo'q.")
                return
            keyboard = []
            for kod, m_data in movies.items():
                name = m_data.get("name", f"Kino {kod}").upper() if isinstance(m_data, dict) else f"Kino {kod}"
                keyboard.append([InlineKeyboardButton(f"🎬 {name} (Kod: {kod})", callback_data=f"del_movie_{kod}")])
            keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")])
            await update.message.reply_text("👇 O'chirmoqchi bo'lgan kinoni tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        elif text == "📊 Statistika":
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            today_count = len(daily_users.get(today_str, set()))
            await update.message.reply_text(
                f"📊 Statistika:\n\n"
                f"👥 Jami foydalanuvchi: {len(users)}\n"
                f"📅 Bugun: {today_count}\n"
                f"🎬 Kinolar soni: {len(movies)}"
            )
            return

        elif text == "📋 Kodlar ro'yxati":
            if not movies:
                await update.message.reply_text("Ro'yxat bo'sh.")
                return
            text_codes = "📋 Kodlar ro'yxati:\n\n"
            for kod, data in movies.items():
                name = data.get("name", "Nomsiz").upper() if isinstance(data, dict) else "Kino"
                text_codes += f"🔑 {kod} → {name}\n"
            await update.message.reply_text(text_codes)
            return

        elif text == "⚙️ Kanallarni boshqarish":
            text_ch = "📢 Kanal ro'yxati:\n\n"
            for ch_id, ch_name in channels.items():
                text_ch += f"🔹 {ch_name} ({ch_id})\n"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Kanal qo'shish", callback_data="ask_channel_add"),
                 InlineKeyboardButton("🗑️ Kanal o'chirish", callback_data="ask_channel_remove")],
                [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")]
            ])
            await update.message.reply_text(text_ch, reply_markup=kb)
            return

        elif text == "📣 Hammaga xabar yuborish" and is_main_admin(user_id):
            context.user_data["admin_state"] = "broadcast_wait"
            await update.message.reply_text(
                f"📣 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yozing:\n\n"
                f"👥 Jami foydalanuvchilar: {len(users)} ta",
                reply_markup=get_cancel_keyboard()
            )
            return

        elif text == "👑 Adminlarni boshqarish" and is_main_admin(user_id):
            admin_list = "\n".join([f"• {a_id}" for a_id in admins if a_id != ADMIN_ID]) or "Hozircha yo'q"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Admin qo'shish", callback_data="ask_admin_add"),
                 InlineKeyboardButton("➖ Admin o'chirish", callback_data="ask_admin_remove")],
                [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")]
            ])
            await update.message.reply_text(f"👑 Adminlar:\n{admin_list}", reply_markup=kb)
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
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="🏠 Bosh panel",
                reply_markup=get_admin_keyboard(user_id)
            )
        return

    if data == "check":
        if await is_joined(context.bot, user_id):
            await query.answer("✅ Tasdiqlandi!")
            start_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔍 Kinolarni qidirish", switch_inline_query_current_chat="")
            ]])
            await query.message.edit_text(
                "👋 Assalomu alaykum, botimizga xush kelibsiz\n\n"
                "🎥 Bot orqali siz sevimli filmlar, seriallar va multfilmlarni sifatli formatda ko'rishingiz mumkin\n\n"
                "🚀 Shunchaki\n"
                "— Kino yoki serialning kodini yuboring\n"
                "— Pastdagi qidiruv bo'limidan foydalaning",
                reply_markup=start_kb
            )
        else:
            await query.answer("❌ Hali obuna bo'linmagan!", show_alert=True)
        return

    if not is_admin(user_id):
        return

    if data.startswith("del_movie_"):
        kod_to_delete = data.split("_")[2]
        if kod_to_delete in movies:
            del movies[kod_to_delete]
            save_data()
            await query.answer(f"✅ Kod {kod_to_delete} o'chirildi!", show_alert=True)
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="✅ Kino o'chirildi!",
                reply_markup=get_admin_keyboard(user_id)
            )
        else:
            await query.answer("❌ Bu kino allaqachon o'chirilgan", show_alert=True)
        return

    if data == "confirm_save_movie":
        movie_data = context.user_data.get("new_movie")
        if movie_data:
            movies[movie_data["code"]] = {
                "name": movie_data["name"],
                "desc": movie_data["desc"],
                "poster": movie_data["poster"],
                "video_id": movie_data["video_id"]
            }
            save_data()
            context.user_data["admin_state"] = None
            context.user_data.pop("new_movie", None)
            await query.answer("✅ Saqlandi!")
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"✅ Kino qo'shildi! Kod: {movie_data['code']}",
                reply_markup=get_admin_keyboard(user_id)
            )
        return

    elif data == "ask_channel_add":
        context.user_data["admin_state"] = "waiting_channel_add"
        await query.message.edit_text(
            "➕ Yangi kanal qo'shish:\n\n"
            "Format: @kanal_username Kanal Nomi\n"
            "Misol: @mdcmovie MDC Movie\n\n"
            "Yoki bekor qilish uchun:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")
            ]])
        )
        return

    elif data == "ask_channel_remove":
        if not channels:
            await query.answer("❌ O'chiradigan kanal yo'q!", show_alert=True)
            return
        kb = []
        for ch_id, ch_name in channels.items():
            kb.append([InlineKeyboardButton(f"🗑️ {ch_name} ({ch_id})", callback_data=f"remove_channel_{ch_id}")])
        kb.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")])
        await query.message.edit_text("👇 O'chirmoqchi bo'lgan kanalni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    elif data.startswith("remove_channel_"):
        ch_id_to_remove = data[len("remove_channel_"):]
        if ch_id_to_remove in channels:
            ch_name = channels.pop(ch_id_to_remove)
            save_data()
            await query.answer(f"✅ {ch_name} o'chirildi!", show_alert=True)
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"✅ Kanal o'chirildi: {ch_name}",
                reply_markup=get_admin_keyboard(user_id)
            )
        else:
            await query.answer("❌ Kanal topilmadi!", show_alert=True)
        return

    elif data == "ask_admin_add" and is_main_admin(user_id):
        context.user_data["admin_state"] = "waiting_admin_add"
        await query.message.edit_text(
            "➕ Yangi admin qo'shish:\n\n"
            "Foydalanuvchining Telegram ID raqamini yuboring.\n"
            "(ID bilish uchun @userinfobot ga /start yuboring)\n\n"
            "Yoki bekor qilish uchun:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")
            ]])
        )
        return

    elif data == "ask_admin_remove" and is_main_admin(user_id):
        other_admins = [a for a in admins if a != ADMIN_ID]
        if not other_admins:
            await query.answer("❌ O'chiradigan admin yo'q!", show_alert=True)
            return
        kb = []
        for a_id in other_admins:
            kb.append([InlineKeyboardButton(f"❌ {a_id}", callback_data=f"remove_admin_{a_id}")])
        kb.append([InlineKeyboardButton("🔙 Bekor qilish", callback_data="cancel_to_main")])
        await query.message.edit_text("👇 O'chirmoqchi bo'lgan adminni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    elif data == "broadcast_confirm" and is_main_admin(user_id):
        msg_text = context.user_data.get("broadcast_text", "")
        if not msg_text:
            await query.answer("❌ Xabar topilmadi!", show_alert=True)
            return
        await query.answer("📣 Yuborilmoqda...")
        await query.message.delete()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="⏳ Xabar yuborilmoqda...",
            reply_markup=get_admin_keyboard(user_id)
        )
        success = 0
        failed = 0
        for uid in list(users):
            try:
                await context.bot.send_message(chat_id=uid, text=msg_text)
                success += 1
            except Exception:
                failed += 1
        context.user_data.pop("broadcast_text", None)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"✅ Xabar yuborildi!\n\n"
                 f"📨 Muvaffaqiyatli: {success} ta\n"
                 f"❌ Yuborilmadi: {failed} ta",
            reply_markup=get_admin_keyboard(user_id)
        )
        return

    elif data.startswith("remove_admin_") and is_main_admin(user_id):
        remove_id = int(data.split("_")[2])
        if remove_id in admins and remove_id != ADMIN_ID:
            admins.remove(remove_id)
            save_data()
            await query.answer("✅ Admin o'chirildi!", show_alert=True)
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"✅ Admin o'chirildi! ID: {remove_id}",
                reply_markup=get_admin_keyboard(user_id)
            )
        return

# BOTNI WEBHOOK REJIMIDA ISHGA TUSHIRISH
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(InlineQueryHandler(inline_query_handler))
app.add_handler(CallbackQueryHandler(handle_callbacks))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

if RENDER_EXTERNAL_URL:
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        secret_token="BotSecretToken123",
        webhook_url=f"{RENDER_EXTERNAL_URL}/webhook"
    )
else:
    print("Lokal rejimda ishga tushdi...")
    app.run_polling()