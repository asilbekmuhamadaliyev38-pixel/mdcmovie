import os
import base64
import requests
import json
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, InlineQueryHandler, ContextTypes, filters
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

def auto_backup_loop():
    while True:
        threading.Event().wait(60)
        try: flush_pending_saves()
        except: pass

# ==================== MA'LUMOT YUKLASH ====================
def load_data():
    global admins, movies, channels, catalogs, genres, users, active_users, deleted_users, ad_post_id, bot_settings
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
    queue_save("views.json", views, "Ko'rishlar yangilandi")

def is_admin(user_id): return user_id in admins

# ==================== REYTING ====================
def set_rating(movie_code, user_id, score):
    if movie_code not in ratings: ratings[movie_code] = {}
    ratings[movie_code][str(user_id)] = score
    queue_save("ratings.json", ratings, f"Reyting yangilandi: {movie_code}")

def get_avg_rating(movie_code):
    scores = ratings.get(movie_code, {})
    if not scores: return 0.0, 0
    vals = list(scores.values())
    return sum(vals) / len(vals), len(vals)

# ==================== TOP VA SAQLANGANLAR ====================
TOP_RATED_PAGE_SIZE = 10

def build_top_rated_keyboard(items, page, prefix="toprated"):
    start = page * TOP_RATED_PAGE_SIZE
    end = start + TOP_RATED_PAGE_SIZE
    page_items = items[start:end]
    kb = []
    row = []
    for offset, item in enumerate(page_items):
        code = item if isinstance(item, str) else item[0]
        num = start + offset + 1
        row.append(InlineKeyboardButton(str(num), callback_data=f"{prefix}_open_{code}"))
        if len(row) == 5:
            kb.append(row)
            row = []
    if row: kb.append(row)

    nav = []
    if start > 0: nav.append(InlineKeyboardButton("◀️ Oldingi", callback_data=f"{prefix}_page_{page-1}"))
    if end < len(items): nav.append(InlineKeyboardButton("Keyingi ▶️", callback_data=f"{prefix}_page_{page+1}"))
    if nav: kb.append(nav)
    return InlineKeyboardMarkup(kb), page_items, start

async def show_top_rated_page(message, bot, page=0, edit=False):
    scored = []
    for code in movies:
        avg, count = get_avg_rating(code)
        if count > 0:
            scored.append((code, avg, count))
    scored.sort(key=lambda x: (x[1], x[2]), reverse=True)

    if not scored:
        text = "⭐ Hali hech qanday kino baholanmagan."
        if edit: await message.edit_text(text)
        else: await bot.send_message(message.chat_id, text)
        return

    kb, page_items, start = build_top_rated_keyboard(scored, page, "toprated")
    keyboard = kb.inline_keyboard
    keyboard.append([InlineKeyboardButton("🏠 Asosiy menyuga", callback_data="go_to_main_menu")])
    final_kb = InlineKeyboardMarkup(keyboard)

    lines = [f"{start+i+1}. {movies[code].get('name', code).upper()} — {avg:.1f}/5 ({count} ovoz)" for i, (code, avg, count) in enumerate(page_items)]
    text = f"⭐ Top baholangan kinolar ({page+1} sahifa):\n\n" + "\n".join(lines)
    if edit: await message.edit_text(text, reply_markup=final_kb)
    else: await bot.send_message(message.chat_id, text, reply_markup=final_kb)

async def show_saved_movies_page(chat_id, bot, page=0, edit=False, message=None):
    uid_str = str(chat_id)
    saved = [c for c in saved_movies.get(uid_str, []) if c in movies]
    if not saved:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Asosiy menyuga", callback_data="go_to_main_menu")]])
        text = "❤️ Siz hali hech qanday kino saqlamagansiz."
        if edit and message: await message.edit_text(text, reply_markup=kb)
        else: await bot.send_message(chat_id, text, reply_markup=kb)
        return

    kb, page_items, start = build_top_rated_keyboard(saved, page, "mysaved")
    keyboard = kb.inline_keyboard
    keyboard.append([InlineKeyboardButton("🏠 Asosiy menyuga", callback_data="go_to_main_menu")])
    final_kb = InlineKeyboardMarkup(keyboard)

    lines = [f"{start+i+1}. {movies[code].get('name', code).upper()}" for i, code in enumerate(page_items)]
    text = f"❤️ Saqlangan kinolaringiz ({page+1} sahifa):\n\n" + "\n".join(lines)
    if edit and message: await message.edit_text(text, reply_markup=final_kb)
    else: await bot.send_message(chat_id, text, reply_markup=final_kb)

# ==================== QOLGAN QISMLAR (to'liq) ====================
# ==================== QISMLI KINO ====================
def get_video_ids(data):
    video_ids_raw = data.get("video_id") if isinstance(data, dict) else data
    if isinstance(video_ids_raw, str):
        return [v.strip() for v in video_ids_raw.split(",") if v.strip()]
    elif isinstance(video_ids_raw, list):
        return video_ids_raw
    return [str(video_ids_raw)]

def get_part_progress_key(user_id, movie_code):
    return f"{user_id}_{movie_code}"

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
        InlineKeyboardButton("🏠 Asosiy menyuga", callback_data="go_to_main_menu")
    ])
    rows.append([InlineKeyboardButton("⭐ Baholash", callback_data=f"rate_menu_{movie_code}")])
    return InlineKeyboardMarkup(rows)

# ==================== KINO YUBORISH ====================
async def send_movie(chat_id, movie_code, bot):
    if movie_code not in movies: return False
    data = movies[movie_code]
    video_ids = get_video_ids(data)

    if len(video_ids) > 1:
        return await send_movie_part(chat_id, movie_code, 0, bot)

    protect = False if is_admin(chat_id) else bot_settings.get("protect_content", True)

    movie_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Qidiruv", switch_inline_query_current_chat="")],
        [
            InlineKeyboardButton("❤️ Saqlash", callback_data=f"save_{movie_code}"),
            InlineKeyboardButton("🏠 Asosiy menyuga", callback_data="go_to_main_menu")
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

async def send_movie_part(chat_id, movie_code, part_index, bot):
    if movie_code not in movies: return False
    data = movies[movie_code]
    video_ids = get_video_ids(data)
    total_parts = len(video_ids)
    if part_index < 0 or part_index >= total_parts: part_index = 0

    protect = False if is_admin(chat_id) else bot_settings.get("protect_content", True)

    kb = build_part_nav_keyboard(movie_code, part_index, total_parts)

    try:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=SOURCE_CHANNEL,
            message_id=int(video_ids[part_index]),
            reply_markup=kb,
            protect_content=protect
        )
    except Exception: return False

    part_progress[get_part_progress_key(chat_id, movie_code)] = part_index
    queue_save("part_progress.json", part_progress, "Qism progressi yangilandi")

    if not is_admin(chat_id) and part_index == 0:
        increment_views(movie_code)
        if ad_post_id:
            try:
                await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=SOURCE_CHANNEL,
                    message_id=int(ad_post_id),
                    protect_content=True
                )
            except Exception: pass
    return True

# ==================== START VA INLINE ====================
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
            await update.message.reply_text("❗ Kanallarga obuna bo'ling!", reply_markup=await get_subscription_keyboard(context.bot))
        return

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

    results = []
    for code, data in reversed(list(movies.items())):
        name = data.get("name", "") if isinstance(data, dict) else f"Kino {code}"
        if not query or query in name.lower() or query in str(code).lower():
            results.append(InlineQueryResultArticle(
                id=code,
                title=f"🎬 {name.upper()}",
                description=f"Kod: {code}",
                input_message_content=InputTextMessageContent(str(code))
            ))

    if query == "top":
        results.sort(key=lambda r: views.get(r.id, 0), reverse=True)
        results = results[:20]

    await update.inline_query.answer(results[:50], cache_time=0)

# ==================== CALLBACK HANDLER (ENG MUHIMI) ====================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global saved_movies
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    # === BAHOLASH ===
    if data.startswith("rate_menu_"):
        movie_code = data.replace("rate_menu_", "")
        avg, count = get_avg_rating(movie_code)
        kb_row = [InlineKeyboardButton(f"{i}⭐", callback_data=f"rate_{movie_code}_{i}") for i in range(1, 6)]
        await context.bot.send_message(
            chat_id=user_id,
            text=f"⭐ {movie_code} kinosi uchun baho bering\nHozirgi reyting: {avg:.1f}/5 ({count} ovoz)",
            reply_markup=InlineKeyboardMarkup([kb_row])
        )
        return

    if data.startswith("rate_") and not data.startswith("rate_menu_"):
        rest = data[len("rate_"):]
        movie_code, _, score_str = rest.rpartition("_")
        score = int(score_str)
        set_rating(movie_code, user_id, score)
        avg, total = get_avg_rating(movie_code)
        
        await query.answer(f"✅ {score}⭐ baho qabul qilindi!", show_alert=True)
        try:
            await query.message.delete()
        except:
            pass
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Rahmat! {movie_code} uchun yangi o'rtacha baho: **{avg:.1f}/5** ({total} ovoz)",
            parse_mode='Markdown'
        )
        return

    # === SAQLANGANLAR ===
    if data == "my_saved" or data.startswith("mysaved_page_"):
        page = int(data.replace("mysaved_page_", "")) if data.startswith("mysaved_page_") else 0
        await show_saved_movies_page(user_id, context.bot, page, edit=True, message=query.message)
        return

    if data.startswith("toprated_page_") or data == "top_rated":
        page = int(data.replace("toprated_page_", "")) if data.startswith("toprated_page_") else 0
        await show_top_rated_page(query.message, context.bot, page, edit=True)
        return

    if data.startswith("save_"):
        movie_code = data.split("_")[1]
        uid_str = str(user_id)
        if uid_str not in saved_movies: saved_movies[uid_str] = []
        if movie_code not in saved_movies[uid_str]:
            saved_movies[uid_str].append(movie_code)
            queue_save("saved_movies.json", saved_movies, "Kino saqlandi")
            await query.answer("❤️ Saqlandi!", show_alert=True)
        return

    if data.startswith("unsave_"):
        movie_code = data.split("_")[1]
        uid_str = str(user_id)
        if uid_str in saved_movies and movie_code in saved_movies[uid_str]:
            saved_movies[uid_str].remove(movie_code)
            queue_save("saved_movies.json", saved_movies, "Saqlanganlardan o'chirildi")
        await query.answer("🗑️ O'chirildi!", show_alert=True)
        await show_saved_movies_page(user_id, context.bot, 0)
        return

    # === KATALOG VA JANR ===
    if data == "user_show_catalogs":
        kb = [[InlineKeyboardButton(cat, switch_inline_query_current_chat=f"katalog:{cat}")] for cat in catalogs]
        kb.append([InlineKeyboardButton("🏠 Asosiy menyuga", callback_data="go_to_main_menu")])
        await query.message.edit_text("📂 Kerakli katalogni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "user_show_genres":
        kb = [[InlineKeyboardButton(gen, switch_inline_query_current_chat=f"janr:{gen}")] for gen in genres]
        kb.append([InlineKeyboardButton("🏠 Asosiy menyuga", callback_data="go_to_main_menu")])
        await query.message.edit_text("🎭 Kerakli janrni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "go_to_main_menu":
        await send_welcome_message(user_id, context.bot, query.from_user.first_name)
        return

    # Admin callback'lari (kerak bo'lsa qo'shimcha yuboraman)
    if not is_admin(user_id): return
    # ... admin qismi kerak bo'lsa ayting

# ==================== MAIN ====================
def main():
    load_data()
    if not TOKEN: 
        print("TOKEN topilmadi!")
        return
    
    threading.Thread(target=auto_backup_loop, daemon=True).start()
    
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_text))
    
    print("Bot ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()
# ... (Fayl juda uzun bo'lgani uchun qolgan qismini quyida qo'shish uchun alohida yuboraman)

print("Kodning birinchi qismi yuklandi. Davomini yuboraymi yoki to'liq kodni boshqa usulda kerakmi?")
