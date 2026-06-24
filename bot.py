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

ratings = {}        
part_progress = {}  

_pending_saves = {}      
_pending_saves_lock = threading.Lock()

bot_settings = {
    "protect_content": True,
    "start_media_type": "text",
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
        try: flush_pending_saves()
        except Exception: pass

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
    save_and_push("ratings.json", ratings, f"Reyting yangilandi")

def get_avg_rating(movie_code):
    scores = ratings.get(movie_code, {})
    if not scores: return 0.0, 0
    vals = list(scores.values())
    return sum(vals) / len(vals), len(vals)

def get_user_rating(movie_code, user_id):
    return ratings.get(movie_code, {}).get(str(user_id))

# ==================== SAHIFALASH ====================
TOP_RATED_PAGE_SIZE = 10

def get_sorted_top_rated():
    scored = []
    for code in movies:
        avg, count = get_avg_rating(code)
        if count > 0: scored.append((code, avg, count))
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
    if row: kb.append(row)

    nav_row = []
    if start > 0: nav_row.append(InlineKeyboardButton("◀️ Oldingi", callback_data=f"{prefix}_page_{page-1}"))
    if end < len(scored): nav_row.append(InlineKeyboardButton("Keyingi ▶️", callback_data=f"{prefix}_page_{page+1}"))
    if nav_row: kb.append(nav_row)

    kb.append([InlineKeyboardButton("🏠 Asosiy menu", callback_data="go_to_main_menu")])
    return InlineKeyboardMarkup(kb), page_items, start

async def show_top_rated_page(message, bot, page, edit=False):
    scored = get_sorted_top_rated()
    if not scored:
        text = "⭐ Hali hech qanday kino baholanmagan."
        kb_menu = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Asosiy menu", callback_data="go_to_main_menu")]])
        if edit: await message.edit_text(text, reply_markup=kb_menu)
        else: await bot.send_message(chat_id=message.chat_id, text=text, reply_markup=kb_menu)
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

async def show_saved_movies_page(chat_id, bot, page, edit=False, message=None):
    uid_str = str(chat_id)
    saved = saved_movies.get(uid_str, [])
    valid = [c for c in saved if c in movies]
    
    if not valid:
        text = "❤️ Siz hali hech qanday kino saqlamagansiz.\n\nKinoni ko'rayotganda '❤️ Saqlash' tugmasini bosing!"
        kb_menu = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Asosiy menu", callback_data="go_to_main_menu")]])
        if edit and message: await message.edit_text(text, reply_markup=kb_menu)
        else: await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb_menu)
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
    caption = f"🎬 {name}\n¼ {desc}\n👁 {vc} marta ko'rilgan\n⭐ Reyting: {avg:.1f}/5 ({count}ta ovoz)\n🔑 Kod: {movie_code}"
    try:
        if poster and poster.startswith("http"): await bot.send_photo(chat_id=chat_id, photo=poster, caption=caption, reply_markup=kb)
        else: await bot.send_message(chat_id=chat_id, text=caption, reply_markup=kb)
    except Exception: await bot.send_message(chat_id=chat_id, text=caption, reply_markup=kb)

# ==================== QISMLI KINO ====================
def get_video_ids(data):
    video_ids_raw = data.get("video_id") if isinstance(data, dict) else data
    if isinstance(video_ids_raw, str): return [v.strip() for v in video_ids_raw.split(",") if v.strip()]
    elif isinstance(video_ids_raw, list): return video_ids_raw
    return [str(video_ids_raw)]

def get_part_progress_key(user_id, movie_code): return f"{user_id}_{movie_code}"

# ==================== KLAVIATURALAR ====================
def get_user_inline_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Qidiruv", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("📂 Katalog", callback_data="user_show_catalogs"), InlineKeyboardButton("🎭 Janr", callback_data="user_show_genres")],
        [InlineKeyboardButton("🔥 Top kinolar", switch_inline_query_current_chat="top"), InlineKeyboardButton("❤️ Saqlanganlar", callback_data="my_saved")],
        [InlineKeyboardButton("🎲 Tasodifiy kino", callback_data="random_movie"), InlineKeyboardButton("⭐ Top baholangan", callback_data="top_rated")]
    ])

def get_admin_keyboard():
    return ReplyKeyboardMarkup([
        ["➕ Kino qo'shish", "✏️ Kino tahrirlash"],
        ["🗑️ Kino o'chirish", "📋 Kinolar ro'yxati"],
        ["📈 Top kinolar", "📁 Katalog/Janr"],
        ["📊 Statistika", "📢 Reklama xabar"],
        ["📣 Hammaga xabar", "⚙️ Bot Sozlamalari"]
    ], resize_keyboard=True)

def get_cancel_keyboard(): return ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)
def get_return_main_keyboard(): return ReplyKeyboardMarkup([["🏠 Asosiy panelga qaytish"]], resize_keyboard=True)

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
        except Exception: url = f"https://t.me/{str(ch_id).replace('@', '')}"
        keyboard.append([InlineKeyboardButton(f"📢 {ch_name}", url=url)])
    keyboard.append([InlineKeyboardButton("✅ Tekshirish", callback_data="check")])
    return InlineKeyboardMarkup(keyboard)

async def send_welcome_message(chat_id, bot, first_name):
    media_type = bot_settings.get("start_media_type", "text")
    file_id = bot_settings.get("start_file_id")
    text = bot_settings.get("start_text", "").format(name=first_name)
    kb = get_user_inline_keyboard()
    try:
        if media_type == "photo" and file_id: await bot.send_photo(chat_id=chat_id, photo=file_id, caption=text, reply_markup=kb)
        elif media_type == "animation" and file_id: await bot.send_animation(chat_id=chat_id, animation=file_id, caption=text, reply_markup=kb)
        else: await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
    except Exception: await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)

# ==================== KINO YUBORISH ====================
async def send_movie(chat_id, movie_code, bot):
    global ad_post_id, bot_settings
    if movie_code not in movies: return False
    data = movies[movie_code]
    video_ids = get_video_ids(data)

    if len(video_ids) > 1: return await send_movie_part(chat_id, movie_code, 0, bot)

    protect = False if is_admin(chat_id) else bot_settings.get("protect_content", True)
    movie_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Film qidirish", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("❤️ Saqlash", callback_data=f"save_{movie_code}"), InlineKeyboardButton("🏠 Bosh menyu", callback_data="go_to_main_menu")],
        [InlineKeyboardButton("⭐ Baholash", callback_data=f"rate_menu_{movie_code}")]
    ])

    success = False
    for vid in video_ids:
        try:
            await bot.copy_message(chat_id=chat_id, from_chat_id=SOURCE_CHANNEL, message_id=int(vid), reply_markup=movie_kb, protect_content=protect)
            success = True
        except Exception: pass

    if not success: return False
    if not is_admin(chat_id): increment_views(movie_code)
    if ad_post_id and not is_admin(chat_id):
        try: await bot.copy_message(chat_id=chat_id, from_chat_id=SOURCE_CHANNEL, message_id=int(ad_post_id), protect_content=True)
        except Exception: pass
    return True

# ==================== QISMLI KINO NAVIGATSIYA ====================
def build_part_nav_keyboard(movie_code, part_index, total_parts):
    nav_row = []
    if part_index > 0: nav_row.append(InlineKeyboardButton("◀️ Oldingi qism", callback_data=f"part_{movie_code}_{part_index-1}"))
    if part_index < total_parts - 1: nav_row.append(InlineKeyboardButton("Keyingi qism ▶️", callback_data=f"part_{movie_code}_{part_index+1}"))
    rows = []
    if nav_row: rows.append(nav_row)
    rows.append([InlineKeyboardButton(f"📋 Qismlar ({part_index+1}/{total_parts})", callback_data=f"partlist_{movie_code}")])
    rows.append([InlineKeyboardButton("❤️ Saqlash", callback_data=f"save_{movie_code}"), InlineKeyboardButton("🏠 Bosh menyu", callback_data="go_to_main_menu")])
    rows.append([InlineKeyboardButton("⭐ Baholash", callback_data=f"rate_menu_{movie_code}")])
    return InlineKeyboardMarkup(rows)

def build_parts_list_keyboard(movie_code, total_parts):
    kb = []
    row = []
    for i in range(total_parts):
        row.append(InlineKeyboardButton(str(i + 1), callback_data=f"part_{movie_code}_{i}"))
        if len(row) == 5: kb.append(row); row = []
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

    try: await bot.copy_message(chat_id=chat_id, from_chat_id=SOURCE_CHANNEL, message_id=int(vid), reply_markup=kb, protect_content=protect)
    except Exception: return False

    part_progress[get_part_progress_key(chat_id, movie_code)] = part_index
    queue_save("part_progress.json", part_progress, "Qism progressi yangilandi")
    if not is_admin(chat_id) and part_index == 0: increment_views(movie_code)
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    track_user(user_id)
    if is_admin(user_id):
        admin_states[user_id] = None
        await update.message.reply_text("👑 Admin boshqaruv paneli:", reply_markup=get_admin_keyboard())
        return
    if not await is_joined(context.bot, user_id):
        await update.message.reply_text("❗ Botdan foydalanish uchun kanallarga qo'shiling!", reply_markup=await get_subscription_keyboard(context.bot))
        return
    await send_welcome_message(user_id, context.bot, update.effective_user.first_name)

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    user_id = update.inline_query.from_user.id
    if not await is_joined(context.bot, user_id):
        await update.inline_query.answer([], switch_pm_text="📢 Avval kanallarga obuna bo'ling", switch_pm_parameter="start", cache_time=0)
        return

    filter_type, filter_value = None, None
    if query.startswith("katalog:"): filter_type = "catalog"; filter_value = query.replace("katalog:", "").strip().lower()
    elif query.startswith("janr:"): filter_type = "genre"; filter_value = query.replace("janr:", "").strip().lower()
    elif query == "top": filter_type = "top"

    results = []
    for code, data in reversed(list(movies.items())):
        name = data.get("name", "") if isinstance(data, dict) else f"Kino {code}"
        desc = data.get("desc", "") if isinstance(data, dict) else ""
        poster = data.get("poster") if isinstance(data, dict) else None
        movie_cats = [c.lower() for c in data.get("catalogs", [])] if isinstance(data, dict) else []
        movie_gnrs = [g.lower() for g in data.get("genres", [])] if isinstance(data, dict) else []

        match = False
        if filter_type == "catalog": match = (filter_value in movie_cats)
        elif filter_type == "genre": match = (filter_value in movie_gnrs)
        elif filter_type == "top": match = True
        else: match = (not query or query in name.lower() or query in str(code).lower())

        if match:
            results.append(InlineQueryResultArticle(
                id=code, title=f"🎬 {name.upper()}", description=f"🔑 Kod: {code} | {desc}",
                thumbnail_url=poster if (poster and poster.startswith("http")) else None,
                input_message_content=InputTextMessageContent(message_text=str(code))
            ))
    if filter_type == "top": results.sort(key=lambda r: views.get(r.id, 0), reverse=True)
    await update.inline_query.answer(results[:50], cache_time=0)

# ==================== MATN VA MEDIA XABARLARI ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ad_post_id, bot_settings, catalogs, genres, movies, admins, channels
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""

    if text in ["❌ Bekor qilish", "🏠 Asosiy panelga qaytish"]:
        admin_states[user_id] = None
        if is_admin(user_id): await update.message.reply_text("🏠 Admin paneli:", reply_markup=get_admin_keyboard())
        else: await send_welcome_message(user_id, context.bot, update.effective_user.first_name)
        return

    if not is_admin(user_id):
        if not await is_joined(context.bot, user_id):
            await update.message.reply_text("❗ Avval kanallarga obuna bo'ling!", reply_markup=await get_subscription_keyboard(context.bot))
            return
        if text and await send_movie(update.effective_chat.id, text, context.bot): return
        await update.message.reply_text("❌ Bunday kodli kino topilmadi.")
        return

    state = admin_states.get(user_id)

    if state == "add_admin_id":
        if not text.lstrip("-").isdigit():
            await update.message.reply_text("❌ ID faqat raqamdan iborat bo'ladi:", reply_markup=get_cancel_keyboard())
            return
        new_id = int(text)
        admins.add(new_id)
        save_and_push("admins.json", list(admins), "Admin qo'shildi")
        admin_states[user_id] = None
        await update.message.reply_text(f"✅ ID: {new_id} muvaffaqiyatli admin qilindi!", reply_markup=get_admin_keyboard())
        return

    if state == "channel_add":
        parts = text.split(" ", 1)
        if len(parts) < 2 or not parts[0].lstrip("-").isdigit():
            await update.message.reply_text("❌ Format xato! Faqat: `KanalID KanalNomi` ko'rinishida yuboring (Masalan: `-10022334455 Premium Kanal`):", reply_markup=get_cancel_keyboard())
            return
        channels[parts[0].strip()] = parts[1].strip()
        save_and_push("channels.json", channels, "Kanal qo'shildi")
        admin_states[user_id] = None
        await update.message.reply_text("✅ Majburiy obuna kanali ID orqali qo'shildi!", reply_markup=get_admin_keyboard())
        return

    if state == "edit_start_text":
        if update.message.photo:
            bot_settings["start_media_type"], bot_settings["start_file_id"] = "photo", update.message.photo[-1].file_id
            bot_settings["start_text"] = update.message.caption or ""
        elif update.message.animation:
            bot_settings["start_media_type"], bot_settings["start_file_id"] = "animation", update.message.animation.file_id
            bot_settings["start_text"] = update.message.caption or ""
        else:
            bot_settings["start_media_type"], bot_settings["start_file_id"] = "text", None
            bot_settings["start_text"] = text
        save_and_push("settings.json", bot_settings, "Start xabari o'zgardi")
        admin_states[user_id] = None
        await update.message.reply_text("✅ Start xabari muvaffaqiyatli saqlandi!", reply_markup=get_admin_keyboard())
        return

    if state == "delete_movie_by_code":
        code = text.lower()
        if code in movies:
            del movies[code]
            views.pop(code, None)
            save_and_push("movies.json", movies, "Kino o'chirildi")
            admin_states[user_id] = None
            await update.message.reply_text("✅ Kino muvaffaqiyatli o'chirildi!", reply_markup=get_admin_keyboard())
        else: await update.message.reply_text("❌ Topilmadi, qayta yuboring:", reply_markup=get_cancel_keyboard())
        return

    if state == "add_movie_text":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) < 5:
            await update.message.reply_text("❌ Kamida 5 qator shart! Qayta kiriting:", reply_markup=get_cancel_keyboard())
            return
        new_movie_wizard[user_id] = {"name": lines[0], "desc": lines[1], "code": lines[2].lower(), "poster": lines[3], "video_id": lines[4], "catalogs": [], "genres": []}
        admin_states[user_id] = "add_movie_catalog"
        kb = [[InlineKeyboardButton(cat, callback_data=f"wiz_cat_{i}")] for i, cat in enumerate(catalogs)]
        kb.append([InlineKeyboardButton("➡️ Keyingi (Janr)", callback_data="wiz_cat_done")])
        await update.message.reply_text("🗂 Katalog tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if state == "edit_movie_select":
        code = text.lower()
        if code not in movies:
            await update.message.reply_text("❌ Bunday kod topilmadi:", reply_markup=get_cancel_keyboard())
            return
        admin_states[user_id] = None
        d = movies[code]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📛 Nom", callback_data=f"edit_name_{code}"), InlineKeyboardButton("📝 Ma'lumot", callback_data=f"edit_desc_{code}")],
            [InlineKeyboardButton("🖼 Poster", callback_data=f"edit_poster_{code}"), InlineKeyboardButton("📥 Video ID", callback_data=f"edit_vid_{code}")],
            [InlineKeyboardButton("❌ Chiqish", callback_data="cancel_edit")]
        ])
        await update.message.reply_text(f"✏️ Tahrirlash: {d.get('name', code).upper()}", reply_markup=kb)
        return

    if state and state.startswith("edit_field_"):
        parts = state.split("_", 3)
        field, code = parts[2], parts[3]
        if code in movies:
            if field == "name": movies[code]["name"] = text
            elif field == "desc": movies[code]["desc"] = text
            elif field == "poster": movies[code]["poster"] = text
            elif field == "vid": movies[code]["video_id"] = text
            save_and_push("movies.json", movies, "Kino tahrirlandi")
            admin_states[user_id] = None
            await update.message.reply_text("✅ Muvaffaqiyatli yangilandi!", reply_markup=get_admin_keyboard())
        return

    if state == "broadcast":
        context.user_data["broadcast_text"] = text
        admin_states[user_id] = None
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yuborish", callback_data="broadcast_confirm"), InlineKeyboardButton("❌ Bekor", callback_data="cancel_broadcast")]])
        await update.message.reply_text(f"📣 {len(users)} ta odamga yuborilsinmi?", reply_markup=kb)
        return

    if state == "set_ad":
        ad_post_id = None if text == "0" else text
        save_and_push("ad_post.json", {"id": ad_post_id}, "Reklama yangilandi")
        admin_states[user_id] = None
        await update.message.reply_text("✅ Reklama sozlamasi saqlandi!", reply_markup=get_admin_keyboard())
        return

    # ADMIN TUGMALARI
    if text == "➕ Kino qo'shish": admin_states[user_id] = "add_movie_text"; await update.message.reply_text("➕ 5 qatorli shablonni kiriting:\nNomi\nTavsif\nKod\nPosterLink\nPostID", reply_markup=get_cancel_keyboard()); return
    if text == "✏️ Kino tahrirlash": admin_states[user_id] = "edit_movie_select"; await update.message.reply_text("🔑 Kino kodini yuboring:", reply_markup=get_cancel_keyboard()); return
    if text == "🗑️ Kino o'chirish": admin_states[user_id] = "delete_movie_by_code"; await update.message.reply_text("🔑 O'chirish uchun kino kodini kiriting:", reply_markup=get_cancel_keyboard()); return
    if text == "📋 Kinolar ro'yxati": await update.message.reply_text("\n".join([f"🔑 {c} — {d.get('name', c).upper()}" for c, d in movies.items()][:60]) or "Baza bo'sh."); return
    if text == "📈 Top kinolar": await update.message.reply_text("\n".join([f"{code} — 👁 {v}" for code, v in sorted(views.items(), key=lambda x: x[1], reverse=True)[:10]]) or "Ko'rishlar yo'q."); return
    if text == "📊 Statistika": await update.message.reply_text(f"📊 Jami a'zolar: {len(users)}\n🎬 Jami kinolar: {len(movies)}\n👁 Jami ko'rishlar: {sum(views.values())}"); return
    if text == "📢 Reklama xabar": admin_states[user_id] = "set_ad"; await update.message.reply_text("Reklama Post ID kiriting (o'chirish uchun 0):", reply_markup=get_cancel_keyboard()); return
    if text == "📣 Hammaga xabar": admin_states[user_id] = "broadcast"; await update.message.reply_text("Yuboriladigan xabarni kiriting:", reply_markup=get_cancel_keyboard()); return
    
    if text == "⚙️ Bot Sozlamalari":
        status_str = "TAQIQLANGAN 🔒" if bot_settings.get("protect_content", True) else "OCHIQ 🔓"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Start xabarini o'zgartirish", callback_data="edit_start")],
            [InlineKeyboardButton("📢 Majburiy kanallar", callback_data="manage_ch")],
            [InlineKeyboardButton("👥 Adminlarni boshqarish", callback_data="manage_admins")],
            [InlineKeyboardButton(f"🔒 Uzatish cheklovi: {status_str}", callback_data="toggle_protect")]
        ])
        await update.message.reply_text("⚙️ Bot boshqaruv va sozlamalar bo'limi:", reply_markup=kb)
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
        if movies: import random; await send_movie(user_id, random.choice(list(movies.keys())), context.bot)
        return

    if data == "top_rated" or data.startswith("toprated_page_"):
        await query.answer()
        await show_top_rated_page(query.message, context.bot, int(data.replace("toprated_page_", "")) if data.startswith("toprated_page_") else 0, edit=data.startswith("toprated_page_"))
        return

    if data.startswith("toprated_open_") or data.startswith("mysaved_open_"):
        await query.answer()
        code = data.replace("toprated_open_", "").replace("mysaved_open_", "")
        if data.startswith("mysaved_open_"): await show_saved_movie_detail(user_id, context.bot, code)
        else: await send_movie(user_id, code, context.bot)
        return

    if data == "my_saved" or data.startswith("mysaved_page_"):
        await query.answer()
        await show_saved_movies_page(user_id, context.bot, int(data.replace("mysaved_page_", "")) if data.startswith("mysaved_page_") else 0, edit=data.startswith("mysaved_page_"), message=query.message)
        return

    if data.startswith("rate_menu_"):
        await query.answer()
        movie_code = data.replace("rate_menu_", "")
        
        # BAHOLASH CHEKLOVI: Oldin baholagan bo'lsa ogohlantirish
        old_score = ratings.get(movie_code, {}).get(str(user_id))
        if old_score:
            await query.answer(f"⚠️ Siz ushbu kinoga allaqachon {old_score} ball bergansiz!", show_alert=True)
            return

        kb_row = [InlineKeyboardButton(f"{i} ⭐", callback_data=f"rate_{movie_code}_{i}") for i in range(1, 6)]
        await context.bot.send_message(chat_id=user_id, text="⭐ Ushbu kinoga baho bering (1-5):", reply_markup=InlineKeyboardMarkup([kb_row]))
        return

    if data.startswith("rate_") and not data.startswith("rate_menu_"):
        rest = data[len("rate_"):]
        movie_code, _, score_str = rest.rpartition("_")
        
        old_score = ratings.get(movie_code, {}).get(str(user_id))
        if old_score:
            await query.message.delete()
            await query.answer(f"⚠️ Siz ushbu kinoga allaqachon {old_score} ball bergansiz!", show_alert=True)
            return

        set_rating(movie_code, user_id, int(score_str))
        await query.message.delete()
        await query.answer(f"✅ Rahmat! Kinoga {score_str}/5 ball berildi.", show_alert=True)
        return

    if data == "check":
        if await is_joined(context.bot, user_id): await query.answer("✅ Rahmat!"); await query.message.delete(); await send_welcome_message(user_id, context.bot, query.from_user.first_name)
        else: await query.answer("❌ Obuna bo'lmadingiz!", show_alert=True)
        return

    if data == "go_to_main_menu":
        await query.answer()
        await send_welcome_message(user_id, context.bot, query.from_user.first_name)
        return

    if data.startswith("watch_"): await query.answer(); await send_movie(user_id, data.split("_")[1], context.bot); return
    
    if data.startswith("unsave_"):
        movie_code = data.split("_")[1]
        if str(user_id) in saved_movies and movie_code in saved_movies[str(user_id)]:
            saved_movies[str(user_id)].remove(movie_code)
            save_and_push("saved_movies.json", saved_movies, "Saqlangan o'chirildi")
        await query.answer("🗑️ Ro'yxatdan o'chirildi!", show_alert=True)
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
        else: await query.answer("✨ Oldindan saqlangan!", show_alert=True)
        return

    if data == "user_show_catalogs":
        await query.answer()
        kb = [[InlineKeyboardButton(c, switch_inline_query_current_chat=f"katalog:{c}")] for c in catalogs]
        kb.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="go_to_main_menu")])
        await query.message.edit_text("📂 Katalogni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "user_show_genres":
        await query.answer()
        kb = [[InlineKeyboardButton(g, switch_inline_query_current_chat=f"janr:{g}")] for g in genres]
        kb.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="go_to_main_menu")])
        await query.message.edit_text("🎭 Janrni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if not is_admin(user_id): return

    # ADMIN MANAGEMENT CALLBACKS
    if data == "toggle_protect":
        bot_settings["protect_content"] = not bot_settings.get("protect_content", True)
        save_and_push("settings.json", bot_settings, "Protect content holati o'zgartirildi")
        status_str = "TAQIQLANGAN 🔒" if bot_settings["protect_content"] else "OCHIQ 🔓"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Start xabarini o'zgartirish", callback_data="edit_start")],
            [InlineKeyboardButton("📢 Majburiy kanallar", callback_data="manage_ch")],
            [InlineKeyboardButton("👥 Adminlarni boshqarish", callback_data="manage_admins")],
            [InlineKeyboardButton(f"🔒 Uzatish cheklovi: {status_str}", callback_data="toggle_protect")]
        ])
        await query.message.edit_reply_markup(reply_markup=kb)
        await query.answer("✅ Uzatish sozlamasi o'zgartirildi!", show_alert=True)
        return

    if data == "manage_admins":
        await query.answer()
        kb = [[InlineKeyboardButton(f"🗑️ O'chirish: {adm_id}", callback_data=f"del_admin_{adm_id}")] for adm_id in admins if adm_id != ADMIN_ID]
        kb.append([InlineKeyboardButton("➕ Admin qo'shish", callback_data="add_admin_start")])
        kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data="go_to_settings")])
        await query.message.edit_text(f"👥 Jami adminlar: {len(admins)} ta\n\nBoshqarish:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "add_admin_start":
        await query.answer()
        admin_states[user_id] = "add_admin_id"
        await context.bot.send_message(chat_id=user_id, text="➕ Yangi adminning Telegram ID raqamini kiriting:", reply_markup=get_cancel_keyboard())
        return

    if data.startswith("del_admin_"):
        await query.answer()
        adm_id = int(data.replace("del_admin_", ""))
        admins.discard(adm_id)
        save_and_push("admins.json", list(admins), "Admin o'chirildi")
        await query.message.delete()
        await context.bot.send_message(chat_id=user_id, text="✅ Admin muvaffaqiyatli o'chirildi!", reply_markup=get_admin_keyboard())
        return

    if data == "manage_ch":
        await query.answer()
        kb = [[InlineKeyboardButton(f"🗑️ {name} ({ch_id})", callback_data=f"del_ch_{ch_id}")] for ch_id, name in channels.items()]
        kb.append([InlineKeyboardButton("➕ Kanal qo'shish (ID orqali)", callback_data="add_ch_start")])
        kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data="go_to_settings")])
        await query.message.edit_text("📢 Majburiy obuna kanallari (O'chirish uchun kanal ustiga bosing):", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "add_ch_start":
        await query.answer()
        admin_states[user_id] = "channel_add"
        await context.bot.send_message(chat_id=user_id, text="📢 Kanalni quyidagi formatda yuboring:\n`KanalID KanalNomi` (Masalan: `-100123456789 Premium_Kino`):", reply_markup=get_cancel_keyboard())
        return

    if data.startswith("del_ch_"):
        await query.answer()
        ch_id = data.replace("del_ch_", "")
        if ch_id in channels:
            channels.pop(ch_id)
            save_and_push("channels.json", channels, "Kanal o'chirildi")
        await query.message.delete()
        await context.bot.send_message(chat_id=user_id, text="✅ Majburiy kanal muvaffaqiyatli olib tashlandi!", reply_markup=get_admin_keyboard())
        return

    if data == "go_to_settings":
        await query.answer()
        status_str = "TAQIQLANGAN 🔒" if bot_settings.get("protect_content", True) else "OCHIQ 🔓"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Start xabarini o'zgartirish", callback_data="edit_start")],
            [InlineKeyboardButton("📢 Majburiy kanallar", callback_data="manage_ch")],
            [InlineKeyboardButton("👥 Adminlarni boshqarish", callback_data="manage_admins")],
            [InlineKeyboardButton(f"🔒 Uzatish cheklovi: {status_str}", callback_data="toggle_protect")]
        ])
        await query.message.edit_text("⚙️ Bot boshqaruv va sozlamalar bo'limi:", reply_markup=kb)
        return

    if data == "edit_start":
        await query.answer()
        admin_states[user_id] = "edit_start_text"
        await context.bot.send_message(chat_id=user_id, text="📝 Yangi start matnini yoki rasmini yuboring:", reply_markup=get_cancel_keyboard())
        return

    if data.startswith("wiz_cat_"):
        await query.answer()
        val = data.replace("wiz_cat_", "")
        if val == "done":
            admin_states[user_id] = "add_movie_genre"
            kb = [[InlineKeyboardButton(g, callback_data=f"wiz_gen_{i}")] for i, g in enumerate(genres)]
            kb.append([InlineKeyboardButton("💾 Saqlash", callback_data="wiz_gen_done")])
            await query.message.edit_text("🎭 Janr tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        else:
            idx = int(val)
            if user_id in new_movie_wizard and catalogs[idx] not in new_movie_wizard[user_id]["catalogs"]:
                new_movie_wizard[user_id]["catalogs"].append(catalogs[idx])
                await query.answer(f"➕ {catalogs[idx]} qo'shildi")
        return

    if data.startswith("wiz_gen_"):
        await query.answer()
        val = data.replace("wiz_gen_", "")
        if val == "done":
            wiz = new_movie_wizard.pop(user_id, None)
            if wiz:
                code = wiz["code"]
                movies[code] = {"name": wiz["name"], "desc": wiz["desc"], "poster": wiz["poster"], "video_id": wiz["video_id"], "catalogs": wiz["catalogs"], "genres": wiz["genres"]}
                save_and_push("movies.json", movies, f"Kino qo'shildi: {code}")
                admin_states[user_id] = None
                await query.message.edit_text("🎉 Kino muvaffaqiyatli qo'shildi!", reply_markup=get_admin_keyboard())
        else:
            idx = int(val)
            if user_id in new_movie_wizard and genres[idx] not in new_movie_wizard[user_id]["genres"]:
                new_movie_wizard[user_id]["genres"].append(genres[idx])
                await query.answer(f"➕ {genres[idx]} qo'shildi")
        return

    if data == "broadcast_confirm":
        await query.answer()
        text_to_send = context.user_data.get("broadcast_text")
        if text_to_send:
            await query.message.edit_text("🚀 Yuborilmoqda...")
            for uid in list(users):
                try: await context.bot.send_message(chat_id=uid, text=text_to_send)
                except Exception: pass
            await context.bot.send_message(chat_id=user_id, text="📊 Tugadi!", reply_markup=get_admin_keyboard())
        return

    if data == "cancel_broadcast" or data == "cancel_edit": await query.answer(); await query.message.delete(); return

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
    if not TOKEN: return
    threading.Thread(target=run_fake_server, daemon=True).start()
    threading.Thread(target=auto_backup_loop, daemon=True).start()
    threading.Thread(target=keep_alive_loop, daemon=True).start()
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
