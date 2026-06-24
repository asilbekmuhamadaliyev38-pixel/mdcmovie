import os
import base64
import requests
import json
import datetime
import threading
import random
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
admin_states = {}
new_movie_wizard = {}
ad_post_id = None
views = {}          
saved_movies = {}   

ratings = {}        
part_progress = {}  

_pending_saves = {}      
_pending_saves_lock = threading.Lock()

bot_settings = {
    "protect_content": True,
    "start_text": (
        "👋 Assalomu alaykum {name}, botimizga xush kelibsiz\n\n"
        "🎥 Bot orqali siz sevimli filmlar, seriallar va multfilmlarni sifatli formatda ko'rishingiz mumkin\n\n"
        "🚀 Shunchaki:\n"
        "— Kino yoki serialning kodini yuboring\n"
        "— Pastdagi bo'limlardan birini tanlang va zavqlaning! 😉"
    ),
    "start_media_type": "text", # text, photo, animation
    "start_media_id": None
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

def queue_save(filename, data, message):
    write_local(filename, data)
    with _pending_saves_lock:
        _pending_saves[filename] = (data, message)

def flush_pending_saves():
    with _pending_saves_lock:
        items = list(_pending_saves.items())
        _pending_saves.clear()
    for filename, (data, message) in items:
        github_put(filename, data, message)

AUTO_BACKUP_INTERVAL = 60  

def auto_backup_loop():
    while True:
        threading.Event().wait(AUTO_BACKUP_INTERVAL)
        try:
            flush_pending_saves()
        except Exception: pass

# ==================== MA'LUMOT YUKLASH ====================
def load_data():
    global admins, movies, channels, catalogs, genres, users, active_users
    global deleted_users, ad_post_id, bot_settings, views, saved_movies, ratings, part_progress

    movies.update(read_file("movies.json", {}))
    channels.update(read_file("channels.json", {}))
    bot_settings.update(read_file("settings.json", bot_settings))
    views.update(read_file("views.json", {}))
    saved_movies_raw = read_file("saved_movies.json", {})
    saved_movies.update({str(k): v for k, v in saved_movies_raw.items()})

    ratings.update(read_file("ratings.json", {}))
    part_progress.update(read_file("part_progress.json", {}))

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

    ad = read_file("ad_post.json", {"id": None})
    ad_post_id = ad.get("id") if isinstance(ad, dict) else None

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

# ==================== REYTING FUNKSIYALARI ====================
def set_rating(movie_code, user_id, score):
    if movie_code not in ratings:
        ratings[movie_code] = {}
    ratings[movie_code][str(user_id)] = score
    save_and_push("ratings.json", ratings, f"Reyting yangilandi: {movie_code}")

def get_avg_rating(movie_code):
    scores = ratings.get(movie_code, {})
    if not scores: return 0.0, 0
    vals = list(scores.values())
    return sum(vals) / len(vals), len(vals)

def get_user_rating(movie_code, user_id):
    return ratings.get(movie_code, {}).get(str(user_id))

# ==================== TOP BAHOLANGANLAR SAHIFALASH (LIMIT 50) ====================
TOP_RATED_PAGE_SIZE = 10
TOP_RATED_LIMIT = 50  

def get_sorted_top_rated():
    scored = []
    for code in movies:
        avg, count = get_avg_rating(code)
        if count > 0:
            scored.append((code, avg, count))
    scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return scored[:TOP_RATED_LIMIT]  

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
    if row: kb.append(row)

    nav_row = []
    if start > 0:
        nav_row.append(InlineKeyboardButton("◀️ Oldingi", callback_data=f"toprated_page_{page-1}"))
    if end < len(scored):
        nav_row.append(InlineKeyboardButton("Keyingi ▶️", callback_data=f"toprated_page_{page+1}"))
    if nav_row: kb.append(nav_row)
        
    kb.append([InlineKeyboardButton("🏠 Bosh menyu", callback_data="go_to_main_menu")])
    return InlineKeyboardMarkup(kb), page_items, start

async def show_top_rated_page(message, bot, page, edit=False):
    scored = get_sorted_top_rated()
    if not scored:
        text = "⭐ Hali hech qanday kino baholanmagan."
        if edit: await message.edit_text(text)
        else: await bot.send_message(chat_id=message.chat_id, text=text)
        return

    kb, page_items, start = build_top_rated_keyboard(scored, page)
    lines = []
    for offset, (code, avg, count) in enumerate(page_items):
        num = start + offset + 1
        d = movies[code]
        name = d.get("name", code).upper() if isinstance(d, dict) else code.upper()
        # YANGI: Emoji olib tashlandi, so'ralgan formatga keltirildi
        lines.append(f"{num}. {name} {avg:.1f}/5 ({count}ta ovoz)")

    total_pages = (len(scored) - 1) // TOP_RATED_PAGE_SIZE + 1
    text = f"⭐ Top baholangan kinolar ({page + 1}/{total_pages}-sahifa):\n\n" + "\n".join(lines) + "\n\n👇 Kerakli raqamni bosing:"

    if edit: await message.edit_text(text, reply_markup=kb)
    else: await bot.send_message(chat_id=message.chat_id, text=text, reply_markup=kb)

# ==================== SAQLANGANLARNI REYTINGDEK SAHIFALASH ====================
SAVED_PAGE_SIZE = 10

def build_saved_keyboard(valid_codes, page):
    start = page * SAVED_PAGE_SIZE
    end = start + SAVED_PAGE_SIZE
    page_items = valid_codes[start:end]

    kb = []
    row = []
    for offset, code in enumerate(page_items):
        num = start + offset + 1
        row.append(InlineKeyboardButton(str(num), callback_data=f"saved_open_{code}_{page}"))
        if len(row) == 5:
            kb.append(row)
            row = []
    if row: kb.append(row)

    nav_row = []
    if start > 0:
        nav_row.append(InlineKeyboardButton("◀️ Oldingi", callback_data=f"saved_page_{page-1}"))
    if end < len(valid_codes):
        nav_row.append(InlineKeyboardButton("Keyingi ▶️", callback_data=f"saved_page_{page+1}"))
    if nav_row: kb.append(nav_row)

    kb.append([InlineKeyboardButton("🏠 Bosh menyu", callback_data="go_to_main_menu")])
    return InlineKeyboardMarkup(kb), page_items, start

async def show_saved_page(chat_id, bot, page, message_to_edit=None):
    uid_str = str(chat_id)
    saved = saved_movies.get(uid_str, [])
    valid = [c for c in saved if c in movies]

    if not valid:
        text = "❤️ Siz hali hech qanday kino saqlamagansiz.\n\nKinoni tomosha qilayotganda '❤️ Saqlash' tugmasini bosing!"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Bosh menyu", callback_data="go_to_main_menu")]])
        if message_to_edit: await message_to_edit.edit_text(text, reply_markup=kb)
        else: await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
        return

    kb, page_items, start = build_saved_keyboard(valid, page)
    lines = []
    for offset, code in enumerate(page_items):
        num = start + offset + 1
        d = movies[code]
        name = d.get("name", code).upper() if isinstance(d, dict) else code.upper()
        lines.append(f"{num}. {name} (Kod: {code})")

    total_pages = (len(valid) - 1) // SAVED_PAGE_SIZE + 1
    text = f"❤️ Saqlangan kinolaringiz ({page + 1}/{total_pages}-sahifa):\n\n" + "\n".join(lines) + "\n\n👇 Kerakli raqamni bosing:"

    if message_to_edit: await message_to_edit.edit_text(text, reply_markup=kb)
    else: await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)

# ==================== QISMLI KINO FUNKSIYALARI ====================
def get_video_ids(data):
    video_ids_raw = data.get("video_id") if isinstance(data, dict) else data
    if isinstance(video_ids_raw, str):
        return [v.strip() for v in video_ids_raw.split(",") if v.strip()]
    elif isinstance(video_ids_raw, list):
        return video_ids_raw
    return [str(video_ids_raw)]

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
            InlineKeyboardButton("❤️ Saqlanganlar", callback_data="my_saved_page_0")
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
        ["📣 Hammaga xabar", "👥 Adminlarni boshqarish"],
        ["⚙️ Bot Sozlamalari"]
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

# ==================== START MATNINI YUBORISH ====================
async def send_welcome_message(chat_id, first_name, bot):
    welcome_text = bot_settings.get("start_text", "").format(name=first_name)
    m_type = bot_settings.get("start_media_type", "text")
    m_id = bot_settings.get("start_media_id")
    kb = get_user_inline_keyboard()

    try:
        if m_type == "photo" and m_id:
            await bot.send_photo(chat_id=chat_id, photo=m_id, caption=welcome_text, reply_markup=kb)
        elif m_type == "animation" and m_id:
            await bot.send_animation(chat_id=chat_id, animation=m_id, caption=welcome_text, reply_markup=kb)
        else:
            await bot.send_message(chat_id=chat_id, text=welcome_text, reply_markup=kb)
    except Exception:
        await bot.send_message(chat_id=chat_id, text=welcome_text, reply_markup=kb)

# ==================== KINO YUBORISH ====================
async def send_movie(chat_id, movie_code, bot, back_page=None):
    global ad_post_id, bot_settings
    if movie_code not in movies: return False
    data = movies[movie_code]

    video_ids = get_video_ids(data)
    if len(video_ids) > 1:
        return await send_movie_part(chat_id, movie_code, 0, bot, back_page)

    protect = False if is_admin(chat_id) else bot_settings.get("protect_content", True)

    btn_row = [
        InlineKeyboardButton("❤️ Saqlash", callback_data=f"save_{movie_code}"),
        InlineKeyboardButton("⭐ Baholash", callback_data=f"rate_menu_{movie_code}")
    ]
    
    kb_list = [
        [InlineKeyboardButton("🔍 Film qidirish", switch_inline_query_current_chat="")],
        btn_row
    ]
    
    if back_page is not None:
        kb_list.append([InlineKeyboardButton("❤️ Saqlanganlarga qaytish", callback_data=f"my_saved_page_{back_page}")])
    else:
        kb_list.append([InlineKeyboardButton("🏠 Bosh menyu", callback_data="go_to_main_menu")])

    movie_kb = InlineKeyboardMarkup(kb_list)

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

    if not is_admin(chat_id): increment_views(movie_code)

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

# ==================== QISMLI KINO YUBORISH ====================
def build_part_nav_keyboard(movie_code, part_index, total_parts, back_page=None):
    nav_row = []
    if part_index > 0:
        nav_row.append(InlineKeyboardButton("◀️ Oldingi qism", callback_data=f"part_{movie_code}_{part_index-1}" + (f"_{back_page}" if back_page is not None else "")))
    if part_index < total_parts - 1:
        nav_row.append(InlineKeyboardButton("Keyingi qism ▶️", callback_data=f"part_{movie_code}_{part_index+1}" + (f"_{back_page}" if back_page is not None else "")))

    rows = []
    if nav_row: rows.append(nav_row)
    rows.append([InlineKeyboardButton(f"📋 Qismlar ({part_index+1}/{total_parts})", callback_data=f"partlist_{movie_code}" + (f"_{back_page}" if back_page is not None else ""))])
    rows.append([
        InlineKeyboardButton("❤️ Saqlash", callback_data=f"save_{movie_code}"),
        InlineKeyboardButton("⭐ Baholash", callback_data=f"rate_menu_{movie_code}")
    ])
    if back_page is not None:
        rows.append([InlineKeyboardButton("❤️ Saqlanganlarga qaytish", callback_data=f"my_saved_page_{back_page}")])
    else:
        rows.append([InlineKeyboardButton("🏠 Bosh menyu", callback_data="go_to_main_menu")])
    return InlineKeyboardMarkup(rows)

def build_parts_list_keyboard(movie_code, total_parts, back_page=None):
    kb = []
    row = []
    p_str = f"_{back_page}" if back_page is not None else ""
    for i in range(total_parts):
        row.append(InlineKeyboardButton(str(i + 1), callback_data=f"part_{movie_code}_{i}{p_str}"))
        if len(row) == 5:
            kb.append(row)
            row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"part_back_{movie_code}{p_str}")])
    return InlineKeyboardMarkup(kb)

async def send_movie_part(chat_id, movie_code, part_index, bot, back_page=None):
    if movie_code not in movies: return False
    data = movies[movie_code]
    video_ids = get_video_ids(data)
    total_parts = len(video_ids)

    if part_index < 0 or part_index >= total_parts: part_index = 0

    protect = False if is_admin(chat_id) else bot_settings.get("protect_content", True)
    vid = video_ids[part_index]
    kb = build_part_nav_keyboard(movie_code, part_index, total_parts, back_page)

    try:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=SOURCE_CHANNEL,
            message_id=int(vid),
            reply_markup=kb,
            protect_content=protect
        )
    except Exception: return False

    progress_key = get_part_progress_key(chat_id, movie_code)
    part_progress[progress_key] = part_index
    queue_save("part_progress.json", part_progress, "Qism progressi yangilandi")

    if not is_admin(chat_id) and part_index == 0: increment_views(movie_code)

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

    await send_welcome_message(user_id, update.effective_user.first_name, context.bot)

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
        elif filter_type == "top": match = True
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

# ==================== MATN VA MULTIMEDIA XABARLARI ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ad_post_id, bot_settings, catalogs, genres, movies, admins
    user_id = update.effective_user.id
    
    # YANGI: Start matniga rasm/gif qo'shish jarayoni uchun matn va media tekshiruvi
    state = admin_states.get(user_id)
    text = update.message.text.strip() if update.message.text else ""

    if text in ["❌ Bekor qilish", "🏠 Asosiy panelga qaytish"]:
        admin_states[user_id] = None
        new_movie_wizard.pop(user_id, None)
        if is_admin(user_id):
            await update.message.reply_text("🏠 Admin paneli:", reply_markup=get_admin_keyboard())
        else:
            await send_welcome_message(user_id, update.effective_user.first_name, context.bot)
        return

    if not is_admin(user_id):
        if not await is_joined(context.bot, user_id):
            await update.message.reply_text("❗ Avval kanallarga obuna bo'ling!", reply_markup=await get_subscription_keyboard(context.bot))
            return
        if text and await send_movie(update.effective_chat.id, text, context.bot): return
        await update.message.reply_text("❌ Bunday kodli kino topilmadi.")
        return

    # YANGI: Rasmli/Gifli start matnini o'rnatish tekshiruvi
    if state == "edit_start_text":
        if update.message.photo:
            bot_settings["start_media_type"] = "photo"
            bot_settings["start_media_id"] = update.message.photo[-1].file_id
            bot_settings["start_text"] = update.message.caption if update.message.caption else ""
        elif update.message.animation:
            bot_settings["start_media_type"] = "animation"
            bot_settings["start_media_id"] = update.message.animation.file_id
            bot_settings["start_text"] = update.message.caption if update.message.caption else ""
        else:
            bot_settings["start_media_type"] = "text"
            bot_settings["start_media_id"] = None
            bot_settings["start_text"] = text

        save_and_push("settings.json", bot_settings, "Start xabari yangilandi")
        admin_states[user_id] = None
        await update.message.reply_text("✅ Start xabari muvaffaqiyatli yangilandi!", reply_markup=get_admin_keyboard())
        return

    if state == "add_movie_text" and text:
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
        await update.message.reply_text("🗂 Katalog tanlang (bir nechta bo'lishi mumkin):", reply_markup=InlineKeyboardMarkup(kb))
        await update.message.reply_text("Bekor qilish:", reply_markup=get_return_main_keyboard())
        return

    if state == "delete_movie_by_code" and text:
        code = text.lower()
        if code in movies:
            name = movies[code].get("name", code) if isinstance(movies[code], dict) else code
            del movies[code]
            views.pop(code, None)
            save_and_push("movies.json", movies, f"Kino o'chirildi: {code}")
            save_and_push("views.json", views, "Ko'rishlar yangilandi")
            admin_states[user_id] = None
            await update.message.reply_text(f"✅ '{name}' kinosi o'chirildi!", reply_markup=get_admin_keyboard())
        else:
            await update.message.reply_text("❌ Bunday kodli kino topilmadi:", reply_markup=get_cancel_keyboard())
        return

    if state == "edit_movie_select" and text:
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
        await update.message.reply_text(
            f"✏️ '{name}' — nimani tahrirlaysiz?\n\n📂 Katalog: {', '.join(cur_cats)}\n🎭 Janr: {', '.join(cur_gnrs)}",
            reply_markup=kb
        )
        return

    if state and state.startswith("edit_field_") and text:
        parts = state.split("_", 3)
        field, code = parts[2], parts[3]
        if code in movies:
            if not isinstance(movies[code], dict):
                movies[code] = {"name": f"Kino {code}", "desc": "", "poster": "", "video_id": movies[code], "catalogs": [], "genres": []}
            if field == "name": movies[code]["name"] = text
            elif field == "desc": movies[code]["desc"] = text
            elif field == "poster": movies[code]["poster"] = text
            elif field == "vid": movies[code]["video_id"] = text
            
            save_and_push("movies.json", movies, f"Kino tahrirlandi: {code}")
            admin_states[user_id] = None
            await update.message.reply_text(f"✅ Muaffaqiyatli yangilandi!", reply_markup=get_admin_keyboard())
        return

    if state == "add_custom_catalog" and text:
        if text not in catalogs:
            catalogs.append(text)
            save_and_push("catalogs.json", catalogs, "Katalog qo'shildi")
        admin_states[user_id] = None
        await update.message.reply_text(f"✅ Katalog qo'shildi: {text}", reply_markup=get_admin_keyboard())
        return

    if state == "add_custom_genre" and text:
        if text not in genres:
            genres.append(text)
            save_and_push("genres.json", genres, "Janr qo'shildi")
        admin_states[user_id] = None
        await update.message.reply_text(f"✅ Janr qo'shildi: {text}", reply_markup=get_admin_keyboard())
        return

    if state == "channel_add" and text:
        parts = text.split(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Format: `@username Kanal nomi` yoki `-1001234567890 Kanal nomi`", reply_markup=get_cancel_keyboard())
            return
        channels[parts[0].strip()] = parts[1].strip()
        save_and_push("channels.json", channels, "Kanal qo'shildi")
        admin_states[user_id] = None
        await update.message.reply_text("✅ Kanal qo'shildi!", reply_markup=get_admin_keyboard())
        return

    if state == "channel_del_text" and text:
        ch_id = text.strip()
        if ch_id in channels:
            removed = channels.pop(ch_id)
            save_and_push("channels.json", channels, f"Kanal o'chirildi: {removed}")
            admin_states[user_id] = None
            await update.message.reply_text(f"✅ Kanal olib tashlandi: {removed}", reply_markup=get_admin_keyboard())
        else:
            await update.message.reply_text("❌ Bunday ID'li kanal majburiy ro'yxatda topilmadi. Qayta yuboring:")
        return

    # YANGI: Admin qo'shish va o'chirish matnli holatlari
    if state == "add_admin_state" and text:
        if not text.isdigit():
            await update.message.reply_text("❌ Faqat ID raqam yuboring:")
            return
        new_adm = int(text)
        admins.add(new_adm)
        save_and_push("admins.json", list(admins), "Yangi admin qo'shildi")
        admin_states[user_id] = None
        await update.message.reply_text(f"✅ {new_adm} admin qilib qo'shildi!", reply_markup=get_admin_keyboard())
        return

    if state == "del_admin_state" and text:
        if not text.isdigit():
            await update.message.reply_text("❌ Faqat ID raqam yuboring:")
            return
        target_adm = int(text)
        if target_adm == ADMIN_ID:
            await update.message.reply_text("❌ Asosiy adminni o'chirish mumkin emas!")
            return
        if target_adm in admins:
            admins.discard(target_adm)
            save_and_push("admins.json", list(admins), "Admin o'chirildi")
            admin_states[user_id] = None
            await update.message.reply_text(f"✅ Admin {target_adm} o'chirildi!", reply_markup=get_admin_keyboard())
        else:
            await update.message.reply_text("❌ Bunday admin topilmadi.")
        return

    if state == "broadcast" and text:
        context.user_data["broadcast_text"] = text
        admin_states[user_id] = None
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yuborish", callback_data="broadcast_confirm"),
            InlineKeyboardButton("❌ Bekor", callback_data="cancel_broadcast")
        ]])
        await update.message.reply_text(f"📣 Xabar {len(users)} ta odamga yuboriladi. Tasdiqlaysizmi?", reply_markup=kb)
        return

    if state == "set_ad" and text:
        if not text.lstrip("-").isdigit():
            await update.message.reply_text("❌ Faqat raqam (Post ID):", reply_markup=get_cancel_keyboard())
            return
        ad_post_id = None if text == "0" else text
        save_and_push("ad_post.json", {"id": ad_post_id}, "Reklama yangilandi")
        admin_states[user_id] = None
        msg = "✅ Reklama o'chirildi." if ad_post_id is None else f"✅ Reklama o'rnatildi! Post ID: {ad_post_id}"
        await update.message.reply_text(msg, reply_markup=get_admin_keyboard())
        return

    # ADMIN PANEL BOSILGANDA
    if text == "➕ Kino qo'shish":
        admin_states[user_id] = "add_movie_text"
        await update.message.reply_text("➕ 5 qatorli shablonni to'ldirib yuboring:\n\nNomi\nTavsif\nkod\nhttps://poster.jpg\nPostID", reply_markup=get_cancel_keyboard())
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
        lines = [f"{i}. {movies[c].get('name', c).upper() if c in movies and isinstance(movies[c], dict) else c} — 👁 {cnt}" for i, (c, cnt) in enumerate(sorted_views, 1)]
        await update.message.reply_text("📈 Top 10 kino:\n\n" + "\n".join(lines))
        return

    if text == "📁 Katalog/Janr":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Katalog qo'shish", callback_data="add_cat"), InlineKeyboardButton("➕ Janr qo'shish", callback_data="add_gen")],
            [InlineKeyboardButton("🗑️ Katalog o'chirish", callback_data="list_del_cat"), InlineKeyboardButton("🗑️ Janr o'chirish", callback_data="list_del_gen")]
        ])
        await update.message.reply_text("📁 Katalog va Janr sozalamalari:", reply_markup=kb)
        return

    if text == "📊 Statistika":
        await update.message.reply_text(f"📊 Statistika:\n\n👥 Jami foydalanuvchi: {len(users)}\n✅ Faol: {len(active_users)}\n❌ Bloklagan: {len(deleted_users)}\n🎬 Jami kinolar: {len(movies)}\n👁 Jami ko'rishlar: {sum(views.values())}")
        return

    if text == "📣 Hammaga xabar":
        admin_states[user_id] = "broadcast"
        await update.message.reply_text(f"📣 Xabar yozing:", reply_markup=get_cancel_keyboard())
        return

    if text == "📢 Reklama xabar":
        admin_states[user_id] = "set_ad"
        await update.message.reply_text(f"📢 Post ID yuboring (o'chirish: 0):", reply_markup=get_cancel_keyboard())
        return

    # YANGI: Adminlarni boshqarish bo'limi qaytarildi
    if text == "👥 Adminlarni boshqarish":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Admin qo'shish", callback_data="add_admin_btn"),
             InlineKeyboardButton("🗑️ Admin o'chirish", callback_data="del_admin_btn")],
            [InlineKeyboardButton("📋 Adminlar ro'yxati", callback_data="list_admins_btn")]
        ])
        await update.message.reply_text("👥 Adminlarni boshqarish tizimi:", reply_markup=kb)
        return

    # YANGI: Chiroyli kanal qo'shish/o'chirish menyusi
    if text == "⚙️ Bot Sozlamalari":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Start matnini o'zgartirish", callback_data="edit_start")],
            [InlineKeyboardButton("📢 Majburiy kanallar tizimi", callback_data="manage_ch_menu")]
        ])
        await update.message.reply_text("⚙️ Bot sozalamalari:", reply_markup=kb)
        return

    await update.message.reply_text("⚠️ Noma'lum buyruq yoki amal bekor qilingan.", reply_markup=get_admin_keyboard())

# ==================== CALLBACKS ====================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global movies, channels, catalogs, genres, users, active_users, deleted_users, bot_settings, saved_movies, ratings, admins
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "random_movie":
        await query.answer()
        if not movies:
            await context.bot.send_message(chat_id=user_id, text="🎬 Hozircha bazada kino yo'q.")
            return
        await send_movie(user_id, random.choice(list(movies.keys())), context.bot)
        return

    if data == "top_rated" or data.startswith("toprated_page_"):
        await query.answer()
        page = int(data.replace("toprated_page_", "")) if data.startswith("toprated_page_") else 0
        await show_top_rated_page(query.message, context.bot, page, edit=data.startswith("toprated_page_"))
        return

    if data.startswith("toprated_open_"):
        await query.answer()
        await send_movie(user_id, data.replace("toprated_open_", ""), context.bot)
        return

    # YANGI: Saqlanganlarni reytingdek sahifali ochish inline amallari
    if data.startswith("my_saved_page_"):
        await query.answer()
        page = int(data.replace("my_saved_page_", ""))
        await show_saved_page(user_id, context.bot, page, message_to_edit=query.message)
        return

    if data.startswith("saved_page_"):
        await query.answer()
        page = int(data.replace("saved_page_", ""))
        await show_saved_page(user_id, context.bot, page, message_to_edit=query.message)
        return

    if data.startswith("saved_open_"):
        await query.answer()
        parts = data.split("_")
        code = parts[2]
        page = int(parts[3])
        await send_movie(user_id, code, context.bot, back_page=page)
        return

    # YANGI: Baholashda "Siz oldin baholagansiz" alert chiqarish va yonma-yon 5 ta tugma
    if data.startswith("rate_menu_"):
        movie_code = data.replace("rate_menu_", "")
        user_score = get_user_rating(movie_code, user_id)
        if user_score is not None:
            await query.answer("❌ Siz ushbu kinoga oldin baho bergansiz!", show_alert=True)
            return

        await query.answer()
        avg, count = get_avg_rating(movie_code)
        
        # Yonma-yon joylashgan 5 ta tugma qatori
        row = [InlineKeyboardButton(f"{i} ⭐" if i==5 else str(i), callback_data=f"rate_{movie_code}_{i}") for i in range(1, 6)]
        kb = InlineKeyboardMarkup([row])
        
        info = f"{avg:.1f}/5 ({count}ta ovoz)" if count else "Hali baholanmagan"
        await context.bot.send_message(chat_id=user_id, text=f"⭐ Ushbu kinoga baho bering:\n\nHozirgi reyting: {info}", reply_markup=kb)
        return

    if data.startswith("rate_") and not data.startswith("rate_menu_"):
        rest = data[len("rate_"):]
        movie_code, _, score_str = rest.rpartition("_")
        score = int(score_str)
        
        if get_user_rating(movie_code, user_id) is not None:
            await query.answer("❌ Siz oldin baholagansiz!", show_alert=True)
            try: await query.message.delete()
            except Exception: pass
            return
            
        await query.answer()
        set_rating(movie_code, user_id, score)
        avg, count = get_avg_rating(movie_code)
        await query.answer(f"✅ Siz {score} ball berdingiz! O'rtacha: {avg:.1f}/5", show_alert=True)
        try: await query.message.delete()
        except Exception: pass
        return

    # Qismli kinolarni boshqarish
    if data.startswith("part_") and not data.startswith("part_back_") and not data.startswith("partlist_"):
        await query.answer()
        rest = data[len("part_"):]
        movie_code, _, idx_str = rest.rpartition("_")
        back_page = None
        if "_" in idx_str:
            idx_str, _, bp_str = idx_str.partition("_")
            back_page = int(bp_str)
        await send_movie_part(user_id, movie_code, int(idx_str), context.bot, back_page)
        return

    if data.startswith("partlist_"):
        await query.answer()
        rest = data.replace("partlist_", "")
        back_page = None
        if "_" in rest:
            rest, _, bp_str = rest.partition("_")
            back_page = int(bp_str)
        movie_code = rest
        if movie_code in movies:
            total_parts = len(get_video_ids(movies[movie_code]))
            try: await query.message.edit_reply_markup(reply_markup=build_parts_list_keyboard(movie_code, total_parts, back_page))
            except Exception: pass
        return

    if data.startswith("part_back_"):
        await query.answer()
        rest = data.replace("part_back_", "")
        back_page = None
        if "_" in rest:
            rest, _, bp_str = rest.partition("_")
            back_page = int(bp_str)
        movie_code = rest
        current = part_progress.get(get_part_progress_key(user_id, movie_code), 0)
        if movie_code in movies:
            total_parts = len(get_video_ids(movies[movie_code]))
            try: await query.message.edit_reply_markup(reply_markup=build_part_nav_keyboard(movie_code, current, total_parts, back_page))
            except Exception: pass
        return

    if data == "check":
        if await is_joined(context.bot, user_id):
            await query.answer("✅ Obuna tasdiqlandi!")
            try: await query.message.delete()
            except Exception: pass
            await send_welcome_message(user_id, query.from_user.first_name, context.bot)
        else:
            await query.answer("❌ Kanallarga hali a'zo bo'lmadingiz!", show_alert=True)
        return

    if data == "go_to_main_menu":
        await query.answer()
        await send_welcome_message(user_id, query.from_user.first_name, context.bot)
        return

    if data.startswith("unsave_"):
        movie_code = data.split("_")[1]
        uid_str = str(user_id)
        if uid_str in saved_movies and movie_code in saved_movies[uid_str]:
            saved_movies[uid_str].remove(movie_code)
            save_and_push("saved_movies.json", saved_movies, "Saqlanganlardan o'chirildi")
        await query.answer("🗑️ Saqlanganlardan o'chirildi!", show_alert=True)
        try: await query.message.delete()
        except Exception: pass
        await show_saved_page(user_id, context.bot, 0)
        return

    if data.startswith("save_"):
        movie_code = data.split("_")[1]
        uid_str = str(user_id)
        if uid_str not in saved_movies: saved_movies[uid_str] = []
        if movie_code not in saved_movies[uid_str]:
            saved_movies[uid_str].append(movie_code)
            save_and_push("saved_movies.json", saved_movies, "Kino saqlandi")
            await query.answer("❤️ Saqlandi!", show_alert=True)
        else:
            await query.answer("✨ Bu kino allaqachon saqlangan!", show_alert=True)
        return

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

    # YANGI: Chiroyli Kanal boshqarish tizimi
    if data == "manage_ch_menu":
        await query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Majburiy kanal qo'shish", callback_data="add_ch_start")],
            [InlineKeyboardButton("🗑️ Majburiy kanalni o'chirish", callback_data="del_ch_start_menu")],
            [InlineKeyboardButton("📋 Kanallar ro'yxati", callback_data="list_ch_view")]
        ])
        await query.message.edit_text("📢 Majburiy obuna kanallarini boshqarish paneli:", reply_markup=kb)
        return

    if data == "list_ch_view":
        await query.answer()
        lines = [f"🔹 ID: `{ch_id}` — {name}" for ch_id, name in channels.items()]
        text = "📋 Hozirgi majburiy kanallar:\n\n" + ("\n".join(lines) if lines else "Kanallar mavjud emas.")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="manage_ch_menu")]])
        await query.message.edit_text(text, reply_markup=kb)
        return

    if data == "add_ch_start":
        await query.answer()
        admin_states[user_id] = "channel_add"
        await context.bot.send_message(chat_id=user_id, text="📢 Yangi kanalni formatda yuboring:\n`@username Kanal nomi` yoki `-100... Kanal nomi`", reply_markup=get_cancel_keyboard())
        return

    if data == "del_ch_start_menu":
        await query.answer()
        admin_states[user_id] = "channel_del_text"
        lines = [f"🔑 `{ch_id}` — {name}" for ch_id, name in channels.items()]
        text = "🗑️ O'chirmoqchi bo'lgan kanalingizning telegram ID raqamini (yoki @username) nusxalab matn ko'rinishida yuboring:\n\n" + "\n".join(lines)
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=get_cancel_keyboard())
        return

    # YANGI: Admin boshqarish inline tugmalari amali
    if data == "add_admin_btn":
        await query.answer()
        admin_states[user_id] = "add_admin_state"
        await context.bot.send_message(chat_id=user_id, text="➕ Qo'shmoqchi bo'lgan yangi adminingizning Telegram ID raqamini kiriting:", reply_markup=get_cancel_keyboard())
        return

    if data == "del_admin_btn":
        await query.answer()
        admin_states[user_id] = "del_admin_state"
        await context.bot.send_message(chat_id=user_id, text="🗑️ O'chirmoqchi bo'lgan adminingizning Telegram ID raqamini kiriting:", reply_markup=get_cancel_keyboard())
        return

    if data == "list_admins_btn":
        await query.answer()
        lines = [f"👤 Admin ID: `{a}`" for a in list(admins)]
        await query.message.edit_text("📋 Bot adminlari ro'yxati:\n\n" + "\n".join(lines), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="cancel_edit")]]))
        return

    # Kino tahrirlash inline amallari
    if data.startswith("edit_name_") or data.startswith("edit_desc_") or data.startswith("edit_poster_") or data.startswith("edit_vid_"):
        await query.answer()
        parts = data.split("_", 2)
        admin_states[user_id] = f"edit_field_{parts[1]}_{parts[2]}"
        await context.bot.send_message(chat_id=user_id, text=f"📝 Yangi qiymatni yuboring:", reply_markup=get_cancel_keyboard())
        return

    if data.startswith("edit_cats_"):
        await query.answer()
        code = data.split("_")[2]
        if code in movies and not isinstance(movies[code], dict):
            movies[code] = {"name": f"Kino {code}", "desc": "", "poster": "", "video_id": movies[code], "catalogs": [], "genres": []}
        movie_cats = movies[code].get("catalogs", []) if code in movies else []
        kb = [[InlineKeyboardButton(f"{'✅ ' if cat in movie_cats else ''}{cat}", callback_data=f"tgl_cat_{code}_{i}")] for i, cat in enumerate(catalogs)]
        kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"edit_back_{code}")])
        await query.message.edit_text("📂 Kataloglarni boshqarish:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("tgl_cat_"):
        parts = data.split("_")
        code, idx = parts[2], int(parts[3])
        cat_name = catalogs[idx]
        if code in movies:
            if "catalogs" not in movies[code]: movies[code]["catalogs"] = []
            if cat_name in movies[code]["catalogs"]: movies[code]["catalogs"].remove(cat_name)
            else: movies[code]["catalogs"].append(cat_name)
            save_and_push("movies.json", movies, f"Katalog tahrirlandi: {code}")
            movie_cats = movies[code].get("catalogs", [])
            kb = [[InlineKeyboardButton(f"{'✅ ' if cat in movie_cats else ''}{cat}", callback_data=f"tgl_cat_{code}_{i}")] for i, cat in enumerate(catalogs)]
            kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"edit_back_{code}")])
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("edit_gnrs_"):
        await query.answer()
        code = data.split("_")[2]
        if code in movies and not isinstance(movies[code], dict):
            movies[code] = {"name": f"Kino {code}", "desc": "", "poster": "", "video_id": movies[code], "catalogs": [], "genres": []}
        movie_gnrs = movies[code].get("genres", []) if code in movies else []
        kb = [[InlineKeyboardButton(f"{'✅ ' if gen in movie_gnrs else ''}{gen}", callback_data=f"tgl_gen_{code}_{i}")] for i, gen in enumerate(genres)]
        kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"edit_back_{code}")])
        await query.message.edit_text("🎭 Janrlarni boshqarish:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("tgl_gen_"):
        parts = data.split("_")
        code, idx = parts[2], int(parts[3])
        gen_name = genres[idx]
        if code in movies:
            if "genres" not in movies[code]: movies[code]["genres"] = []
            if gen_name in movies[code]["genres"]: movies[code]["genres"].remove(gen_name)
            else: movies[code]["genres"].append(gen_name)
            save_and_push("movies.json", movies, f"Janr tahrirlandi: {code}")
            movie_gnrs = movies[code].get("genres", [])
            kb = [[InlineKeyboardButton(f"{'✅ ' if gen in movie_gnrs else ''}{gen}", callback_data=f"tgl_gen_{code}_{i}")] for i, gen in enumerate(genres)]
            kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"edit_back_{code}")])
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("edit_back_"):
        await query.answer()
        code = data.split("_")[2]
        data_m = movies[code]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📛 Nom", callback_data=f"edit_name_{code}"), InlineKeyboardButton("📝 Ma'lumot", callback_data=f"edit_desc_{code}")],
            [InlineKeyboardButton("🖼 Poster", callback_data=f"edit_poster_{code}"), InlineKeyboardButton("📥 Video ID", callback_data=f"edit_vid_{code}")],
            [InlineKeyboardButton("📂 Kataloglar (Boshqarish)", callback_data=f"edit_cats_{code}")],
            [InlineKeyboardButton("🎭 Janrlar (Boshqarish)", callback_data=f"edit_gnrs_{code}")],
            [InlineKeyboardButton("❌ Chiqish (Tayyor)", callback_data="cancel_edit")]
        ])
        await query.message.edit_text(f"✏️ '{data_m.get('name', code)}' — nimani tahrirlaysiz?\n\n📂 Katalog: {', '.join(data_m.get('catalogs', []))}\n🎭 Janr: {', '.join(data_m.get('genres', []))}", reply_markup=kb)
        return

    if data == "cancel_edit":
        await query.answer()
        await query.message.edit_text("✅ Amal yakunlandi.", reply_markup=None)
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
        await context.bot.send_message(chat_id=user_id, text="📝 Yangi start xabarini yuboring (Rasm, GIF yoki oddiy Matn bo'lishi mumkin):", reply_markup=get_cancel_keyboard())
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
            if user_id in new_movie_wizard and cat_name not in new_movie_wizard[user_id]["catalogs"]:
                new_movie_wizard[user_id]["catalogs"].append(cat_name)
                await query.answer(f"➕ {cat_name} qo'shildi")
        return

    # YANGI: Janr tanlangandan so'ng "Xabar yuborilsinmi?" so'ramaydi, full tugatadi.
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
                admin_states[user_id] = None
                await query.message.edit_text(f"🎉 '{wiz['name']}' kinosi muvaffaqiyatli qo'shildi va saqlandi!", reply_markup=None)
                await context.bot.send_message(chat_id=user_id, text="Asosiy boshqaruv paneli:", reply_markup=get_admin_keyboard())
        else:
            idx = int(val)
            gen_name = genres[idx]
            if user_id in new_movie_wizard and gen_name not in new_movie_wizard[user_id]["genres"]:
                new_movie_wizard[user_id]["genres"].append(gen_name)
                await query.answer(f"➕ {gen_name} qo'shildi")
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
                except Exception: fail += 1
            await context.bot.send_message(chat_id=user_id, text=f"📊 Natija:\n✅ Yuborildi: {success}\n❌ Muammo: {fail}", reply_markup=get_admin_keyboard())
        return

    if data == "cancel_broadcast":
        await query.answer("Bekor qilindi")
        try: await query.message.delete()
        except Exception: pass
        return

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    pass

def run_fake_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()

def keep_alive_loop():
    if not RENDER_EXTERNAL_URL: return
    while True:
        threading.Event().wait(240)
        try: requests.get(RENDER_EXTERNAL_URL, timeout=10)
        except Exception: pass

def main():
    load_data()
    if not TOKEN: return
    
    threading.Thread(target=run_fake_server, daemon=True).start()
    threading.Thread(target=auto_backup_loop, daemon=True).start()
    threading.Thread(target=keep_alive_loop, daemon=True).start()
    
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND | filters.PHOTO | filters.ANIMATION, handle_text))
    app.add_error_handler(error_handler)

    app.run_polling()

if __name__ == "__main__":
    main()
