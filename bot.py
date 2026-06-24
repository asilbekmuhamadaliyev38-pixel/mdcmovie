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
admin_states = {}
new_movie_wizard = {}
ad_post_id = None
views = {}          
saved_movies = {}   

ratings = {}        # {"movie_code": {"user_id": baho}}
part_progress = {}  # {"user_id_movie_code": current_part_index}

_pending_saves = {}      
_pending_saves_lock = threading.Lock()

bot_settings = {
    "protect_content": True,
    "start_media_type": "text", # text, photo, animation
    "start_file_id": None,
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
        except Exception:
            pass

# ==================== MA'LUMOT YUKLASH ====================
def load_data():
    global admins, movies, channels, catalogs, genres, users, active_users
    global deleted_users, ad_post_id, bot_settings
    global views, saved_movies, ratings, part_progress

    movies.update(read_file("movies.json", {}))
    channels.update(read_file("channels.json", {}))
    bot_settings.update(read_file("settings.json", bot_settings))
    views.update(read_file("views.json", {}))
    saved_movies_raw = read_file("saved_movies.json", {})
    saved_movies.update({str(k): v for k, v in saved_movies_raw.items()})

    ratings_raw = read_file("ratings.json", {})
    ratings.update(ratings_raw)
    part_progress_raw = read_file("part_progress.json", {})
    part_progress.update(part_progress_raw)

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

# ==================== TOP BAHOLANGANLAR SAHIFALASH ====================
TOP_RATED_PAGE_SIZE = 10

def get_sorted_top_rated():
    scored = []
    for code in movies:
        avg, count = get_avg_rating(code)
        if count > 0:
            scored.append((code, avg, count))
    scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return scored

def build_top_rated_keyboard(scored, page, prefix="toprated"):
    start = page * TOP_RATED_PAGE_SIZE
    end = start + TOP_RATED_PAGE_SIZE
    page_items = scored[start:end]

    kb = []
    row = []
    for offset, item in enumerate(page_items):
        code = item[0] if isinstance(item, tuple) else item
        num = start + offset + 1
        row.append(InlineKeyboardButton(str(num), callback_data=f"{prefix}_open_{code}"))
        if len(row) == 5:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    nav_row = []
    if start > 0:
        nav_row.append(InlineKeyboardButton("◀️ Oldingi", callback_data=f"{prefix}_page_{page-1}"))
    if end < len(scored):
        nav_row.append(InlineKeyboardButton("Keyingi ▶️", callback_data=f"{prefix}_page_{page+1}"))
    if nav_row:
        kb.append(nav_row)

    return InlineKeyboardMarkup(kb), page_items, start

async def show_top_rated_page(message, bot, page, edit=False):
    scored = get_sorted_top_rated()
    if not scored:
        text = "⭐ Hali hech qanday kino baholanmagan."
        if edit: await message.edit_text(text)
        else: await bot.send_message(chat_id=message.chat_id, text=text)
        return

    kb, page_items, start = build_top_rated_keyboard(scored, page, "toprated")
    lines = []
    for offset, (code, avg, count) in enumerate(page_items):
        num = start + offset + 1
        d = movies[code]
        name = d.get("name", code).upper() if isinstance(d, dict) else code.upper()
        lines.append(f"{num}. {name} {avg:.1f}/5 ({count}ta ovoz)")

    total_pages = (len(scored) - 1) // TOP_RATED_PAGE_SIZE + 1
    text = f"⭐ Top baholangan kinolar ({page+1}/{total_pages}-sahifa):\n\n" + "\n".join(lines) + "\n\n👇 Kerakli kinoning raqamini bosing:"

    if edit: await message.edit_text(text, reply_markup=kb)
    else: await bot.send_message(chat_id=message.chat_id, text=text, reply_markup=kb)

# ==================== SAQLANGANLAR SAHIFALASH ====================
async def show_saved_movies_page(chat_id, bot, page, edit=False, message=None):
    uid_str = str(chat_id)
    saved = saved_movies.get(uid_str, [])
    valid = [c for c in saved if c in movies]
    
    if not valid:
        text = "❤️ Siz hali hech qanday kino saqlamagansiz.\n\nKinoni ko'rayotganda '❤️ Saqlash' tugmasini bosing!"
        if edit and message: await message.edit_text(text)
        else: await bot.send_message(chat_id=chat_id, text=text)
        return

    kb, page_items, start = build_top_rated_keyboard(valid, page, "mysaved")
    lines = []
    for offset, code in enumerate(page_items):
        num = start + offset + 1
        d = movies[code]
        name = d.get("name", code).upper() if isinstance(d, dict) else code.upper()
        avg, count = get_avg_rating(code)
        lines.append(f"{num}. {name} {avg:.1f}/5 ({count}ta ovoz)")

    total_pages = (len(valid) - 1) // TOP_RATED_PAGE_SIZE + 1
    text = f"❤️ Saqlangan kinolaringiz ({page+1}/{total_pages}-sahifa):\n\n" + "\n".join(lines) + "\n\n👇 Kerakli kinoning raqamini bosing:"
    
    if edit and message: await message.edit_text(text, reply_markup=kb)
    else: await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)

async def show_saved_movie_detail(chat_id, bot, movie_code):
    if movie_code not in movies: return
    d = movies[movie_code]
    name = d.get("name", movie_code).upper() if isinstance(d, dict) else movie_code.upper()
    desc = d.get("desc", "") if isinstance(d, dict) else ""
    poster = d.get("poster") if isinstance(d, dict) else None
    vc = views.get(movie_code, 0)
    avg, count = get_avg_rating(movie_code)
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Ko'rish", callback_data=f"watch_{movie_code}"),
         InlineKeyboardButton("🗑️ O'chirish", callback_data=f"unsave_{movie_code}")],
        [InlineKeyboardButton("🔙 Ro'yxatga qaytish", callback_data="mysaved_page_0")]
    ])
    caption = f"🎬 {name}\n📝 {desc}\n👁 {vc} marta ko'rilgan\n⭐ Reyting: {avg:.1f}/5 ({count}ta ovoz)\n🔑 Kod: {movie_code}"
    try:
        if poster and poster.startswith("http"):
            await bot.send_photo(chat_id=chat_id, photo=poster, caption=caption, reply_markup=kb)
        else:
            await bot.send_message(chat_id=chat_id, text=caption, reply_markup=kb)
    except Exception:
        await bot.send_message(chat_id=chat_id, text=caption, reply_markup=kb)

# ==================== QISMLI KINO YORDAMCHI FUNKSIYALARI ====================
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

# ==================== START XABARINI YUBORISH ====================
async def send_welcome_message(chat_id, bot, first_name):
    media_type = bot_settings.get("start_media_type", "text")
    file_id = bot_settings.get("start_file_id")
    text = bot_settings.get("start_text", "").format(name=first_name)
    kb = get_user_inline_keyboard()

    try:
        if media_type == "photo" and file_id:
            await bot.send_photo(chat_id=chat_id, photo=file_id, caption=text, reply_markup=kb)
        elif media_type == "animation" and file_id:
            await bot.send_animation(chat_id=chat_id, animation=file_id, caption=text, reply_markup=kb)
        else:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
    except Exception:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)

# ==================== KINO YUBORISH ====================
async def send_movie(chat_id, movie_code, bot, notify_new=False):
    global ad_post_id, bot_settings
    if movie_code not in movies: return False
    data = movies[movie_code]

    video_ids = get_video_ids(data)

    if len(video_ids) > 1:
        return await send_movie_part(chat_id, movie_code, 0, bot)

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
def build_part_nav_keyboard(movie_code, part_index, total_parts):
    nav_row = []
    if part_index > 0:
        nav_row.append(InlineKeyboardButton("◀️ Oldingi qism", callback_data=f"part_{movie_code}_{part_index-1}"))
    if part_index < total_parts - 1:
        nav_row.append(InlineKeyboardButton("Keyingi qism ▶️", callback_data=f"part_{movie_code}_{part_index+1}"))

    rows = []
    if nav_row: rows.append(nav_row)
    rows.append([InlineKeyboardButton(f"📋 Qismlar ({part_index+1}/{total_parts})", callback_data=f"partlist_{movie_code}")])
    rows.append([
        InlineKeyboardButton("❤️ Saqlash", callback_data=f"save_{movie_code}"),
        InlineKeyboardButton("🏠 Bosh menyu", callback_data="go_to_main_menu")
    ])
    rows.append([InlineKeyboardButton("⭐ Baholash", callback_data=f"rate_menu_{movie_code}")])
    return InlineKeyboardMarkup(rows)

def build_parts_list_keyboard(movie_code, total_parts):
    kb = []
    row = []
    for i in range(total_parts):
        row.append(InlineKeyboardButton(str(i + 1), callback_data=f"part_{movie_code}_{i}"))
        if len(row) == 5:
            kb.append(row)
            row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"part_back_{movie_code}")])
    return InlineKeyboardMarkup(kb)

async def send_movie_part(chat_id, movie_code, part_index, bot):
    if movie_code not in movies: return False
    data = movies[movie_code]
    video_ids = get_video_ids(data)
    total_parts = len(video_ids)

    if part_index < 0 or part_index >= total_parts: part_index = 0

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

    await send_welcome_message(user_id, context.bot, update.effective_user.first_name)

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

# ==================== MATN VA MEDIA XABARLARI ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ad_post_id, bot_settings, catalogs, genres, movies, admins
    user_id = update.effective_user.id
    
    text = update.message.text.strip() if update.message.text else ""

    if text in ["❌ Bekor qilish", "🏠 Asosiy panelga qaytish"]:
        admin_states[user_id] = None
        new_movie_wizard.pop(user_id, None)
        if is_admin(user_id):
            await update.message.reply_text("🏠 Admin paneli:", reply_markup=get_admin_keyboard())
        else:
            await send_welcome_message(user_id, context.bot, update.effective_user.first_name)
        return

    if not is_admin(user_id):
        if not await is_joined(context.bot, user_id):
            await update.message.reply_text("❗ Avval kanallarga obuna bo'ling!", reply_markup=await get_subscription_keyboard(context.bot))
            return
        if text and await send_movie(update.effective_chat.id, text, context.bot): return
        await update.message.reply_text("❌ Bunday kodli kino topilmadi.")
        return

    state = admin_states.get(user_id)

    if state == "edit_start_text":
        if update.message.photo:
            bot_settings["start_media_type"] = "photo"
            bot_settings["start_file_id"] = update.message.photo[-1].file_id
            bot_settings["start_text"] = update.message.caption or ""
        elif update.message.animation:
            bot_settings["start_media_type"] = "animation"
            bot_settings["start_file_id"] = update.message.animation.file_id
            bot_settings["start_text"] = update.message.caption or ""
        else:
            bot_settings["start_media_type"] = "text"
            bot_settings["start_file_id"] = None
            bot_settings["start_text"] = text

        save_and_push("settings.json", bot_settings, "Start xabari yangilandi")
        admin_states[user_id] = None
        await update.message.reply_text("✅ Yangi start xabari muvaffaqiyatli saqlandi!", reply_markup=get_admin_keyboard())
        return

    if state == "add_admin_id":
        if not text.isdigit():
            await update.message.reply_text("❌ Faqat raqamlardan iborat Telegram ID kiriting:", reply_markup=get_cancel_keyboard())
            return
        new_id = int(text)
        admins.add(new_id)
        save_and_push("admins.json", list(admins), "Yangi admin qo'shildi")
        admin_states[user_id] = None
        await update.message.reply_text(f"✅ {new_id} muvaffaqiyatli admin qilindi!", reply_markup=get_admin_keyboard())
        return

    if not text: return

    if state == "delete_movie_by_code":
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
        await update.message.reply_text("🗂 Katalog tanlang (bir nechta bo'lishi mumkin):", reply_markup=InlineKeyboardMarkup(kb))
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
            [InlineKeyboardButton("📛 Nom", callback_data=f"edit_name_{code}"), InlineKeyboardButton("📝 Ma'lumot", callback_data=f"edit_desc_{code}")],
            [InlineKeyboardButton("🖼 Poster", callback_data=f"edit_poster_{code}"), InlineKeyboardButton("📥 Video ID", callback_data=f"edit_vid_{code}")],
            [InlineKeyboardButton("📂 Kataloglar (Boshqarish)", callback_data=f"edit_cats_{code}")],
            [InlineKeyboardButton("🎭 Janrlar (Boshqarish)", callback_data=f"edit_gnrs_{code}")],
            [InlineKeyboardButton("❌ Chiqish (Tayyor)", callback_data="cancel_edit")]
        ])
        await update.message.reply_text(f"✏️ '{name}' — nimani tahrirlaysiz?\n\n📂 Katalog: {', '.join(cur_cats) or 'Yoqu'}\n🎭 Janr: {', '.join(cur_gnrs) or 'Yoqu'}", reply_markup=kb)
        return

    if state and state.startswith("edit_field_"):
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
            await update.message.reply_text(f"✅ Muvaffaqiyatli yangilandi!", reply_markup=get_admin_keyboard())
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
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yuborish", callback_data="broadcast_confirm"), InlineKeyboardButton("❌ Bekor", callback_data="cancel_broadcast")]])
        await update.message.reply_text(f"📣 Xabar:\n\n{text}\n\n👥 {len(users)} ta foydalanuvchiga yuboriladi. Tasdiqlaysizmi?", reply_markup=kb)
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

    # ADMIN TUGMALARI DIAGNOSTIKASI
    if text == "➕ Kino qo'shish":
        admin_states[user_id] = "add_movie_text"
        await update.message.reply_text("➕ 5 qatorli shablonni to'ldirib yuboring:\n\nKino nomi\nTavsif\nkod\nhttps://poster.jpg\nPostID", reply_markup=get_cancel_keyboard())
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
        lines = [f"{i}. {movies[code].get('name', code).upper() if code in movies and isinstance(movies[code], dict) else code} — 👁 {count}" for i, (code, count) in enumerate(sorted_views, 1)]
        await update.message.reply_text("📈 Top 10 kino:\n\n" + "\n".join(lines))
        return

    if text == "📁 Katalog/Janr":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Katalog qo'shish", callback_data="add_cat"), InlineKeyboardButton("➕ Janr qo'shish", callback_data="add_gen")], [InlineKeyboardButton("🗑️ Katalog o'chirish", callback_data="list_del_cat"), InlineKeyboardButton("🗑️ Janr o'chirish", callback_data="list_del_gen")]])
        await update.message.reply_text("📁 Katalog va Janr sozalamalari:", reply_markup=kb)
        await update.message.reply_text("Qaytish:", reply_markup=get_return_main_keyboard())
        return

    if text == "📊 Statistika":
        most_viewed = "Yo'q"
        if views:
            top_code = max(views, key=views.get)
            most_viewed = f"{movies.get(top_code, {}).get('name', top_code) if isinstance(movies.get(top_code), dict) else top_code} ({views[top_code]} marta)"

        best_rated = "Yo'q"
        best_avg, best_code = 0, None
        for code in movies:
            avg, count = get_avg_rating(code)
            if count > 0 and avg > best_avg: best_avg, best_code = avg, code
        if best_code: best_rated = f"{movies.get(best_code, {}).get('name', best_code) if isinstance(movies.get(best_code), dict) else best_code} ({best_avg:.1f}⭐)"

        await update.message.reply_text(f"📊 Statistika:\n\n👥 Jami foydalanuvchi: {len(users)}\n✅ Faol: {len(active_users)}\n❌ Bloklagan: {len(deleted_users)}\n🎬 Jami kinolar: {len(movies)}\n👁 Jami ko'rishlar: {sum(views.values())}\n\n🔥 Eng ko'p ko'rilgan: {most_viewed}\n⭐ Eng yuqori baholangan: {best_rated}")
        return

    if text == "👥 Adminlarni boshqarish":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Admin qo'shish", callback_data="add_admin"), InlineKeyboardButton("🗑️ Admin o'chirish", callback_data="list_del_admin")]])
        await update.message.reply_text(f"👥 Jami adminlar soni: {len(admins)} ta\n\nKerakli amalni tanlang:", reply_markup=kb)
        return

    if text == "📣 Hammaga xabar":
        admin_states[user_id] = "broadcast"
        await update.message.reply_text(f"📣 Xabar yozing ({len(users)} ta foydalanuvchi):", reply_markup=get_cancel_keyboard())
        return

    if text == "📢 Reklama xabar":
        admin_states[user_id] = "set_ad"
        await update.message.reply_text(f"📢 Reklama Post ID yuboring (o'chirish: 0):", reply_markup=get_cancel_keyboard())
        return

    if text == "📋 Kinolar ro'yxati":
        if not movies:
            await update.message.reply_text("🎬 Bazada hech qanday kino yo'q.")
            return
        lines_list = [f"🔑 {code} — {d.get('name', code).upper() if isinstance(d, dict) else code.upper()} 👁{views.get(code, 0)}" for code, d in movies.items()]
        await update.message.reply_text(f"🎬 Kinolar ro'yxati ({len(movies)} ta):\n\n" + "\n".join(lines_list[:50]))
        return

    if text == "⚙️ Bot Sozlamalari":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Start xabarini o'zgartirish", callback_data="edit_start")], [InlineKeyboardButton("📢 Majburiy kanallar", callback_data="manage_ch")]])
        await update.message.reply_text("⚙️ Bot sozalamalari:", reply_markup=kb)
        await update.message.reply_text("Qaytish:", reply_markup=get_return_main_keyboard())
        return

    await update.message.reply_text("⚠️ Noma'lum buyruq.", reply_markup=get_admin_keyboard())

# ==================== CALLBACKS ====================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global movies, channels, catalogs, genres, users, bot_settings, saved_movies, ratings, admins
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "random_movie":
        await query.answer()
        if not movies:
            await context.bot.send_message(chat_id=user_id, text="🎬 Hozircha bazada kino yo'q.")
            return
        import random
        await send_movie(user_id, random.choice(list(movies.keys())), context.bot)
        return

    if data == "top_rated" or data.startswith("toprated_page_"):
        await query.answer()
        page = int(data.replace("toprated_page_", "")) if data.startswith("toprated_page_") else 0
        await show_top_rated_page(query.message, context.bot, page, edit=data.startswith("toprated_page_"))
        return

    if data.startswith("toprated_open_") or data.startswith("mysaved_open_"):
        await query.answer()
        code = data.replace("toprated_open_", "").replace("mysaved_open_", "")
        if data.startswith("mysaved_open_"):
            await show_saved_movie_detail(user_id, context.bot, code)
        else:
            await send_movie(user_id, code, context.bot)
        return

    if data == "my_saved" or data.startswith("mysaved_page_"):
        await query.answer()
        page = int(data.replace("mysaved_page_", "")) if data.startswith("mysaved_page_") else 0
        await show_saved_movies_page(user_id, context.bot, page, edit=data.startswith("mysaved_page_"), message=query.message)
        return

    # BAHOLASH TUGMALARI (YONMA-YON 5 TASI YULDUZCHA)
    if data.startswith("rate_menu_"):
        await query.answer()
        movie_code = data.replace("rate_menu_", "")
        avg, count = get_avg_rating(movie_code)
        
        kb_row = []
        for i in range(1, 6):
            kb_row.append(InlineKeyboardButton("⭐" * i if i==1 else str(i)+"⭐", callback_data=f"rate_{movie_code}_{i}"))
        
        info = f"{avg:.1f}/5 ({count}ta ovoz)" if count else "Baholanmagan"
        await context.bot.send_message(
            chat_id=user_id,
            text=f"⭐ Ushbu kinoga baho bering:\nHozirgi o'rtacha reyting: {info}",
            reply_markup=InlineKeyboardMarkup([kb_row])
        )
        return

    if data.startswith("rate_") and not data.startswith("rate_menu_"):
        await query.answer()
        rest = data[len("rate_"):]
        movie_code, _, score_str = rest.rpartition("_")
        set_rating(movie_code, user_id, int(score_str))
        avg, _ = get_avg_rating(movie_code)
        await query.answer(f"✅ Baholandi! Yangi o'rtacha: {avg:.1f}/5", show_alert=True)
        return

    if data.startswith("part_") and not data.startswith("part_back_") and not data.startswith("partlist_"):
        await query.answer()
        rest = data[len("part_"):]
        movie_code, _, idx_str = rest.rpartition("_")
        await send_movie_part(user_id, movie_code, int(idx_str), context.bot)
        return

    if data.startswith("partlist_"):
        await query.answer()
        movie_code = data.replace("partlist_", "")
        if movie_code in movies:
            await query.message.edit_reply_markup(reply_markup=build_parts_list_keyboard(movie_code, len(get_video_ids(movies[movie_code]))))
        return

    if data.startswith("part_back_"):
        await query.answer()
        movie_code = data.replace("part_back_", "")
        if movie_code in movies:
            await query.message.edit_reply_markup(reply_markup=build_part_nav_keyboard(movie_code, part_progress.get(get_part_progress_key(user_id, movie_code), 0), len(get_video_ids(movies[movie_code]))))
        return

    if data == "check":
        if await is_joined(context.bot, user_id):
            await query.answer("✅ Obuna tasdiqlandi!")
            await query.message.delete()
            await send_welcome_message(user_id, context.bot, query.from_user.first_name)
        else:
            await query.answer("❌ Kanallarga hali a'zo bo'lmadingiz!", show_alert=True)
        return

    if data == "go_to_main_menu":
        await query.answer()
        await send_welcome_message(user_id, context.bot, query.from_user.first_name)
        return

    if data.startswith("watch_"):
        await query.answer()
        await send_movie(user_id, data.split("_")[1], context.bot)
        return

    if data.startswith("unsave_"):
        movie_code = data.split("_")[1]
        uid_str = str(user_id)
        if uid_str in saved_movies and movie_code in saved_movies[uid_str]:
            saved_movies[uid_str].remove(movie_code)
            save_and_push("saved_movies.json", saved_movies, "Saqlanganlardan o'chirildi")
        await query.answer("🗑️ O'chirildi!", show_alert=True)
        await query.message.delete()
        await show_saved_movies_page(user_id, context.bot, 0)
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
            await query.answer("✨ Allaqachon saqlangan!", show_alert=True)
        return

    if data == "user_show_catalogs":
        await query.answer()
        kb = []
        for i in range(0, len(catalogs), 2):
            row = [InlineKeyboardButton(catalogs[i], switch_inline_query_current_chat=f"katalog:{catalogs[i]}")]
            if i + 1 < len(catalogs): row.append(InlineKeyboardButton(catalogs[i+1], switch_inline_query_current_chat=f"katalog:{catalogs[i+1]}"))
            kb.append(row)
        kb.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="go_to_main_menu")])
        await query.message.edit_text("📂 Kerakli katalogni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "user_show_genres":
        await query.answer()
        kb = []
        for i in range(0, len(genres), 2):
            row = [InlineKeyboardButton(genres[i], switch_inline_query_current_chat=f"janr:{genres[i]}")]
            if i + 1 < len(genres): row.append(InlineKeyboardButton(genres[i+1], switch_inline_query_current_chat=f"janr:{genres[i+1]}"))
            kb.append(row)
        kb.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="go_to_main_menu")])
        await query.message.edit_text("🎭 Kerakli janrni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if not is_admin(user_id): return

    # ADMIN PANEL ISHLARI
    if data == "add_admin":
        await query.answer()
        admin_states[user_id] = "add_admin_id"
        await context.bot.send_message(chat_id=user_id, text="➕ Yangi adminning Telegram ID raqamini kiriting:", reply_markup=get_cancel_keyboard())
        return

    if data == "list_del_admin":
        await query.answer()
        kb = [[InlineKeyboardButton(f"🗑️ {adm_id}", callback_data=f"del_admin_{adm_id}")] for adm_id in admins if adm_id != ADMIN_ID]
        if not kb:
            await context.bot.send_message(chat_id=user_id, text="Boshqa adminlar mavjud emas.")
            return
        await query.message.edit_text("🗑️ O'chirmoqchi bo'lgan adminni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("del_admin_"):
        await query.answer()
        adm_id = int(data.replace("del_admin_", ""))
        admins.discard(adm_id)
        save_and_push("admins.json", list(admins), "Admin o'chirildi")
        await context.bot.send_message(chat_id=user_id, text=f"✅ {adm_id} adminlikdan olindi!", reply_markup=get_admin_keyboard())
        return

    # MAJBURIY KANALLAR TUZATILDI (CHIROYLI REJIM VA TASDIQLASH BILAN)
    if data == "manage_ch":
        await query.answer()
        kb = [[InlineKeyboardButton(f"📢 {name}", callback_data=f"view_ch_{ch_id}")] for ch_id, name in channels.items()]
        kb.append([InlineKeyboardButton("➕ Kanal qo'shish", callback_data="add_ch_start")])
        await query.message.edit_text("📢 Majburiy obuna kanallari ro'yxati (Boshqarish uchun kanal ustiga bosing):", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("view_ch_"):
        await query.answer()
        ch_id = data.replace("view_ch_", "")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Kanalni o'chirish", callback_data=f"del_ch_{ch_id}")], [InlineKeyboardButton("🔙 Orqaga", callback_data="manage_ch")]])
        await query.message.edit_text(f"Kanal: {channels.get(ch_id, ch_id)}\nID/Username: {ch_id}\n\nUshbu kanalni o'chirib tashlaysizmi?", reply_markup=kb)
        return

    if data.startswith("del_ch_"):
        await query.answer()
        ch_id = data.replace("del_ch_", "")
        if ch_id in channels:
            removed = channels.pop(ch_id)
            save_and_push("channels.json", channels, f"Kanal o'chirildi: {removed}")
            await context.bot.send_message(chat_id=user_id, text=f"✅ Kanal olib tashlandi: {removed}", reply_markup=get_admin_keyboard())
        return

    if data == "add_ch_start":
        await query.answer()
        admin_states[user_id] = "channel_add"
        await context.bot.send_message(chat_id=user_id, text="📢 Kanalni formatda yuboring:\n`@username Kanal nomi`", reply_markup=get_cancel_keyboard())
        return

    if data.startswith("edit_name_") or data.startswith("edit_desc_") or data.startswith("edit_poster_") or data.startswith("edit_vid_"):
        await query.answer()
        parts = data.split("_", 2)
        admin_states[user_id] = f"edit_field_{parts[1]}_{parts[2]}"
        await context.bot.send_message(chat_id=user_id, text="📝 Yangi qiymatni kiriting:", reply_markup=get_cancel_keyboard())
        return

    if data.startswith("edit_cats_"):
        await query.answer()
        code = data.split("_")[2]
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
            save_and_push("movies.json", movies, f"Katalog tahrirlandi")
            movie_cats = movies[code].get("catalogs", [])
            kb = [[InlineKeyboardButton(f"{'✅ ' if cat in movie_cats else ''}{cat}", callback_data=f"tgl_cat_{code}_{i}")] for i, cat in enumerate(catalogs)]
            kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"edit_back_{code}")])
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("edit_gnrs_"):
        await query.answer()
        code = data.split("_")[2]
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
            save_and_push("movies.json", movies, f"Janr tahrirlandi")
            movie_gnrs = movies[code].get("genres", [])
            kb = [[InlineKeyboardButton(f"{'✅ ' if gen in movie_gnrs else ''}{gen}", callback_data=f"tgl_gen_{code}_{i}")] for i, gen in enumerate(genres)]
            kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"edit_back_{code}")])
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("edit_back_"):
        await query.answer()
        code = data.split("_")[2]
        d_m = movies[code]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📛 Nom", callback_data=f"edit_name_{code}"), InlineKeyboardButton("📝 Ma'lumot", callback_data=f"edit_desc_{code}")], [InlineKeyboardButton("🖼 Poster", callback_data=f"edit_poster_{code}"), InlineKeyboardButton("📥 Video ID", callback_data=f"edit_vid_{code}")], [InlineKeyboardButton("📂 Kataloglar (Boshqarish)", callback_data=f"edit_cats_{code}")], [InlineKeyboardButton("🎭 Janrlar (Boshqarish)", callback_data=f"edit_gnrs_{code}")], [InlineKeyboardButton("❌ Chiqish (Tayyor)", callback_data="cancel_edit")]])
        await query.message.edit_text(f"✏️ '{d_m.get('name', code)}' — nimani tahrirlaysiz?", reply_markup=kb)
        return

    if data == "cancel_edit":
        await query.answer()
        await query.message.edit_text("✅ Tahrirlash tugatildi va saqlandi.", reply_markup=None)
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
            save_and_push("catalogs.json", catalogs, f"Katalog o'chirildi")
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
            save_and_push("genres.json", genres, f"Janr o'chirildi")
            await context.bot.send_message(chat_id=user_id, text=f"✅ Janr o'chirildi: {removed}", reply_markup=get_admin_keyboard())
        return

    if data == "edit_start":
        await query.answer()
        admin_states[user_id] = "edit_start_text"
        await context.bot.send_message(chat_id=user_id, text="📝 Yangi start xabarini yuboring (Rasm, GIF yoki oddiy Matn bo'lishi mumkin):", reply_markup=get_cancel_keyboard())
        return

    # KINO QO'SHISH YAKUNIY BOSQICHI (SO'ROVSIZ FULL TUGAYDI)
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
            if user_id in new_movie_wizard and catalogs[idx] not in new_movie_wizard[user_id]["catalogs"]:
                new_movie_wizard[user_id]["catalogs"].append(catalogs[idx])
                await query.answer(f"➕ Qo'shildi")
        return

    if data.startswith("wiz_gen_"):
        await query.answer()
        val = data.replace("wiz_gen_", "")
        if val == "done":
            wiz = new_movie_wizard.pop(user_id, None)
            if wiz:
                code = wiz["code"]
                movies[code] = {"name": wiz["name"], "desc": wiz["desc"], "poster": wiz["poster"], "video_id": wiz["video_id"], "catalogs": wiz["catalogs"], "genres": wiz["genres"]}
                save_and_push("movies.json", movies, f"Yangi kino qo'shildi: {code}")
                admin_states[user_id] = None
                await query.message.edit_text(f"🎉 '{wiz['name']}' kinosi muvaffaqiyatli saqlandi va jarayon yakunlandi!", reply_markup=get_admin_keyboard())
        else:
            idx = int(val)
            if user_id in new_movie_wizard and genres[idx] not in new_movie_wizard[user_id]["genres"]:
                new_movie_wizard[user_id]["genres"].append(genres[idx])
                await query.answer(f"➕ Qo'shildi")
        return

    if data == "broadcast_confirm":
        await query.answer()
        text_to_send = context.user_data.get("broadcast_text")
        if text_to_send:
            await query.message.edit_text("🚀 Xabar yuborilmoqda...")
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
        await query.message.delete()
        return

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None: pass

def run_fake_server():
    server = HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), SimpleHTTPRequestHandler)
    server.serve_forever()

def keep_alive_loop():
    if not RENDER_EXTERNAL_URL: return
    while True:
        threading.Event().wait(240)
        try: requests.get(RENDER_EXTERNAL_URL, timeout=10)
        except Exception: pass

def main():
    load_data()
    if not TOKEN: 
        print("XATO: TOKEN topilmadi!")
        return
    
    # Soxta serverni Render portni tekshirishidan oldin tayyorlash
    print("Soxta server ishga tushmoqda...")
    threading.Thread(target=run_fake_server, daemon=True).start()

    # Avto-bekap oqimi
    threading.Thread(target=auto_backup_loop, daemon=True).start()

    # Keep-alive oqimi
    threading.Thread(target=keep_alive_loop, daemon=True).start()
    
    print("Telegram Bot ulanmoqda...")
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    app.run_polling()

if __name__ == "__main__":
    main()
