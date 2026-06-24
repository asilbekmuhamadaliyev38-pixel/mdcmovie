import os
import base64
import requests
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

# ==================== SOZLAMALAR ====================
TOKEN = os.environ.get("TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "5837813502"))
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL", "-1003926152488")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("REPO_NAME", "asilbekmuhamadaliyev38-pixel/mdcmovie")

# ==================== MA'LUMOTLAR ====================
admins = set()
movies = {}
channels = {}
catalogs = []
genres = []
users = set()
active_users = set()
deleted_users = set()
blocked_users = set()
admin_states = {}
new_movie_wizard = {}
ad_post_id = None
views = {}          # {movie_code: count}
saved_movies = {}   # {user_id: [code1, code2, ...]}
admin_logs = []     # [{admin, action, time}]

bot_settings = {
    "protect_content": True,
    "start_text": (
        "👋 Assalomu alaykum {name}, botimizga xush kelibsiz\n\n"
        "🎥 Bot orqali siz sevimli filmlar, seriallar va multfilmlarni sifatli formatda ko'rishingiz mumkin\n\n"
        "🚀 Shunchaki:\n"
        "— Kino yoki serialning kodini yuboring\n"
        "— Pastdagi bo'limlardan birini tanlang va zavqlaning! 😉"
    )
}

# ==================== GITHUB ====================
def github_get(filename):
    if not GITHUB_TOKEN: return None
    try:
        url = f"https://api.github.com/repos/{REPO_NAME}/contents/{filename}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code == 200 and "content" in res.json():
            return json.loads(base64.b64decode(res.json()["content"]).decode("utf-8"))
    except Exception: pass
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
    except Exception: pass

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
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_and_push(filename, data, message):
    write_local(filename, data)
    github_put(filename, data, message)

# ==================== MA'LUMOT YUKLASH ====================
def load_data():
    global admins, movies, channels, catalogs, genres, users, active_users
    global deleted_users, blocked_users, ad_post_id, bot_settings
    global views, saved_movies, admin_logs

    movies.update(read_file("movies.json", {}))
    channels.update(read_file("channels.json", {}))
    bot_settings.update(read_file("settings.json", bot_settings))
    views.update(read_file("views.json", {}))
    saved_movies_raw = read_file("saved_movies.json", {})
    saved_movies.update({str(k): v for k, v in saved_movies_raw.items()})
    admin_logs_raw = read_file("admin_logs.json", [])
    admin_logs.extend(admin_logs_raw[-200:])

    loaded_cats = read_file("catalogs.json", [])
    catalogs.clear()
    catalogs.extend(loaded_cats if loaded_cats else ["🍿 Kinolar", "🎬 Seriallar", "🧸 Multfilmlar"])

    loaded_gnrs = read_file("genres.json", [])
    genres.clear()
    genres.extend(loaded_gnrs if loaded_gnrs else ["🔥 Jangari", "🤣 Komediya", "😢 Drama", "🚀 Fantastika"])

    adm = read_file("admins.json", [ADMIN_ID])
    admins.clear(); admins.update(set(adm)); admins.add(ADMIN_ID)

    users.clear(); users.update(set(read_file("users.json", [])))
    active_users.clear(); active_users.update(set(read_file("active_users.json", list(users))))
    deleted_users.clear(); deleted_users.update(set(read_file("deleted_users.json", [])))
    blocked_users.clear(); blocked_users.update(set(read_file("blocked_users.json", [])))

    ad = read_file("ad_post.json", {"id": None})
    ad_post_id = ad.get("id") if isinstance(ad, dict) else None

def add_log(admin_id, action):
    entry = {"admin": admin_id, "action": action, "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    admin_logs.append(entry)
    if len(admin_logs) > 200:
        admin_logs.pop(0)
    save_and_push("admin_logs.json", admin_logs, "Log yangilandi")

def track_user(user_id):
    global users, active_users, deleted_users
    changed = False
    if user_id not in users: users.add(user_id); changed = True
    if user_id not in active_users: active_users.add(user_id); changed = True
    if user_id in deleted_users: deleted_users.discard(user_id); changed = True
    if changed:
        save_and_push("users.json", list(users), "Foydalanuvchi yangilandi")
        save_and_push("active_users.json", list(active_users), "Faollar yangilandi")
        save_and_push("deleted_users.json", list(deleted_users), "O'chirilganlar yangilandi")

def increment_views(movie_code):
    views[movie_code] = views.get(movie_code, 0) + 1
    save_and_push("views.json", views, "Ko'rishlar yangilandi")

def is_admin(user_id): return user_id in admins
def is_blocked(user_id): return user_id in blocked_users

# ==================== KLAVIATURALAR ====================
def get_user_inline_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Qidiruv", switch_inline_query_current_chat="")],
        [
            InlineKeyboardButton("📂 Katalog", callback_data="user_show_catalogs"),
            InlineKeyboardButton("🎭 Janr", callback_data="user_show_genres")
        ],
        [
            InlineKeyboardButton("🔥 Top kinolar", switch_inline_query_current_chat="top"),
            InlineKeyboardButton("❤️ Saqlanganlar", callback_data="my_saved")
        ]
    ])

def get_admin_keyboard():
    return ReplyKeyboardMarkup([
        ["➕ Kino qo'shish", "✏️ Kino tahrirlash"],
        ["🗑️ Kino o'chirish", "📋 Kinolar ro'yxati"],
        ["📈 Top kinolar", "📁 Katalog/Janr"],
        ["📊 Statistika", "📢 Reklama xabar"],
        ["📣 Hammaga xabar", "🚫 Foydalanuvchi blok"],
        ["📝 Admin loglar", "⚙️ Bot Sozlamalari"]
    ], resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)

def get_return_main_keyboard():
    return ReplyKeyboardMarkup([["🏠 Asosiy panelga qaytish"]], resize_keyboard=True)

# ==================== OBUNA ====================
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
        except Exception:
            url = f"https://t.me/{str(ch_id).replace('@', '')}"
        keyboard.append([InlineKeyboardButton(f"📢 {ch_name}", url=url)])
    keyboard.append([InlineKeyboardButton("✅ Tekshirish", callback_data="check")])
    return InlineKeyboardMarkup(keyboard)

# ==================== KINO YUBORISH ====================
async def send_movie(chat_id, movie_code, bot, notify_new=False):
    global ad_post_id, bot_settings
    if movie_code not in movies: return False
    data = movies[movie_code]

    video_ids_raw = data.get("video_id") if isinstance(data, dict) else data
    if isinstance(video_ids_raw, str):
        video_ids = [v.strip() for v in video_ids_raw.split(",") if v.strip()]
    elif isinstance(video_ids_raw, list):
        video_ids = video_ids_raw
    else:
        video_ids = [str(video_ids_raw)]

    name = data.get("name", movie_code) if isinstance(data, dict) else movie_code
    protect = False if is_admin(chat_id) else bot_settings.get("protect_content", True)

    movie_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Film qidirish", switch_inline_query_current_chat="")],
        [
            InlineKeyboardButton("❤️ Saqlash", callback_data=f"save_{movie_code}"),
            InlineKeyboardButton("🏠 Bosh menyu", callback_data="go_to_main_menu")
        ]
    ])

    success = False
    for vid in video_ids:
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=SOURCE_CHANNEL,
                message_id=int(vid),
                reply_markup=movie_kb,
                protect_content=protect
            )
            success = True
        except Exception: pass

    if not success: return False

    if not is_admin(chat_id):
        increment_views(movie_code)

    if ad_post_id and not is_admin(chat_id):
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=SOURCE_CHANNEL,
                message_id=int(ad_post_id),
                protect_content=True
            )
        except Exception: pass

    return True

# ==================== START ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if is_blocked(user_id):
        await update.message.reply_text("❌ Siz botdan bloklangansiz.")
        return

    track_user(user_id)
    args = context.args

    if args and args[0].startswith("kino_"):
        movie_code = args[0].split("_")[1]
        if await is_joined(context.bot, user_id):
            if not await send_movie(update.effective_chat.id, movie_code, context.bot):
                await update.message.reply_text("❌ Bunday kodli kino topilmadi.")
        else:
            await update.message.reply_text(
                "❗ Kinoni ko'rish uchun kanallarga obuna bo'ling!",
                reply_markup=await get_subscription_keyboard(context.bot)
            )
        return

    if is_admin(user_id):
        admin_states[user_id] = None
        await update.message.reply_text("👑 Admin boshqaruv paneli:", reply_markup=get_admin_keyboard())
        return

    if not await is_joined(context.bot, user_id):
        await update.message.reply_text(
            "❗ Botdan foydalanish uchun kanallarga qo'shiling!",
            reply_markup=await get_subscription_keyboard(context.bot)
        )
        return

    welcome = bot_settings.get("start_text", "").format(name=update.effective_user.first_name)
    await update.message.reply_text(welcome, reply_markup=get_user_inline_keyboard())

# ==================== INLINE QUERY ====================
async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    user_id = update.inline_query.from_user.id

    if not await is_joined(context.bot, user_id):
        await update.inline_query.answer(
            [], switch_pm_text="📢 Avval kanallarga obuna bo'ling",
            switch_pm_parameter="start", cache_time=0
        )
        return

    filter_type, filter_value = None, None
    if query.startswith("katalog:"):
        filter_type = "catalog"
        filter_value = query.replace("katalog:", "").strip().lower()
    elif query.startswith("janr:"):
        filter_type = "genre"
        filter_value = query.replace("janr:", "").strip().lower()
    elif query == "top":
        filter_type = "top"
        filter_value = None

    results = []
    for code, data in reversed(list(movies.items())):
        name = data.get("name", "") if isinstance(data, dict) else f"Kino {code}"
        desc = data.get("desc", "") if isinstance(data, dict) else ""
        poster = data.get("poster") if isinstance(data, dict) else None
        movie_cats = [c.lower() for c in data.get("catalogs", [])] if isinstance(data, dict) else []
        movie_gnrs = [g.lower() for g in data.get("genres", [])] if isinstance(data, dict) else []
        view_count = views.get(code, 0)

        if poster and not poster.startswith("http"): poster = None

        match = False
        if filter_type == "catalog":
            if not filter_value or any(filter_value in c for c in movie_cats): match = True
        elif filter_type == "genre":
            if not filter_value or any(filter_value in g for g in movie_gnrs): match = True
        elif filter_type == "top":
            match = True
        else:
            if not query or query in name.lower() or query in str(code).lower() or query in desc.lower(): match = True

        if match:
            results.append(InlineQueryResultArticle(
                id=code,
                title=f"🎬 {name.upper()}",
                description=f"👁 {view_count} | Kod: {code} | {desc}",
                thumbnail_url=poster,
                input_message_content=InputTextMessageContent(message_text=str(code))
            ))

    if filter_type == "top":
        results.sort(key=lambda r: views.get(r.id, 0), reverse=True)
        results = results[:20]

    await update.inline_query.answer(results[:50], cache_time=0)

# ==================== MATN XABARLARI ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ad_post_id, bot_settings, catalogs, genres, movies
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if is_blocked(user_id):
        await update.message.reply_text("❌ Siz botdan bloklangansiz.")
        return

    track_user(user_id)

    if text in ["❌ Bekor qilish", "🏠 Asosiy panelga qaytish"]:
        admin_states[user_id] = None
        new_movie_wizard.pop(user_id, None)
        if is_admin(user_id):
            await update.message.reply_text("🏠 Admin paneli:", reply_markup=get_admin_keyboard())
        else:
            welcome = bot_settings.get("start_text", "").format(name=update.effective_user.first_name)
            await update.message.reply_text(welcome, reply_markup=get_user_inline_keyboard())
        return

    if not is_admin(user_id):
        if not await is_joined(context.bot, user_id):
            await update.message.reply_text(
                "❗ Avval kanallarga obuna bo'ling!",
                reply_markup=await get_subscription_keyboard(context.bot)
            )
            return
        if await send_movie(update.effective_chat.id, text, context.bot): return
        await update.message.reply_text("❌ Bunday kodli kino topilmadi.")
        return

    state = admin_states.get(user_id)

    if state == "delete_movie_by_code":
        code = text.lower()
        if code in movies:
            name = movies[code].get("name", code) if isinstance(movies[code], dict) else code
            del movies[code]
            views.pop(code, None)
            save_and_push("movies.json", movies, f"Kino o'chirildi: {code}")
            save_and_push("views.json", views, "Ko'rishlar yangilandi")
            add_log(user_id, f"Kino o'chirildi: {name} ({code})")
            admin_states[user_id] = None
            await update.message.reply_text(f"✅ '{name}' kinosi o'chirildi!", reply_markup=get_admin_keyboard())
        else:
            await update.message.reply_text("❌ Bunday kodli kino topilmadi:", reply_markup=get_cancel_keyboard())
        return

    if state == "add_movie_text":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) < 5:
            await update.message.reply_text("❌ 5 ta qator kerak! Qayta yuboring:", reply_markup=get_cancel_keyboard())
            return
        new_movie_wizard[user_id] = {
            "name": lines[0], "desc": lines[1], "code": lines[2].lower(),
            "poster": lines[3], "video_id": lines[4],
            "catalogs": [], "genres": []
        }
        admin_states[user_id] = "add_movie_catalog"
        kb = [[InlineKeyboardButton(cat, callback_data=f"wiz_cat_{i}")] for i, cat in enumerate(catalogs)]
        kb.append([InlineKeyboardButton("➡️ Keyingi (Janr)", callback_data="wiz_cat_done")])
        await update.message.reply_text(
            "🗂 Katalog tanlang (bir nechta bo'lishi mumkin):",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        await update.message.reply_text("Bekor qilish:", reply_markup=get_return_main_keyboard())
        return

    if state == "edit_movie_select":
        code = text.lower()
        if code not in movies:
            await update.message.reply_text("❌ Bunday kod topilmadi:", reply_markup=get_cancel_keyboard())
            return
        admin_states[user_id] = None
        data = movies[code]
        name = data.get("name", code) if isinstance(data, dict) else code
        cur_cats = movies[code].get("catalogs", []) if isinstance(movies[code], dict) else []
        cur_gnrs = movies[code].get("genres", []) if isinstance(movies[code], dict) else []
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📛 Nom", callback_data=f"edit_name_{code}"),
             InlineKeyboardButton("📝 Ma'lumot", callback_data=f"edit_desc_{code}")],
            [InlineKeyboardButton("🖼 Poster", callback_data=f"edit_poster_{code}"),
             InlineKeyboardButton("📥 Video ID", callback_data=f"edit_vid_{code}")],
            [InlineKeyboardButton("📂 Katalog", callback_data=f"edit_cats_{code}"),
             InlineKeyboardButton("🎭 Janr", callback_data=f"edit_gnrs_{code}")],
            [InlineKeyboardButton("❌ Bekor", callback_data="cancel_edit")]
        ])
        cats_str = ", ".join(cur_cats) if cur_cats else "Yo'q"
        gnrs_str = ", ".join(cur_gnrs) if cur_gnrs else "Yo'q"
        await update.message.reply_text(
            f"✏️ '{name}' — nimani tahrirlaysiz?\n\n📂 Katalog: {cats_str}\n🎭 Janr: {gnrs_str}",
            reply_markup=kb
        )
        return

    if state and state.startswith("edit_field_"):
        parts = state.split("_", 3)
        field = parts[2]
        code = parts[3]
        if code in movies:
            if field == "name": movies[code]["name"] = text
            elif field == "desc": movies[code]["desc"] = text
            elif field == "poster": movies[code]["poster"] = text
            elif field == "vid": movies[code]["video_id"] = text
            save_and_push("movies.json", movies, f"Kino tahrirlandi: {code}")
            add_log(user_id, f"Kino tahrirlandi: {code} ({field})")
            admin_states[user_id] = None
            await update.message.reply_text(f"✅ Yangilandi!", reply_markup=get_admin_keyboard())
        return

    if state == "add_custom_catalog":
        if text not in catalogs:
            catalogs.append(text)
            save_and_push("catalogs.json", catalogs, "Katalog qo'shildi")
        admin_states[user_id] = None
        await update.message.reply_text(f"✅ Katalog qo'shildi: {text}", reply_markup=get_admin_keyboard())
        return

    if state == "add_custom_genre":
        if text not in genres:
            genres.append(text)
            save_and_push("genres.json", genres, "Janr qo'shildi")
        admin_states[user_id] = None
        await update.message.reply_text(f"✅ Janr qo'shildi: {text}", reply_markup=get_admin_keyboard())
        return

    if state == "edit_start_text":
        bot_settings["start_text"] = text
        save_and_push("settings.json", bot_settings, "Start matni yangilandi")
        admin_states[user_id] = None
        await update.message.reply_text("✅ Start matni yangilandi!", reply_markup=get_admin_keyboard())
        return

    if state == "channel_add":
        parts = text.split(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Format:\n@username Kanal nomi\nyoki\n-1001234567890 Kanal nomi", reply_markup=get_cancel_keyboard())
            return
        channels[parts[0].strip()] = parts[1].strip()
        save_and_push("channels.json", channels, "Kanal qo'shildi")
        admin_states[user_id] = None
        await update.message.reply_text("✅ Kanal qo'shildi!", reply_markup=get_admin_keyboard())
        return

    if state == "broadcast":
        context.user_data["broadcast_text"] = text
        admin_states[user_id] = None
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yuborish", callback_data="broadcast_confirm"),
            InlineKeyboardButton("❌ Bekor", callback_data="cancel_broadcast")
        ]])
        await update.message.reply_text(
            f"📣 Xabar:\n\n{text}\n\n👥 {len(users)} ta foydalanuvchiga yuboriladi. Tasdiqlaysizmi?",
            reply_markup=kb
        )
        return

    if state == "set_ad":
        if not text.lstrip("-").isdigit():
            await update.message.reply_text("❌ Faqat raqam (Post ID):", reply_markup=get_cancel_keyboard())
            return
        ad_post_id = None if text == "0" else text
        save_and_push("ad_post.json", {"id": ad_post_id}, "Reklama yangilandi")
        admin_states[user_id] = None
        msg = "✅ Reklama o'chirildi." if ad_post_id is None else f"✅ Reklama o'rnatildi! Post ID: {ad_post_id}"
        await update.message.reply_text(msg, reply_markup=get_admin_keyboard())
        return

    if state == "block_user":
        if not text.isdigit():
            await update.message.reply_text("❌ Faqat Telegram ID raqamini kiriting:", reply_markup=get_cancel_keyboard())
            return
        uid = int(text)
        if uid == ADMIN_ID:
            await update.message.reply_text("❌ Asosiy adminni bloklash mumkin emas!", reply_markup=get_cancel_keyboard())
            return
        blocked_users.add(uid)
        save_and_push("blocked_users.json", list(blocked_users), "Foydalanuvchi bloklandi")
        add_log(user_id, f"Foydalanuvchi bloklandi: {uid}")
        admin_states[user_id] = None
        await update.message.reply_text(f"✅ {uid} bloklandi!", reply_markup=get_admin_keyboard())
        return

    if state == "unblock_user":
        if not text.isdigit():
            await update.message.reply_text("❌ Faqat Telegram ID raqamini kiriting:", reply_markup=get_cancel_keyboard())
            return
        uid = int(text)
        blocked_users.discard(uid)
        save_and_push("blocked_users.json", list(blocked_users), "Foydalanuvchi blokdan chiqarildi")
        add_log(user_id, f"Foydalanuvchi blokdan chiqarildi: {uid}")
        admin_states[user_id] = None
        await update.message.reply_text(f"✅ {uid} blokdan chiqarildi!", reply_markup=get_admin_keyboard())
        return

    # ADMIN TUGMALARI
    if text == "➕ Kino qo'shish":
        admin_states[user_id] = "add_movie_text"
        await update.message.reply_text(
            "➕ 5 qatorli shablonni to'ldirib yuboring:\n\n"
            "Kino nomi\n"
            "Tavsif\n"
            "kod\n"
            "https://poster.jpg\n"
            "PostID\n\n"
            "Misol:\nAvengers\nMarvel filmi, 4K\navengers\nhttps://example.com/p.jpg\n12345",
            reply_markup=get_cancel_keyboard()
        )
        return

    if text == "✏️ Kino tahrirlash":
        admin_states[user_id] = "edit_movie_select"
        await update.message.reply_text("✏️ Tahrirlash uchun kino kodini yuboring:", reply_markup=get_cancel_keyboard())
        return

    if text == "🗑️ Kino o'chirish":
        admin_states[user_id] = "delete_movie_by_code"
        await update.message.reply_text("🗑️ O'chirmoqchi bo'lgan kino kodini yuboring:", reply_markup=get_cancel_keyboard())
        return

    if text == "📈 Top kinolar":
        if not views:
            await update.message.reply_text("Hali hech kim kino ko'rmagan.")
            return
        sorted_views = sorted(views.items(), key=lambda x: x[1], reverse=True)[:10]
        lines = []
        for i, (code, count) in enumerate(sorted_views, 1):
            name = movies[code].get("name", code).upper() if code in movies and isinstance(movies[code], dict) else code
            lines.append(f"{i}. {name} — 👁 {count}")
        await update.message.reply_text("📈 Top 10 kino:\n\n" + "\n".join(lines))
        return

    if text == "📁 Katalog/Janr":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Katalog qo'shish", callback_data="add_cat"),
             InlineKeyboardButton("➕ Janr qo'shish", callback_data="add_gen")],
            [InlineKeyboardButton("🗑️ Katalog o'chirish", callback_data="list_del_cat"),
             InlineKeyboardButton("🗑️ Janr o'chirish", callback_data="list_del_gen")]
        ])
        await update.message.reply_text("📁 Katalog va Janr sozalamalari:", reply_markup=kb)
        await update.message.reply_text("Qaytish:", reply_markup=get_return_main_keyboard())
        return

    if text == "📊 Statistika":
        await update.message.reply_text(
            f"📊 Statistika:\n\n"
            f"👥 Jami: {len(users)}\n"
            f"✅ Faol: {len(active_users)}\n"
            f"❌ Bloklagan: {len(deleted_users)}\n"
            f"🚫 Botda bloklangan: {len(blocked_users)}\n"
            f"🎬 Kinolar: {len(movies)}\n"
            f"👁 Jami ko'rishlar: {sum(views.values())}"
        )
        return

    if text == "📣 Hammaga xabar":
        admin_states[user_id] = "broadcast"
        await update.message.reply_text(
            f"📣 Xabar yozing ({len(users)} ta foydalanuvchi):",
            reply_markup=get_cancel_keyboard()
        )
        return

    if text == "📢 Reklama xabar":
        cur = f"Hozirgi: Post ID {ad_post_id}" if ad_post_id else "Hozircha yo'q"
        admin_states[user_id] = "set_ad"
        await update.message.reply_text(
            f"📢 Reklama: {cur}\n\nPost ID yuboring (o'chirish: 0):",
            reply_markup=get_cancel_keyboard()
        )
        return

    if text == "🚫 Foydalanuvchi blok":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Bloklash", callback_data="block_u"),
             InlineKeyboardButton("✅ Blokdan chiqarish", callback_data="unblock_u")]
        ])
        bl_list = "\n".join([str(u) for u in list(blocked_users)[:10]]) or "Yo'q"
        await update.message.reply_text(
            f"🚫 Bloklangan foydalanuvchilar ({len(blocked_users)} ta):\n{bl_list}",
            reply_markup=kb
        )
        return

    if text == "📋 Kinolar ro'yxati":
        if not movies:
            await update.message.reply_text("🎬 Bazada hech qanday kino yo'q.")
            return
        lines_list = []
        for code, d in movies.items():
            name = d.get("name", code).upper() if isinstance(d, dict) else code.upper()
            vc = views.get(code, 0)
            lines_list.append(f"🔑 {code} — {name} 👁{vc}")
        msg = f"🎬 Kinolar ro'yxati ({len(movies)} ta):\n\n" + "\n".join(lines_list[:50])
        await update.message.reply_text(msg)
        return

    if text == "📝 Admin loglar":
        if not admin_logs:
            await update.message.reply_text("Loglar yo'q.")
            return
        last = admin_logs[-20:][::-1]
        lines = [f"🕐 {l['time']}\n👤 {l['admin']}: {l['action']}" for l in last]
        await update.message.reply_text("📝 Oxirgi 20 ta amal:\n\n" + "\n\n".join(lines))
        return

    if text == "⚙️ Bot Sozlamalari":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Start matnini o'zgartirish", callback_data="edit_start")],
            [InlineKeyboardButton("📢 Majburiy kanallar", callback_data="manage_ch")]
        ])
        await update.message.reply_text("⚙️ Bot sozlamalari:", reply_markup=kb)
        await update.message.reply_text("Qaytish:", reply_markup=get_return_main_keyboard())
        return

    await update.message.reply_text(
        "⚠️ Siz adminsiz! Botni tekshirish uchun boshqa akkountdan foydalaning.",
        reply_markup=get_admin_keyboard()
    )

# ==================== CALLBACKS ====================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global movies, channels, catalogs, genres, users, active_users, deleted_users, bot_settings, saved_movies
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "check":
        if await is_joined(context.bot, user_id):
            await query.answer("✅ Obuna tasdiqlandi!")
            await query.message.delete()
            welcome = bot_settings.get("start_text", "").format(name=query.from_user.first_name)
            await context.bot.send_message(chat_id=user_id, text=welcome, reply_markup=get_user_inline_keyboard())
        else:
            await query.answer("❌ Kanallarga hali a'zo bo'lmadingiz!", show_alert=True)
        return

    if data == "go_to_main_menu":
        await query.answer()
        welcome = bot_settings.get("start_text", "").format(name=query.from_user.first_name)
        await context.bot.send_message(chat_id=user_id, text=welcome, reply_markup=get_user_inline_keyboard())
        return

    if data == "my_saved":
        await query.answer()
        uid_str = str(user_id)
        saved = saved_movies.get(uid_str, [])
        valid = [c for c in saved if c in movies]
        if not valid:
            await context.bot.send_message(
                chat_id=user_id,
                text="❤️ Siz hali hech qanday kino saqlamagansiz.\n\nKinoni ko'rayotganda '❤️ Saqlash' tugmasini bosing!"
            )
            return
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❤️ Saqlangan kinolaringiz ({len(valid)} ta):\n\nQuyidagi tugmalardan birini bosing:"
        )
        for code in valid:
            d = movies[code]
            name = d.get("name", code).upper() if isinstance(d, dict) else code.upper()
            desc = d.get("desc", "") if isinstance(d, dict) else ""
            poster = d.get("poster") if isinstance(d, dict) else None
            vc = views.get(code, 0)
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("▶️ Ko'rish", callback_data=f"watch_{code}"),
                InlineKeyboardButton("🗑️ O'chirish", callback_data=f"unsave_{code}")
            ]])
            caption = f"🎬 {name}\n📝 {desc}\n👁 {vc} marta ko'rilgan\n🔑 Kod: {code}"
            try:
                if poster and poster.startswith("http"):
                    await context.bot.send_photo(chat_id=user_id, photo=poster, caption=caption, reply_markup=kb)
                else:
                    await context.bot.send_message(chat_id=user_id, text=caption, reply_markup=kb)
            except Exception:
                await context.bot.send_message(chat_id=user_id, text=caption, reply_markup=kb)
        return

    if data.startswith("watch_"):
        await query.answer()
        movie_code = data.split("_")[1]
        await send_movie(user_id, movie_code, context.bot)
        return

    if data.startswith("unsave_"):
        movie_code = data.split("_")[1]
        uid_str = str(user_id)
        if uid_str in saved_movies and movie_code in saved_movies[uid_str]:
            saved_movies[uid_str].remove(movie_code)
            save_and_push("saved_movies.json", saved_movies, "Saqlanganlardan o'chirildi")
        await query.answer("🗑️ Saqlanganlardan o'chirildi!", show_alert=True)
        await query.message.delete()
        return

    if data.startswith("save_"):
        movie_code = data.split("_")[1]
        uid_str = str(user_id)
        if uid_str not in saved_movies:
            saved_movies[uid_str] = []
        if movie_code not in saved_movies[uid_str]:
            saved_movies[uid_str].append(movie_code)
            save_and_push("saved_movies.json", saved_movies, "Kino saqlandi")
            await query.answer("❤️ Saqlandi!", show_alert=True)
        else:
            await query.answer("✨ Bu kino allaqachon saqlangan!", show_alert=True)
        return

    if data == "user_show_catalogs":
        await query.answer()
        kb = [[InlineKeyboardButton(cat, switch_inline_query_current_chat=f"katalog:{cat}")] for cat in catalogs]
        kb.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="go_to_main_menu")])
        await query.message.edit_text("📂 Kerakli katalogni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "user_show_genres":
        await query.answer()
        kb = [[InlineKeyboardButton(gen, switch_inline_query_current_chat=f"janr:{gen}")] for gen in genres]
        kb.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="go_to_main_menu")])
        await query.message.edit_text("🎭 Kerakli janrni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if not is_admin(user_id): return

    if data == "add_cat":
        await query.answer()
        admin_states[user_id] = "add_custom_catalog"
        await context.bot.send_message(chat_id=user_id, text="➕ Yangi katalog nomini yuboring:", reply_markup=get_cancel_keyboard())
        return

    if data == "add_gen":
        await query.answer()
        admin_states[user_id] = "add_custom_genre"
        await context.bot.send_message(chat_id=user_id, text="➕ Yangi janr nomini yuboring:", reply_markup=get_cancel_keyboard())
        return

    if data == "list_del_cat":
        await query.answer()
        kb = [[InlineKeyboardButton(f"🗑️ {cat}", callback_data=f"del_cat_{i}")] for i, cat in enumerate(catalogs)]
        await query.message.edit_text("🗑️ O'chirmoqchi bo'lgan katalogni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("del_cat_"):
        await query.answer()
        idx = int(data.split("_")[2])
        if 0 <= idx < len(catalogs):
            removed = catalogs.pop(idx)
            save_and_push("catalogs.json", catalogs, f"Katalog o'chirildi: {removed}")
            await context.bot.send_message(chat_id=user_id, text=f"✅ Katalog o'chirildi: {removed}", reply_markup=get_admin_keyboard())
        return

    if data == "list_del_gen":
        await query.answer()
        kb = [[InlineKeyboardButton(f"🗑️ {gen}", callback_data=f"del_gen_{i}")] for i, gen in enumerate(genres)]
        await query.message.edit_text("🗑️ O'chirmoqchi bo'lgan janrni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("del_gen_"):
        await query.answer()
        idx = int(data.split("_")[2])
        if 0 <= idx < len(genres):
            removed = genres.pop(idx)
            save_and_push("genres.json", genres, f"Janr o'chirildi: {removed}")
            await context.bot.send_message(chat_id=user_id, text=f"✅ Janr o'chirildi: {removed}", reply_markup=get_admin_keyboard())
        return

    if data == "edit_start":
        await query.answer()
        admin_states[user_id] = "edit_start_text"
        await context.bot.send_message(
            chat_id=user_id, 
            text=f"Current text:\n\n{bot_settings.get('start_text')}\n\n📝 Yangi start matnini yuboring:", 
            reply_markup=get_cancel_keyboard()
        )
        return

    if data == "manage_ch":
        await query.answer()
        kb = [[InlineKeyboardButton(f"🗑️ {name}", callback_data=f"del_ch_{ch_id}")] for ch_id, name in channels.items()]
        kb.append([InlineKeyboardButton("➕ Kanal qo'shish", callback_data="add_ch_start")])
        await query.message.edit_text("📢 Majburiy obuna kanallari:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "add_ch_start":
        await query.answer()
        admin_states[user_id] = "channel_add"
        await context.bot.send_message(chat_id=user_id, text="📢 Kanalni formatda yuboring:\n`@username Kanal nomi`", reply_markup=get_cancel_keyboard())
        return

    if data.startswith("del_ch_"):
        await query.answer()
        ch_id = data.replace("del_ch_", "")
        if ch_id in channels:
            removed = channels.pop(ch_id)
            save_and_push("channels.json", channels, f"Kanal o'chirildi: {removed}")
            await context.bot.send_message(chat_id=user_id, text=f"✅ Kanal olib tashlandi: {removed}", reply_markup=get_admin_keyboard())
        return

    if data.startswith("wiz_cat_"):
        await query.answer()
        val = data.replace("wiz_cat_", "")
        if val == "done":
            admin_states[user_id] = "add_movie_genre"
            kb = [[InlineKeyboardButton(gen, callback_data=f"wiz_gen_{i}")] for i, gen in enumerate(genres)]
            kb.append([InlineKeyboardButton("💾 Saqlash va Yakunlash", callback_data="wiz_gen_done")])
            await query.message.edit_text("🎭 Janr tanlang (bir nechta bo'lishi mumkin):", reply_markup=InlineKeyboardMarkup(kb))
        else:
            idx = int(val)
            cat_name = catalogs[idx]
            if user_id in new_movie_wizard:
                if cat_name not in new_movie_wizard[user_id]["catalogs"]:
                    new_movie_wizard[user_id]["catalogs"].append(cat_name)
                    await query.answer(f"➕ {cat_name} qo'shildi")
        return

    if data.startswith("wiz_gen_"):
        await query.answer()
        val = data.replace("wiz_gen_", "")
        if val == "done":
            wiz = new_movie_wizard.pop(user_id, None)
            if wiz:
                code = wiz["code"]
                movies[code] = {
                    "name": wiz["name"], "desc": wiz["desc"],
                    "poster": wiz["poster"], "video_id": wiz["video_id"],
                    "catalogs": wiz["catalogs"], "genres": wiz["genres"]
                }
                save_and_push("movies.json", movies, f"Yangi kino qo'shildi: {code}")
                add_log(user_id, f"Kino qo'shildi: {wiz['name']} ({code})")
                admin_states[user_id] = None
                
                # ================= O'ZGARTIRILGAN QISMI =================
                # Avtomatik xabar yuborilmaydi. Admin so'rovnomasi chiqadi:
                kb_confirm = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Ha (Yuborilsin)", callback_data=f"alert_new_{code}")],
                    [InlineKeyboardButton("❌ Yo'q (Shart emas)", callback_data="alert_cancel")]
                ])
                await query.message.edit_text(
                    f"🎉 '{wiz['name']}' kinosi muvaffaqiyatli qo'shildi!\n\n"
                    f"📢 Ushbu yangi kino haqida barcha foydalanuvchilarga xabar berilsinmi?",
                    reply_markup=kb_confirm
                )
                # ========================================================
        else:
            idx = int(val)
            gen_name = genres[idx]
            if user_id in new_movie_wizard:
                if gen_name not in new_movie_wizard[user_id]["genres"]:
                    new_movie_wizard[user_id]["genres"].append(gen_name)
                    await query.answer(f"➕ {gen_name} qo'shildi")
        return

    # ================= YANGI CALLBACK HANDLERLAR =================
    if data.startswith("alert_new_"):
        await query.answer()
        movie_code = data.split("_")[2]
        if movie_code in movies:
            name = movies[movie_code].get("name", movie_code).upper()
            alert_text = f"🎬 Yangi kino qo'shildi!\n\n🍿 Nomi: {name}\n🔑 Kodi: {movie_code}\n\n🤖 Botga kirib kino kodini yuboring va tomosha qiling!"
            
            await query.message.edit_text("🚀 Foydalanuvchilarga xabar yuborilmoqda, kuting...")
            success, fail = 0, 0
            for uid in list(users):
                try:
                    await context.bot.send_message(chat_id=uid, text=alert_text)
                    success += 1
                except Exception:
                    fail += 1
            await context.bot.send_message(
                chat_id=user_id, 
                text=f"📊 Yangilik tarqatildi:\n✅ Yuborildi: {success}\n❌ Muammo: {fail}", 
                reply_markup=get_admin_keyboard()
            )
        return

    if data == "alert_cancel":
        await query.answer("Xabar bekor qilindi")
        await query.message.edit_text("✅ Tushunarli. Foydalanuvchilarga bildirishnoma yuborilmadi.", reply_markup=get_admin_keyboard())
        return
    # ============================================================

    if data == "broadcast_confirm":
        await query.answer()
        text_to_send = context.user_data.get("broadcast_text")
        if text_to_send:
            await query.message.edit_text("🚀 Xabar yuborilmoqda, kuting...")
            success, fail = 0, 0
            for uid in list(users):
                try:
                    await context.bot.send_message(chat_id=uid, text=text_to_send)
                    success += 1
                except Exception:
                    fail += 1
            await context.bot.send_message(chat_id=user_id, text=f"📊 Natija:\n✅ Yuborildi: {success}\n❌ Muammo: {fail}", reply_markup=get_admin_keyboard())
        return

    if data == "cancel_broadcast":
        await query.answer("Bekor qilindi")
        await query.message.delete()
        return

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    pass

def main():
    load_data()
    if not TOKEN: return
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    app.run_polling()

if __name__ == "__main__":
    main()
