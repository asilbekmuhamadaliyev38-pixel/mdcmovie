import os
import base64
import requests
import json
import datetime
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
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
views = {}          
saved_movies = {}   
admin_logs = []

# YANGI: reyting va qism-navigatsiya uchun ma'lumotlar
ratings = {}        # {"movie_code": {"user_id": baho}}
part_progress = {}  # {"user_id_movie_code": current_part_index} - foydalanuvchi qaysi qismda turgani

# YANGI: pending o'zgarishlar to'plami - avto-bekap navbati uchun
_pending_saves = {}      # {filename: (data, message)}
_pending_saves_lock = threading.Lock()

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

# YANGI: navbatga qo'yib saqlash - har safar emas, balki to'plab keyin push qiladi.
# Lokal faylga DARHOL yoziladi (hech narsa yo'qolmaydi), GitHub'ga esa navbat orqali.
def queue_save(filename, data, message):
    write_local(filename, data)
    with _pending_saves_lock:
        _pending_saves[filename] = (data, message)

# YANGI: navbatdagi barcha o'zgarishlarni GitHub'ga push qiladi (avto-bekap tikleri uchun)
def flush_pending_saves():
    with _pending_saves_lock:
        items = list(_pending_saves.items())
        _pending_saves.clear()
    for filename, (data, message) in items:
        github_put(filename, data, message)

# YANGI: avto-bekap - har AUTO_BACKUP_INTERVAL soniyada navbatdagilarni GitHub'ga yuboradi
AUTO_BACKUP_INTERVAL = 60  # soniya

def auto_backup_loop():
    while True:
        threading.Event().wait(AUTO_BACKUP_INTERVAL)
        try:
            flush_pending_saves()
        except Exception:
            pass

# ==================== MA'LUMOT YUKLASH ====================
def load_data():
    global admins, movies, channels, catalogs, genres, users, active_users
    global deleted_users, blocked_users, ad_post_id, bot_settings
    global views, saved_movies, admin_logs, ratings, part_progress

    movies.update(read_file("movies.json", {}))
    channels.update(read_file("channels.json", {}))
    bot_settings.update(read_file("settings.json", bot_settings))
    views.update(read_file("views.json", {}))
    saved_movies_raw = read_file("saved_movies.json", {})
    saved_movies.update({str(k): v for k, v in saved_movies_raw.items()})
    admin_logs_raw = read_file("admin_logs.json", [])
    admin_logs.extend(admin_logs_raw[-200:])

    # YANGI: reyting va qism-progress yuklash
    ratings_raw = read_file("ratings.json", {})
    ratings.update(ratings_raw)
    part_progress_raw = read_file("part_progress.json", {})
    part_progress.update(part_progress_raw)

    # MUAMMO SHU YERDA EDI: Agar Github yoki localda fayl bo'sh bo'lsa ham [] qaytardi,
    # lekin None tekshirilgani uchun doim eski default janrlar qaytib kelaverardi.
    loaded_cats = read_file("catalogs.json", None)
    catalogs.clear()
    if loaded_cats is not None: catalogs.extend(loaded_cats)
    else: catalogs.extend(["🍿 Kinolar", "🎬 Seriallar", "🧸 Multfilmlar"])

    loaded_gnrs = read_file("genres.json", None)
    genres.clear()
    if loaded_gnrs is not None: genres.extend(loaded_gnrs)
    else: genres.extend(["🔥 Jangari", "🤣 Komediya", "😢 Drama", "🚀 Fantastika"])

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

# ==================== YANGI: REYTING FUNKSIYALARI ====================
def set_rating(movie_code, user_id, score):
    if movie_code not in ratings:
        ratings[movie_code] = {}
    ratings[movie_code][str(user_id)] = score
    # Reyting kamdan-kam o'zgaradi (har user bir marta bosadi), shu sababli
    # darhol GitHub'ga yuboramiz - navbatga qoldirmaymiz, restart bo'lsa ham yo'qolmasin.
    save_and_push("ratings.json", ratings, f"Reyting yangilandi: {movie_code}")

def get_avg_rating(movie_code):
    scores = ratings.get(movie_code, {})
    if not scores: return 0.0, 0
    vals = list(scores.values())
    return sum(vals) / len(vals), len(vals)

def get_user_rating(movie_code, user_id):
    return ratings.get(movie_code, {}).get(str(user_id))

def stars_str(avg):
    full = round(avg)
    return "⭐" * full + "☆" * (5 - full) if avg > 0 else "Baholanmagan"

# ==================== YANGI: TOP BAHOLANGANLAR SAHIFALASH ====================
TOP_RATED_PAGE_SIZE = 10

def get_sorted_top_rated():
    scored = []
    for code in movies:
        avg, count = get_avg_rating(code)
        if count > 0:
            scored.append((code, avg, count))
    scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return scored

def build_top_rated_keyboard(scored, page):
    start = page * TOP_RATED_PAGE_SIZE
    end = start + TOP_RATED_PAGE_SIZE
    page_items = scored[start:end]

    kb = []
    row = []
    for offset, (code, avg, count) in enumerate(page_items):
        num = start + offset + 1
        row.append(InlineKeyboardButton(str(num), callback_data=f"toprated_open_{code}"))
        if len(row) == 5:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    nav_row = []
    if start > 0:
        nav_row.append(InlineKeyboardButton("◀️ Oldingi sahifa", callback_data=f"toprated_page_{page-1}"))
    if end < len(scored):
        nav_row.append(InlineKeyboardButton("Keyingi sahifa ▶️", callback_data=f"toprated_page_{page+1}"))
    if nav_row:
        kb.append(nav_row)

    return InlineKeyboardMarkup(kb), page_items, start

async def show_top_rated_page(message, bot, page, edit=False):
    scored = get_sorted_top_rated()
    if not scored:
        text = "⭐ Hali hech qanday kino baholanmagan."
        if edit:
            await message.edit_text(text)
        else:
            await bot.send_message(chat_id=message.chat_id, text=text)
        return

    kb, page_items, start = build_top_rated_keyboard(scored, page)
    lines = []
    for offset, (code, avg, count) in enumerate(page_items):
        num = start + offset + 1
        d = movies[code]
        name = d.get("name", code).upper() if isinstance(d, dict) else code.upper()
        lines.append(f"{num}. {name} — {stars_str(avg)} ({avg:.1f}/5, {count} ovoz)")

    total_pages = (len(scored) - 1) // TOP_RATED_PAGE_SIZE + 1
    cur_page_num = page + 1
    text = f"⭐ Top baholangan kinolar ({cur_page_num}/{total_pages}-sahifa):\n\n" + "\n".join(lines) + "\n\n👇 Kerakli kinoning raqamini bosing:"

    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await bot.send_message(chat_id=message.chat_id, text=text, reply_markup=kb)

# ==================== YANGI: QISMLI KINO YORDAMCHI FUNKSIYALARI ====================
def get_video_ids(data):
    """movie ma'lumotidan video_id ro'yxatini qaytaradi (har doim list)."""
    video_ids_raw = data.get("video_id") if isinstance(data, dict) else data
    if isinstance(video_ids_raw, str):
        return [v.strip() for v in video_ids_raw.split(",") if v.strip()]
    elif isinstance(video_ids_raw, list):
        return video_ids_raw
    return [str(video_ids_raw)]

def is_multi_part(data):
    return len(get_video_ids(data)) > 1

def get_part_progress_key(user_id, movie_code):
    return f"{user_id}_{movie_code}"

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
        ],
        [
            InlineKeyboardButton("🎲 Tasodifiy kino", callback_data="random_movie"),
            InlineKeyboardButton("⭐ Top baholangan", callback_data="top_rated")
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

    # YANGI: agar kino bir nechta qismdan iborat bo'lsa (video_id'da vergul bilan
    # ajratilgan bir nechta ID bo'lsa), uni alohida qism-navigatsiyali rejimda yuboramiz.
    # Eski xulq-atvor (bitta qism bo'lsa) butunlay o'zgarishsiz qoladi.
    if len(video_ids) > 1:
        return await send_movie_part(chat_id, movie_code, 0, bot)

    name = data.get("name", movie_code) if isinstance(data, dict) else movie_code
    protect = False if is_admin(chat_id) else bot_settings.get("protect_content", True)

    movie_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Film qidirish", switch_inline_query_current_chat="")],
        [
            InlineKeyboardButton("❤️ Saqlash", callback_data=f"save_{movie_code}"),
            InlineKeyboardButton("🏠 Bosh menyu", callback_data="go_to_main_menu")
        ],
        [InlineKeyboardButton("⭐ Baholash", callback_data=f"rate_menu_{movie_code}")]
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

# ==================== YANGI: QISMLI KINO YUBORISH ====================
def build_part_nav_keyboard(movie_code, part_index, total_parts):
    """Qism uchun ◀️ Oldingi / Keyingi ▶️ va boshqa tugmalarni quradi."""
    nav_row = []
    if part_index > 0:
        nav_row.append(InlineKeyboardButton("◀️ Oldingi qism", callback_data=f"part_{movie_code}_{part_index-1}"))
    if part_index < total_parts - 1:
        nav_row.append(InlineKeyboardButton("Keyingi qism ▶️", callback_data=f"part_{movie_code}_{part_index+1}"))

    rows = []
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(f"📋 Qismlar ({part_index+1}/{total_parts})", callback_data=f"partlist_{movie_code}")])
    rows.append([
        InlineKeyboardButton("❤️ Saqlash", callback_data=f"save_{movie_code}"),
        InlineKeyboardButton("🏠 Bosh menyu", callback_data="go_to_main_menu")
    ])
    rows.append([InlineKeyboardButton("⭐ Baholash", callback_data=f"rate_menu_{movie_code}")])
    return InlineKeyboardMarkup(rows)

def build_parts_list_keyboard(movie_code, total_parts):
    """Barcha qismlarni raqamlab ko'rsatadigan klaviatura (3 tadan qatorga)."""
    kb = []
    row = []
    for i in range(total_parts):
        row.append(InlineKeyboardButton(str(i + 1), callback_data=f"part_{movie_code}_{i}"))
        if len(row) == 5:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"part_back_{movie_code}")])
    return InlineKeyboardMarkup(kb)

async def send_movie_part(chat_id, movie_code, part_index, bot, edit_message=None):
    """Qismli kinoning faqat bitta qismini, navigatsiya tugmalari bilan yuboradi."""
    if movie_code not in movies: return False
    data = movies[movie_code]
    video_ids = get_video_ids(data)
    total_parts = len(video_ids)

    if part_index < 0 or part_index >= total_parts:
        part_index = 0

    name = data.get("name", movie_code) if isinstance(data, dict) else movie_code
    protect = False if is_admin(chat_id) else bot_settings.get("protect_content", True)
    vid = video_ids[part_index]

    kb = build_part_nav_keyboard(movie_code, part_index, total_parts)

    try:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=SOURCE_CHANNEL,
            message_id=int(vid),
            reply_markup=kb,
            protect_content=protect
        )
    except Exception:
        return False

    # Foydalanuvchining shu kinodagi joriy qismini xotirada va faylda saqlaymiz
    progress_key = get_part_progress_key(chat_id, movie_code)
    part_progress[progress_key] = part_index
    queue_save("part_progress.json", part_progress, "Qism progressi yangilandi")

    if not is_admin(chat_id) and part_index == 0:
        increment_views(movie_code)

    if ad_post_id and not is_admin(chat_id) and part_index == 0:
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=SOURCE_CHANNEL,
                message_id=int(ad_post_id),
                protect_content=True
            )
        except Exception: pass

    return True

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
            if not filter_value or filter_value in movie_cats: match = True
        elif filter_type == "genre":
            if not filter_value or filter_value in movie_gnrs: match = True
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
        
        if not isinstance(data, dict):
            movies[code] = {"name": f"Kino {code}", "desc": "", "poster": "", "video_id": data, "catalogs": [], "genres": []}
            data = movies[code]

        name = data.get("name", code)
        cur_cats = data.get("catalogs", [])
        cur_gnrs = data.get("genres", [])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📛 Nom", callback_data=f"edit_name_{code}"),
             InlineKeyboardButton("📝 Ma'lumot", callback_data=f"edit_desc_{code}")],
            [InlineKeyboardButton("🖼 Poster", callback_data=f"edit_poster_{code}"),
             InlineKeyboardButton("📥 Video ID", callback_data=f"edit_vid_{code}")],
            [InlineKeyboardButton("📂 Kataloglar (Boshqarish)", callback_data=f"edit_cats_{code}")],
            [InlineKeyboardButton("🎭 Janrlar (Boshqarish)", callback_data=f"edit_gnrs_{code}")],
            [InlineKeyboardButton("❌ Chiqish (Tayyor)", callback_data="cancel_edit")]
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
            if not isinstance(movies[code], dict):
                movies[code] = {"name": f"Kino {code}", "desc": "", "poster": "", "video_id": movies[code], "catalogs": [], "genres": []}
            
            if field == "name": movies[code]["name"] = text
            elif field == "desc": movies[code]["desc"] = text
            elif field == "poster": movies[code]["poster"] = text
            elif field == "vid": movies[code]["video_id"] = text
            
            save_and_push("movies.json", movies, f"Kino tahrirlandi: {code}")
            add_log(user_id, f"Kino tahrirlandi: {code} ({field})")
            admin_states[user_id] = None
            await update.message.reply_text(f"✅ Muaffaqiyatli yangilandi!", reply_markup=get_admin_keyboard())
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
        # Eng ko'p ko'rilgan kino
        most_viewed = "Yo'q"
        if views:
            top_code = max(views, key=views.get)
            top_name = movies.get(top_code, {}).get("name", top_code) if isinstance(movies.get(top_code), dict) else top_code
            most_viewed = f"{top_name} ({views[top_code]} marta)"

        # Eng ko'p saqlangan kino
        save_counts = {}
        for uid_str, codes in saved_movies.items():
            for c in codes:
                save_counts[c] = save_counts.get(c, 0) + 1
        most_saved = "Yo'q"
        if save_counts:
            top_save_code = max(save_counts, key=save_counts.get)
            top_save_name = movies.get(top_save_code, {}).get("name", top_save_code) if isinstance(movies.get(top_save_code), dict) else top_save_code
            most_saved = f"{top_save_name} ({save_counts[top_save_code]} marta)"

        # Eng yuqori reytingli kino
        best_rated = "Yo'q"
        best_avg, best_count = 0, 0
        best_code = None
        for code in movies:
            avg, count = get_avg_rating(code)
            if count > 0 and avg > best_avg:
                best_avg, best_count, best_code = avg, count, code
        if best_code:
            bname = movies.get(best_code, {}).get("name", best_code) if isinstance(movies.get(best_code), dict) else best_code
            best_rated = f"{bname} ({best_avg:.1f}⭐, {best_count} ovoz)"

        # Bugun qo'shilgan ro'yxat (oxirgi loglardan)
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        today_actions = len([l for l in admin_logs if l.get("time", "").startswith(today_str)])

        await update.message.reply_text(
            f"📊 Statistika:\n\n"
            f"👥 Jami foydalanuvchi: {len(users)}\n"
            f"✅ Faol: {len(active_users)}\n"
            f"❌ Bloklagan (botni o'chirgan): {len(deleted_users)}\n"
            f"🚫 Botda bloklangan: {len(blocked_users)}\n"
            f"🎬 Jami kinolar: {len(movies)}\n"
            f"👁 Jami ko'rishlar: {sum(views.values())}\n\n"
            f"🔥 Eng ko'p ko'rilgan: {most_viewed}\n"
            f"❤️ Eng ko'p saqlangan: {most_saved}\n"
            f"⭐ Eng yuqori baholangan: {best_rated}\n\n"
            f"📝 Bugungi admin amallari: {today_actions}"
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
        await update.message.reply_text("⚙️ Bot sozalamalari:", reply_markup=kb)
        await update.message.reply_text("Qaytish:", reply_markup=get_return_main_keyboard())
        return

    await update.message.reply_text(
        "⚠️ Siz adminsiz! Botni tekshirish uchun boshqa akkountdan foydalaning.",
        reply_markup=get_admin_keyboard()
    )

# ==================== CALLBACKS ====================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global movies, channels, catalogs, genres, users, active_users, deleted_users, bot_settings, saved_movies, ratings
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    # ==================== YANGI: TASODIFIY KINO ====================
    if data == "random_movie":
        await query.answer()
        if not movies:
            await context.bot.send_message(chat_id=user_id, text="🎬 Hozircha bazada kino yo'q.")
            return
        import random
        movie_code = random.choice(list(movies.keys()))
        await send_movie(user_id, movie_code, context.bot)
        return

    # ==================== YANGI: TOP BAHOLANGAN KINOLAR (sahifalash bilan) ====================
    if data == "top_rated" or data.startswith("toprated_page_"):
        await query.answer()
        page = 0
        if data.startswith("toprated_page_"):
            page = int(data.replace("toprated_page_", ""))
        await show_top_rated_page(query.message, context.bot, page, edit=data.startswith("toprated_page_"))
        return

    if data.startswith("toprated_open_"):
        await query.answer()
        movie_code = data.replace("toprated_open_", "")
        await send_movie(user_id, movie_code, context.bot)
        return

    # ==================== YANGI: BAHOLASH MENYUSI ====================
    if data.startswith("rate_menu_"):
        await query.answer()
        movie_code = data.replace("rate_menu_", "")
        avg, count = get_avg_rating(movie_code)
        user_score = get_user_rating(movie_code, user_id)
        kb_rows = []
        for i in range(1, 6):
            mark = "✅ " if user_score == i else ""
            label = f"{mark}{i} {'⭐' * i}"
            kb_rows.append([InlineKeyboardButton(label, callback_data=f"rate_{movie_code}_{i}")])
        kb = InlineKeyboardMarkup(kb_rows)
        info = f"{stars_str(avg)} ({avg:.1f}/5, {count} ovoz)" if count else "Hali baholanmagan"
        await context.bot.send_message(
            chat_id=user_id,
            text=f"⭐ Ushbu kinoga baho bering:\n\nHozirgi reyting: {info}",
            reply_markup=kb
        )
        return

    if data.startswith("rate_") and not data.startswith("rate_menu_"):
        await query.answer()
        rest = data[len("rate_"):]
        movie_code, _, score_str = rest.rpartition("_")
        score = int(score_str)
        set_rating(movie_code, user_id, score)
        avg, count = get_avg_rating(movie_code)
        await query.answer(f"✅ Siz {score} ⭐ baho berdingiz! O'rtacha: {avg:.1f}/5", show_alert=True)
        return

    # ==================== YANGI: QISMLI KINO NAVIGATSIYASI ====================
    if data.startswith("part_") and not data.startswith("part_back_") and not data.startswith("partlist_"):
        await query.answer()
        # rsplit ishlatamiz, chunki kino kodining o'zida "_" bo'lishi mumkin
        rest = data[len("part_"):]
        movie_code, _, idx_str = rest.rpartition("_")
        part_index = int(idx_str)
        await send_movie_part(user_id, movie_code, part_index, context.bot)
        return

    if data.startswith("partlist_"):
        await query.answer()
        movie_code = data.replace("partlist_", "")
        if movie_code in movies:
            total_parts = len(get_video_ids(movies[movie_code]))
            kb = build_parts_list_keyboard(movie_code, total_parts)
            try:
                await query.message.edit_reply_markup(reply_markup=kb)
            except Exception:
                pass
        return

    if data.startswith("part_back_"):
        await query.answer()
        movie_code = data.replace("part_back_", "")
        progress_key = get_part_progress_key(user_id, movie_code)
        current = part_progress.get(progress_key, 0)
        if movie_code in movies:
            total_parts = len(get_video_ids(movies[movie_code]))
            kb = build_part_nav_keyboard(movie_code, current, total_parts)
            try:
                await query.message.edit_reply_markup(reply_markup=kb)
            except Exception:
                pass
        return

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

    # O'G'IL BOLLAR UCHUN KATALOG VA JANRNI 2 QATOR (YONMA-YON) QILISH
    if data == "user_show_catalogs":
        await query.answer()
        kb = []
        for i in range(0, len(catalogs), 2):
            row = [InlineKeyboardButton(catalogs[i], switch_inline_query_current_chat=f"katalog:{catalogs[i]}")]
            if i + 1 < len(catalogs):
                row.append(InlineKeyboardButton(catalogs[i+1], switch_inline_query_current_chat=f"katalog:{catalogs[i+1]}"))
            kb.append(row)
        kb.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="go_to_main_menu")])
        await query.message.edit_text("📂 Kerakli katalogni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "user_show_genres":
        await query.answer()
        kb = []
        for i in range(0, len(genres), 2):
            row = [InlineKeyboardButton(genres[i], switch_inline_query_current_chat=f"janr:{genres[i]}")]
            if i + 1 < len(genres):
                row.append(InlineKeyboardButton(genres[i+1], switch_inline_query_current_chat=f"janr:{genres[i+1]}"))
            kb.append(row)
        kb.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="go_to_main_menu")])
        await query.message.edit_text("🎭 Kerakli janrni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if not is_admin(user_id): return

    # TAHRIRLASH INLINE HANDLING
    if data.startswith("edit_name_") or data.startswith("edit_desc_") or data.startswith("edit_poster_") or data.startswith("edit_vid_"):
        await query.answer()
        parts = data.split("_", 2)
        field = parts[1]
        code = parts[2]
        admin_states[user_id] = f"edit_field_{field}_{code}"
        await context.bot.send_message(chat_id=user_id, text=f"📝 Yangi qiymatni kiriting:", reply_markup=get_cancel_keyboard())
        return

    # KINO KATALOGLARINI TAHRIRLASH (PTICHKA BILAN)
    if data.startswith("edit_cats_"):
        await query.answer()
        code = data.split("_")[2]
        if code in movies and not isinstance(movies[code], dict):
            movies[code] = {"name": f"Kino {code}", "desc": "", "poster": "", "video_id": movies[code], "catalogs": [], "genres": []}
        
        movie_cats = movies[code].get("catalogs", []) if code in movies else []
        
        kb = []
        for i, cat in enumerate(catalogs):
            status = "✅ " if cat in movie_cats else ""
            kb.append([InlineKeyboardButton(f"{status}{cat}", callback_data=f"tgl_cat_{code}_{i}")])
        kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"edit_back_{code}")])
        await query.message.edit_text("📂 Kataloglarni boshqarish (Qo'shish/O'chirish uchun bosing):", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("tgl_cat_"):
        parts = data.split("_")
        code = parts[2]
        idx = int(parts[3])
        cat_name = catalogs[idx]
        if code in movies:
            if "catalogs" not in movies[code]: movies[code]["catalogs"] = []
            if cat_name in movies[code]["catalogs"]:
                movies[code]["catalogs"].remove(cat_name)
                await query.answer(f"❌ {cat_name} olib tashlandi")
            else:
                movies[code]["catalogs"].append(cat_name)
                await query.answer(f"✅ {cat_name} biriktirildi")
            save_and_push("movies.json", movies, f"Katalog tahrirlandi: {code}")
            
            # Inline tugmalarni srazi yangilash
            movie_cats = movies[code].get("catalogs", [])
            kb = []
            for i, cat in enumerate(catalogs):
                status = "✅ " if cat in movie_cats else ""
                kb.append([InlineKeyboardButton(f"{status}{cat}", callback_data=f"tgl_cat_{code}_{i}")])
            kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"edit_back_{code}")])
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
        return

    # KINO JANRLARINI TAHRIRLASH (PTICHKA BILAN)
    if data.startswith("edit_gnrs_"):
        await query.answer()
        code = data.split("_")[2]
        if code in movies and not isinstance(movies[code], dict):
            movies[code] = {"name": f"Kino {code}", "desc": "", "poster": "", "video_id": movies[code], "catalogs": [], "genres": []}
            
        movie_gnrs = movies[code].get("genres", []) if code in movies else []
        
        kb = []
        for i, gen in enumerate(genres):
            status = "✅ " if gen in movie_gnrs else ""
            kb.append([InlineKeyboardButton(f"{status}{gen}", callback_data=f"tgl_gen_{code}_{i}")])
        kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"edit_back_{code}")])
        await query.message.edit_text("🎭 Janrlarni boshqarish (Qo'shish/O'chirish uchun bosing):", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("tgl_gen_"):
        parts = data.split("_")
        code = parts[2]
        idx = int(parts[3])
        gen_name = genres[idx]
        if code in movies:
            if "genres" not in movies[code]: movies[code]["genres"] = []
            if gen_name in movies[code]["genres"]:
                movies[code]["genres"].remove(gen_name)
                await query.answer(f"❌ {gen_name} olib tashlandi")
            else:
                movies[code]["genres"].append(gen_name)
                await query.answer(f"✅ {gen_name} biriktirildi")
            save_and_push("movies.json", movies, f"Janr tahrirlandi: {code}")
            
            # Inline tugmalarni srazi yangilash
            movie_gnrs = movies[code].get("genres", [])
            kb = []
            for i, gen in enumerate(genres):
                status = "✅ " if gen in movie_gnrs else ""
                kb.append([InlineKeyboardButton(f"{status}{gen}", callback_data=f"tgl_gen_{code}_{i}")])
            kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"edit_back_{code}")])
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("edit_back_"):
        await query.answer()
        code = data.split("_")[2]
        data_m = movies[code]
        name = data_m.get("name", code)
        cur_cats = data_m.get("catalogs", [])
        cur_gnrs = data_m.get("genres", [])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📛 Nom", callback_data=f"edit_name_{code}"),
             InlineKeyboardButton("📝 Ma'lumot", callback_data=f"edit_desc_{code}")],
            [InlineKeyboardButton("🖼 Poster", callback_data=f"edit_poster_{code}"),
             InlineKeyboardButton("📥 Video ID", callback_data=f"edit_vid_{code}")],
            [InlineKeyboardButton("📂 Kataloglar (Boshqarish)", callback_data=f"edit_cats_{code}")],
            [InlineKeyboardButton("🎭 Janrlar (Boshqarish)", callback_data=f"edit_gnrs_{code}")],
            [InlineKeyboardButton("❌ Chiqish (Tayyor)", callback_data="cancel_edit")]
        ])
        cats_str = ", ".join(cur_cats) if cur_cats else "Yo'q"
        gnrs_str = ", ".join(cur_gnrs) if cur_gnrs else "Yo'q"
        await query.message.edit_text(
            f"✏️ '{name}' — nimani tahrirlaysiz?\n\n📂 Katalog: {cats_str}\n🎭 Janr: {gnrs_str}",
            reply_markup=kb
        )
        return

    if data == "cancel_edit":
        await query.answer()
        await query.message.edit_text("✅ Tahrirlash tugatildi va barcha o'zgarishlar saqlandi.", reply_markup=None)
        await context.bot.send_message(chat_id=user_id, text="Asosiy panel:", reply_markup=get_admin_keyboard())
        return

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
                
                kb_confirm = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Ha (Yuborilsin)", callback_data=f"alert_new_{code}")],
                    [InlineKeyboardButton("❌ Yo'q (Shart emas)", callback_data="alert_cancel")]
                ])
                await query.message.edit_text(
                    f"🎉 '{wiz['name']}' kinosi muvaffaqiyatli qo'shildi!\n\n"
                    f"📢 Ushbu yangi kino haqica barcha foydalanuvchilarga xabar berilsinmi?",
                    reply_markup=kb_confirm
                )
        else:
            idx = int(val)
            gen_name = genres[idx]
            if user_id in new_movie_wizard:
                if gen_name not in new_movie_wizard[user_id]["genres"]:
                    new_movie_wizard[user_id]["genres"].append(gen_name)
                    await query.answer(f"➕ {gen_name} qo'shildi")
        return

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

# Render port so'ragani uchun soxta veb-server
def run_fake_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()

# YANGI: keep-alive - bot "uxlab qolib" RAM tozalanishining oldini olish uchun
# o'zini har 4 daqiqada bir marta so'rab turadi (Render kabi bepul hostinglar
# bir necha daqiqa harakatsizlikdan keyin botni to'xtatib qo'yadi).
def keep_alive_loop():
    if not RENDER_EXTERNAL_URL:
        return
    while True:
        threading.Event().wait(240)
        try:
            requests.get(RENDER_EXTERNAL_URL, timeout=10)
        except Exception:
            pass

def main():
    load_data()
    if not TOKEN: return
    
    # Soxta serverni alohida oqimda ishga tushirish
    threading.Thread(target=run_fake_server, daemon=True).start()

    # YANGI: avto-bekap oqimi - navbatdagi o'zgarishlarni har 60 soniyada GitHub'ga yuboradi
    threading.Thread(target=auto_backup_loop, daemon=True).start()

    # YANGI: keep-alive oqimi - botni "uxlab qolishdan" saqlaydi
    threading.Thread(target=keep_alive_loop, daemon=True).start()
    
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    app.run_polling()

if __name__ == "__main__":
    main()
