import os
import base64
import requests
import json
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

# ==================== SOZLAMALAR ====================
TOKEN = os.environ.get("TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "5837813502"))
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL", "-1003926152488")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("REPO_NAME", "asilbekmuhamadaliyev38-pixel/mega-film-uz")

# ==================== MA'LUMOTLAR STRUKTURASI ====================
admins = set()
movies = {}
channels = {}
catalogs = []
genres = []
users = set()
active_users = set()
deleted_users = set()
admin_states = {}
new_movie_wizard = {}
ad_post_id = None

# Standart xabarlar (O'zingiz xohlagancha tahrirlashingiz mumkin)
bot_settings = {
    "protect_content": True,
    "start_text": (
        "👋 Assalomu alaykum {name}, botimizga xush kelibsiz\n\n"
        "🎥 Bot orqali siz sevimli filmlar, seriallar va multfilmlarni sifatli formatda ko'rishingiz mumkin\n\n"
        "🚀 Shunchaki:\n"
        "— Kino yoki serialning kodini yuboring\n"
        "— Pastdagi bo'limlardan birini tanlang va zavqlaning! 😉"
    ),
    "btn_search": "🔍 Qidiruv",
    "btn_catalog": "🗂️ Katalog bo'yicha",
    "btn_genre": "🎭 Janr bo'yicha"
}

# ==================== GITHUB TIZIMI ====================
def github_get(filename):
    if not GITHUB_TOKEN: return None
    try:
        url = f"https://api.github.com/repos/{REPO_NAME}/contents/{filename}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code == 200 and "content" in res.json():
            return json.loads(base64.b64decode(res.json()["content"]).decode("utf-8"))
    except Exception as e: print(f"GitHub o'qish xatosi ({filename}): {e}")
    return None

def github_put(filename, data, message):
    if not GITHUB_TOKEN: return
    try:
        url = f"https://api.github.com/repos/{REPO_NAME}/contents/{filename}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers, timeout=10)
        sha = res.json().get("sha") if res.status_code == 200 else None
        content = base64.b64encode(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")).decode("utf-8")
        payload = {"message": message, "content": content, "branch": "main"}
        if sha: payload["sha"] = sha
        requests.put(url, headers=headers, json=payload, timeout=12)
    except Exception as e: print(f"GitHub yozish xatosi ({filename}): {e}")

def read_file(filename, default):
    if GITHUB_TOKEN:
        git_data = github_get(filename)
        if git_data is not None:
            write_local(filename, git_data)
            return git_data
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: pass
    return default

def write_local(filename, data):
    with open(filename, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

def save_and_push(filename, data, message):
    write_local(filename, data)
    github_put(filename, data, message)

# ==================== MA'LUMOTLARNI YUKLASH ====================
def load_data():
    global admins, movies, channels, catalogs, genres, users, active_users, deleted_users, ad_post_id, bot_settings
    movies.update(read_file("movies.json", {}))
    channels.update(read_file("channels.json", {}))
    bot_settings.update(read_file("settings.json", bot_settings))
    catalogs.extend(read_file("catalogs.json", ["🍿 Kinolar", "🎬 Seriallar", "🧸 Multfilmlar"]))
    genres.extend(read_file("genres.json", ["🔥 Jangari", "🤣 Komediya", "😢 Drama", "🚀 Fantastika"]))
    
    adm = read_file("admins.json", [ADMIN_ID])
    admins.clear(); admins.update(set(adm)); admins.add(ADMIN_ID)
    users.clear(); users.update(set(read_file("users.json", [])))
    active_users.clear(); active_users.update(set(read_file("active_users.json", list(users))))
    deleted_users.clear(); deleted_users.update(set(read_file("deleted_users.json", [])))
    ad = read_file("ad_post.json", {"id": None})
    ad_post_id = ad.get("id") if isinstance(ad, dict) else None

def track_user(user_id):
    global users, active_users, deleted_users
    is_changed = False
    if user_id not in users: users.add(user_id); is_changed = True
    if user_id not in active_users: active_users.add(user_id); is_changed = True
    if user_id in deleted_users: deleted_users.discard(user_id); is_changed = True
    if is_changed:
        save_and_push("users.json", list(users), "Foydalanuvchilar yangilandi")
        save_and_push("active_users.json", list(active_users), "Faollar yangilandi")
        save_and_push("deleted_users.json", list(deleted_users), "O'chirilganlar yangilandi")

def is_main_admin(user_id): return user_id == ADMIN_ID
def is_admin(user_id): return user_id in admins

# ==================== MENU KLAVIATURALARI ====================
def get_user_keyboard():
    return ReplyKeyboardMarkup([
        [bot_settings.get("btn_search", "🔍 Qidiruv")],
        [bot_settings.get("btn_catalog", "🗂️ Katalog bo'yicha"), bot_settings.get("btn_genre", "🎭 Janr bo'yicha")]
    ], resize_keyboard=True)

def get_admin_keyboard():
    return ReplyKeyboardMarkup([
        ["➕ Kino qo'shish", "🗑️ Kino o'chirish"],
        ["📁 Katalog/Janr Sozlamalari", "📊 Statistika"],
        ["📣 Hammaga xabar", "📢 Reklama xabar"],
        ["⚙️ Bot Sozlamalari"]
    ], resize_keyboard=True)

def get_cancel_keyboard(): return ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)

# ==================== OBUNA TEKSHIRUVI ====================
async def is_joined(bot, user_id):
    if not channels: return True
    for ch_id in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]: return False
        except Exception: return False
    return True

async def get_subscription_keyboard(bot):
    keyboard = []
    for ch_id, ch_name in channels.items():
        try:
            chat = await bot.get_chat(ch_id)
            url = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else "https://t.me")
        except Exception: url = f"https://t.me/{str(ch_id).replace('@', '')}"
        keyboard.append([InlineKeyboardButton(f"📢 {ch_name}", url=url)])
    keyboard.append([InlineKeyboardButton("✅ Tekshirish", callback_data="check")])
    return InlineKeyboardMarkup(keyboard)

# ==================== KINO YUBORISH TIZIMI ====================
async def send_movie(chat_id, movie_code, bot):
    global ad_post_id, bot_settings
    if movie_code not in movies: return False
    data = movies[movie_code]
    
    video_ids_raw = data.get("video_id") if isinstance(data, dict) else data
    if isinstance(video_ids_raw, str): video_ids = [v.strip() for v in video_ids_raw.split(",") if v.strip()]
    elif isinstance(video_ids_raw, list): video_ids = video_ids_raw
    else: video_ids = [str(video_ids_raw)]

    # Har bir kino tagida doimiy qidiruv va bosh menyu tugmalari turadi
    movie_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Film qidirish", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("🏠 Bosh menyu", callback_data="go_to_main_menu")]
    ])
    protect = False if is_admin(chat_id) else bot_settings.get("protect_content", True)

    for vid in video_ids:
        try:
            await bot.copy_message(chat_id=chat_id, from_chat_id=SOURCE_CHANNEL, message_id=int(vid), reply_markup=movie_kb, protect_content=protect)
        except Exception:
            await bot.send_message(chat_id=chat_id, text=f"❌ Film qismi topilmadi (ID: {vid}). Bot manba kanalda admin bo'lishi kerak.")

    if ad_post_id and not is_admin(chat_id):
        try: await bot.copy_message(chat_id=chat_id, from_chat_id=SOURCE_CHANNEL, message_id=int(ad_post_id), protect_content=True)
        except Exception: pass
    return True

# ==================== COMMANDS & START ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    track_user(user_id)
    args = context.args

    if args and args[0].startswith("kino_"):
        movie_code = args[0].split("_")[1]
        if await is_joined(context.bot, user_id):
            await send_movie(update.effective_chat.id, movie_code, context.bot)
        else:
            await update.message.reply_text("❗ Kinoni ko'rish uchun kanallarga obuna bo'ling!", reply_markup=await get_subscription_keyboard(context.bot))
        return

    if is_admin(user_id):
        admin_states[user_id] = None
        await update.message.reply_text("👑 Admin paneli yuklandi:", reply_markup=get_admin_keyboard())
        return

    if not await is_joined(context.bot, user_id):
        await update.message.reply_text("❗ Botdan foydalanish uchun kanallarga qo'shiling!", reply_markup=await get_subscription_keyboard(context.bot))
        return

    welcome_text = bot_settings.get("start_text", "").format(name=update.effective_user.first_name)
    await update.message.reply_text(welcome_text, reply_markup=get_user_keyboard())

# ==================== AQLLI INLINE FILTR TIZIMI ====================
async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    user_id = update.inline_query.from_user.id

    if not await is_joined(context.bot, user_id):
        await update.inline_query.answer([], switch_pm_text="📢 Avval kanallarga obuna bo'ling", switch_pm_parameter="start", cache_time=0)
        return

    filter_type = None
    filter_value = None

    if query.startswith("katalog:"):
        filter_type = "catalog"
        filter_value = query.replace("katalog:", "").strip()
    elif query.startswith("janr:"):
        filter_type = "genre"
        filter_value = query.replace("janr:", "").strip()

    results = []
    for code, data in reversed(list(movies.items())):
        if not isinstance(data, dict): continue
        name = data.get("name", "")
        desc = data.get("desc", "")
        poster = data.get("poster")
        movie_cats = [c.lower() for c in data.get("catalogs", [])]
        movie_gnrs = [g.lower() for g in data.get("genres", [])]

        if poster and not poster.startswith("http"): poster = None

        match = False
        if filter_type == "catalog":
            if not filter_value or any(filter_value in c for c in movie_cats): match = True
        elif filter_type == "genre":
            if not filter_value or any(filter_value in g for g in movie_gnrs): match = True
        else:
            if not query or query in name.lower() or query in code.lower() or query in desc.lower(): match = True

        if match:
            results.append(InlineQueryResultArticle(
                id=code,
                title=f"🎬 {name.upper()}",
                description=f"Kod: {code} | {desc}",
                thumbnail_url=poster,
                input_message_content=InputTextMessageContent(message_text=code)
            ))
            
    await update.inline_query.answer(results[:50], cache_time=0)

# ==================== TEXT HANDLING (ADMIN & USER) ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ad_post_id, bot_settings, catalogs, genres
    user_id = update.effective_user.id
    text = update.message.text.strip()
    track_user(user_id)

    if not is_admin(user_id):
        if text == bot_settings.get("btn_search", "🔍 Qidiruv"):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎬 Kinolarni qidirish", switch_inline_query_current_chat="")]])
            await update.message.reply_text("🍿 Qidiruv tugmasini bosing:", reply_markup=kb)
            return
        elif text == bot_settings.get("btn_catalog", "🗂️ Katalog bo'yicha"):
            kb = [[InlineKeyboardButton(c, switch_inline_query_current_chat=f"katalog:{c}")] for c in catalogs]
            await update.message.reply_text("🗂️ Kerakli katalog turkumini tanlang:", reply_markup=InlineKeyboardMarkup(kb))
            return
        elif text == bot_settings.get("btn_genre", "🎭 Janr bo'yicha"):
            kb = [[InlineKeyboardButton(g, switch_inline_query_current_chat=f"janr:{g}")] for g in genres]
            await update.message.reply_text("🎭 Kerakli kino janrini tanlang:", reply_markup=InlineKeyboardMarkup(kb))
            return
        
        if not await is_joined(context.bot, user_id):
            await update.message.reply_text("❗ Avval kanallarga obuna bo'ling!", reply_markup=await get_subscription_keyboard(context.bot))
            return
        if await send_movie(update.effective_chat.id, text, context.bot): return
        await update.message.reply_text("❌ Bunday kodli kino topilmadi.")
        return

    # ADMIN COMMANDS
    state = admin_states.get(user_id)

    if text in ["❌ Bekor qilish", "🏠 Bosh menyu"]:
        admin_states[user_id] = None
        new_movie_wizard.pop(user_id, None)
        await update.message.reply_text("🏠 Asosiy boshqaruv paneli:", reply_markup=get_admin_keyboard())
        return

    if state == "add_movie_text":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) < 5:
            await update.message.reply_text("❌ Xato! Shablon bo'yicha 5 ta qatorni to'ldirib yuboring:", reply_markup=get_cancel_keyboard())
            return
        new_movie_wizard[user_id] = {
            "name": lines[0], "desc": lines[1], "code": lines[2].lower(), "poster": lines[3], "video_id": lines[4],
            "catalogs": [], "genres": []
        }
        admin_states[user_id] = "add_movie_catalog"
        # Katalog tanlash tugmalari
        kb = [[InlineKeyboardButton(c, callback_data=f"wiz_cat_{i}")] for i, c in enumerate(catalogs)]
        kb.append([InlineKeyboardButton("➡️ Keyingi (Janr tanlash)", callback_data="wiz_cat_done")])
        await update.message.reply_text("🗂️ Kinoni qaysi **Kataloglarga** qo'shasiz? (Bir nechta tanlash mumkin):", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if state == "add_custom_catalog":
        if text not in catalogs: catalogs.append(text)
        save_and_push("catalogs.json", catalogs, "Yangi katalog qo'shildi")
        admin_states[user_id] = None
        await update.message.reply_text(f"✅ Yangi katalog qo'shildi: {text}", reply_markup=get_admin_keyboard())
        return

    if state == "add_custom_genre":
        if text not in genres: genres.append(text)
        save_and_push("genres.json", genres, "Yangi janr qo'shildi")
        admin_states[user_id] = None
        await update.message.reply_text(f"✅ Yangi janr qo'shildi: {text}", reply_markup=get_admin_keyboard())
        return

    if state == "edit_start_text":
        bot_settings["start_text"] = text
        save_and_push("settings.json", bot_settings, "Start matni o'zgartirildi")
        admin_states[user_id] = None
        await update.message.reply_text("✅ Start salomlashish matni muvaffaqiyatli o'zgartirildi!", reply_markup=get_admin_keyboard())
        return

    if state == "channel_add_universal":
        parts = text.split(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Xato format. Namuna:\n`@username Kanal Nomi` yoki `-100123456 Kanal Nomi`", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
            return
        channels[parts[0].strip()] = parts[1].strip()
        save_and_push("channels.json", channels, "Kanal ro'yxati yangilandi")
        admin_states[user_id] = None
        await update.message.reply_text("✅ Majburiy obuna kanali muvaffaqiyatli saqlandi!", reply_markup=get_admin_keyboard())
        return

    if state == "broadcast":
        context.user_data["broadcast_text"] = text
        admin_states[user_id] = None
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yuborishni tasdiqlash", callback_data="broadcast_confirm")]])
        await update.message.reply_text("📣 Xabar barcha faol foydalanuvchilarga yuborilsinmi?", reply_markup=kb)
        return

    if state == "set_ad":
        ad_post_id = None if text == "0" else text
        save_and_push("ad_post.json", {"id": ad_post_id}, "Reklama yangilandi")
        admin_states[user_id] = None
        await update.message.reply_text("✅ Reklama posti o'rnatildi!", reply_markup=get_admin_keyboard())
        return

    # INTERFACE BUTTONS CLICKED
    if text == "➕ Kino qo'shish":
        admin_states[user_id] = "add_movie_text"
        shablon = (
            "➕ **Kino qo'shish uchun quyidagi 5 qatorli shablonni to'ldirib yuboring:**\n\n"
            "`Garri Potter 3`\n"
            "`Sehrgarlar haqida qiziqarli film`\n"
            "`300`\n"
            "`https://images.com/poster.jpg`\n"
            "`1254,1255`\n\n"
            "⚠️ **Eslatma:** Ko'p qismli bo'lsa oxirgi qatorga ID larni vergul bilan yozing."
        )
        await update.message.reply_text(shablon, reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
        return

    if text == "🗑️ Kino o'chirish":
        if not movies:
            await update.message.reply_text("Baza bo'sh.")
            return
        kb = [[InlineKeyboardButton(f"🗑️ {c}", callback_data=f"del_{c}")] for c in movies]
        await update.message.reply_text("O'chirish uchun kino kodini tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if text == "📁 Katalog/Janr Sozlamalari":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Yangi Katalog qo'shish", callback_data="add_cat"), InlineKeyboardButton("➕ Yangi Janr qo'shish", callback_data="add_gen")],
            [InlineKeyboardButton("🗑️ Katalogni o'chirish", callback_data="list_del_cat"), InlineKeyboardButton("🗑️ Janrni o'chirish", callback_data="list_del_gen")]
        ])
        await update.message.reply_text("📁 **Katalog va Janr boshqaruvi:**", reply_markup=kb, parse_mode="Markdown")
        return

    if text == "📊 Statistika":
        bot_info = await context.bot.get_me()
        stat_msg = (
            "📊 BOT STATISTIKASI\n"
            "#statistics\n\n"
            f"@{bot_info.username}\n"
            "▪️Yaratilgan: 03.05.2025\n\n"
            f"▪️Foydalanuvchilar: {len(users)}\n"
            f"▫️Faol: {len(active_users)}\n"
            f"▫️O'chirilgan: {len(deleted_users)}\n"
            f"▪️Adminlar: {len(admins)}"
        )
        await update.message.reply_text(stat_msg)
        return

    if text == "📣 Hammaga xabar":
        admin_states[user_id] = "broadcast"
        await update.message.reply_text("Barcha foydalanuvchilarga boradigan matnni yozing:", reply_markup=get_cancel_keyboard())
        return

    if text == "📢 Reklama xabar":
        admin_states[user_id] = "set_ad"
        await update.message.reply_text("Manba kanaldagi Reklama Post ID raqamini kiriting (O'chirish uchun 0):", reply_markup=get_cancel_keyboard())
        return

    if text == "⚙️ Bot Sozlamalari":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Start matnini o'zgartirish", callback_data="edit_start")],
            [InlineKeyboardButton("📢 Majburiy Kanallar", callback_data="manage_ch")]
        ])
        await update.message.reply_text("⚙️ **Bot sozlamalari bo'limi:**", reply_markup=kb, parse_mode="Markdown")
        return

# ==================== CALLBACKS (INLINE ACTIONS) ====================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global movies, channels, catalogs, genres, users, active_users, deleted_users
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "check":
        if await is_joined(context.bot, user_id):
            await query.answer("✅ Rahmat, obuna tasdiqlandi!")
            await query.message.delete()
            await context.bot.send_message(chat_id=user_id, text=bot_settings.get("start_text", "").format(name=query.from_user.first_name), reply_markup=get_user_keyboard())
        else:
            await query.answer("❌ Kanallarga hali a'zo bo'lmadingiz!", show_alert=True)
        return

    if data == "go_to_main_menu":
        await query.answer()
        await context.bot.send_message(chat_id=user_id, text="🏠 Bosh menyu:", reply_markup=get_user_keyboard())
        return

    if not is_admin(user_id): return

    # WIZARD: KATALOG TANLASH
    if data.startswith("wiz_cat_"):
        val = data[8:]
        wiz = new_movie_wizard.get(user_id)
        if wiz:
            if val == "done":
                admin_states[user_id] = "add_movie_genre"
                kb = [[InlineKeyboardButton(g, callback_data=f"wiz_gen_{i}")] for i, g in enumerate(genres)]
                kb.append([InlineKeyboardButton("➡️ Yakunlash va Saqlash", callback_data="wiz_gen_done")])
                await query.message.edit_text("🎭 Endi kinoning **Janrlarini** tanlang (Bir nechta tanlash mumkin):", reply_markup=InlineKeyboardMarkup(kb))
            else:
                c_name = catalogs[int(val)]
                if c_name not in wiz["catalogs"]: wiz["catalogs"].append(c_name)
                await query.answer(f"➕ {c_name} tanlandi")
        return

    # WIZARD: JANR TANLASH VA YAKUNLASH
    if data.startswith("wiz_gen_"):
        val = data[8:]
        wiz = new_movie_wizard.get(user_id)
        if wiz:
            if val == "done":
                movies[wiz["code"]] = wiz
                save_and_push("movies.json", movies, f"Kino qo'shildi: {wiz['code']}")
                admin_states[user_id] = None
                new_movie_wizard.pop(user_id, None)
                await query.message.delete()
                await context.bot.send_message(chat_id=user_id, text=f"✅ Kino muvaffaqiyatli bazaga qo'shildi! Kod: {wiz['code']}", reply_markup=get_admin_keyboard())
            else:
                g_name = genres[int(val)]
                if g_name not in wiz["genres"]: wiz["genres"].append(g_name)
                await query.answer(f"➕ {g_name} tanlandi")
        return

    # BO'LIMLARNI O'CHIRISH/QO'SHISH
    if data == "add_cat":
        admin_states[user_id] = "add_custom_catalog"
        await query.message.delete()
        await context.bot.send_message(chat_id=user_id, text="📝 Yangi katalog nomini premium emojilar bilan yuboring (Masalan: `🍿 2026-kinolari`):", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
        return

    if data == "add_gen":
        admin_states[user_id] = "add_custom_genre"
        await query.message.delete()
        await context.bot.send_message(chat_id=user_id, text="📝 Yangi janr nomini yuboring (Masalan: `⚡ Fantastika`):", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
        return

    if data == "list_del_cat":
        kb = [[InlineKeyboardButton(f"🗑️ {c}", callback_data=f"dc_cat_{i}")] for i, c in enumerate(catalogs)]
        await query.message.edit_text("O'chirish uchun katalogni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("dc_cat_"):
        idx = int(data[7:])
        if idx < len(catalogs):
            del catalogs[idx]
            save_and_push("catalogs.json", catalogs, "Katalog o'chirildi")
            await query.answer("O'chirildi")
            await query.message.delete()
        return

    if data == "list_del_gen":
        kb = [[InlineKeyboardButton(f"🗑️ {g}", callback_data=f"dc_gen_{i}")] for i, g in enumerate(genres)]
        await query.message.edit_text("O'chirish uchun janrni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("dc_gen_"):
        idx = int(data[7:])
        if idx < len(genres):
            del genres[idx]
            save_and_push("genres.json", genres, "Janr o'chirildi")
            await query.answer("O'chirildi")
            await query.message.delete()
        return

    if data == "edit_start":
        admin_states[user_id] = "edit_start_text"
        await query.message.delete()
        await context.bot.send_message(chat_id=user_id, text="📝 Yangi start salomlashish matnini premium emojilar bilan yuboring. `{name}` yozuvi foydalanuvchi ismini chiqaradi.", reply_markup=get_cancel_keyboard())
        return

    if data == "manage_ch":
        ch_list = "\n".join([f"🔹 {n} (`{i}`)" for i, n in channels.items()]) or "Kanallar yo'q"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Qo'shish", callback_data="add_ch_univ"), InlineKeyboardButton("🗑️ O'chirish", callback_data="del_ch_univ")]
        ])
        await query.message.edit_text(f"📢 **Majburiy obuna kanallari:**\n\n{ch_list}", reply_markup=kb, parse_mode="Markdown")
        return

    if data == "add_ch_univ":
        admin_states[user_id] = "channel_add_universal"
        await query.message.delete()
        await context.bot.send_message(chat_id=user_id, text="➕ **Kanal qo'shish formatini yuboring:**\n\n`@username Kanal Nomi`\nyoki\n`-100234567890 Kanal Nomi`", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
        return

    if data == "del_ch_univ":
        kb = [[InlineKeyboardButton(f"🗑️ {n}", callback_data=f"dc_ch_{i}")] for i, n in channels.items()]
        await query.message.edit_text("O'chirish uchun kanalni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("dc_ch_"):
        ch_key = data[6:]
        if ch_key in channels:
            del channels[ch_key]
            save_and_push("channels.json", channels, "Kanal o'chirildi")
            await query.answer("O'chirildi")
            await query.message.delete()
        return

    if data.startswith("del_"):
        code = data[4:]
        if code in movies:
            del movies[code]
            save_and_push("movies.json", movies, f"Kino o'chirildi: {code}")
            await query.answer("O'chirildi")
            await query.message.delete()
        return

    if data == "broadcast_confirm":
        msg_text = context.user_data.get("broadcast_text", "")
        await query.message.delete()
        success, failed = 0, 0
        for uid in list(users):
            try:
                await context.bot.send_message(chat_id=uid, text=msg_text)
                success += 1
                active_users.add(uid); deleted_users.discard(uid)
            except Exception:
                failed += 1
                active_users.discard(uid); deleted_users.add(uid)
        save_and_push("active_users.json", list(active_users), "Xabardan keyin faollar yangilandi")
        save_and_push("deleted_users.json", list(deleted_users), "Xabardan keyin o'chirilganlar yangilandi")
        await context.bot.send_message(chat_id=user_id, text=f"📣 Xabar yakunlandi:\n\n🟢 Muvaffaqiyatli: {success}\n🔴 Bloklangan: {failed}", reply_markup=get_admin_keyboard())
        return

# ==================== RUN BOT ====================
load_data()

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(InlineQueryHandler(inline_query_handler))
app.add_handler(CallbackQueryHandler(handle_callback))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

if RENDER_EXTERNAL_URL:
    PORT = int(os.environ.get("PORT", 10000))
    app.run_webhook(listen="0.0.0.0", port=PORT, url_path="webhook", webhook_url=f"{RENDER_EXTERNAL_URL}/webhook")
else:
    app.run_polling()
