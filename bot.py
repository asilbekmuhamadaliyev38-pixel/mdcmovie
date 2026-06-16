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
REPO_NAME = os.environ.get("REPO_NAME", "asilbekmuhamadaliyev38-pixel/mega-film-uz")

# ==================== MA'LUMOTLAR ====================
admins = set()
movies = {}
channels = {}
users = set()
daily_users = {}
admin_states = {}
new_movies_temp = {}
ad_post_id = None
bot_settings = {"protect_content": True} # Standart holatda uzatish yopiq

# ==================== GITHUB ====================
def github_get(filename):
    if not GITHUB_TOKEN:
        return None
    try:
        url = f"https://api.github.com/repos/{REPO_NAME}/contents/{filename}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        res = requests.get(url, headers=headers, timeout=10).json()
        if "content" in res:
            return json.loads(base64.b64decode(res["content"]).decode("utf-8"))
    except Exception as e:
        print(f"GitHub get {filename}: {e}")
    return None

def github_put(filename, data, message):
    if not GITHUB_TOKEN:
        return
    try:
        url = f"https://api.github.com/repos/{REPO_NAME}/contents/{filename}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        res = requests.get(url, headers=headers, timeout=10).json()
        sha = res.get("sha")
        content = base64.b64encode(
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("utf-8")
        payload = {"message": message, "content": content, "branch": "main"}
        if sha:
            payload["sha"] = sha
        requests.put(url, headers=headers, json=payload, timeout=10)
    except Exception as e:
        print(f"GitHub put {filename}: {e}")

def read_file(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    if GITHUB_TOKEN:
        data = github_get(filename)
        if data is not None:
            write_local(filename, data)
            print(f"{filename} GitHub'dan yuklandi")
            return data
    return default

def write_local(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_and_push(filename, data, message):
    write_local(filename, data)
    github_put(filename, data, message)

# ==================== MA'LUMOT YUKLASH ====================
def load_data():
    global admins, movies, channels, users, daily_users, admin_states, new_movies_temp, ad_post_id, bot_settings

    movies.update(read_file("movies.json", {}))
    ch = read_file("channels.json", {})
    channels.update(ch)
    
    adm = read_file("admins.json", [ADMIN_ID])
    admins.update(set(adm))
    admins.add(ADMIN_ID)

    usr = read_file("users.json", [])
    users.update(set(usr))

    daily = read_file("daily_users.json", {})
    daily_users.update({k: set(v) for k, v in daily.items()})

    states = read_file("admin_states.json", {})
    admin_states.update({int(k): v for k, v in states.items()})

    temp = read_file("new_movies_temp.json", {})
    new_movies_temp.update({int(k): v for k, v in temp.items()})

    ad = read_file("ad_post.json", {"id": None})
    ad_post_id = ad.get("id") if isinstance(ad, dict) else None
    
    bot_settings.update(read_file("settings.json", {"protect_content": True}))

# ==================== YORDAMCHI FUNKSIYALAR ====================
def is_main_admin(user_id):
    return user_id == ADMIN_ID

def is_admin(user_id):
    return user_id in admins

def track_user(user_id):
    global users, daily_users
    is_new = user_id not in users
    users.add(user_id)
    today = datetime.date.today().strftime("%Y-%m-%d")
    if today not in daily_users:
        daily_users[today] = set()
    daily_users[today].add(user_id)
    if is_new:
        save_and_push("users.json", list(users), "Yangi foydalanuvchi")
        save_and_push("daily_users.json", {k: list(v) for k, v in daily_users.items()}, "Kunlik statistika")

def save_states():
    write_local("admin_states.json", admin_states)
    write_local("new_movies_temp.json", {str(k): v for k, v in new_movies_temp.items()})

# ==================== KLAVIATURALAR ====================
def get_admin_keyboard(user_id):
    if is_main_admin(user_id):
        return ReplyKeyboardMarkup([
            ["➕ Kino qo'shish", "🗑️ Kino o'chirish"],
            ["📊 Statistika", "📋 Kodlar ro'yxati"],
            ["⚙️ Kanallarni boshqarish", "👑 Adminlarni boshqarish"],
            ["📣 Hammaga xabar", "📢 Reklama xabar"],
            ["⚙️ Bot Sozlamalari"]
        ], resize_keyboard=True)
    else:
        return ReplyKeyboardMarkup([
            ["➕ Kino qo'shish", "🗑️ Kino o'chirish"],
            ["📊 Statistika", "📋 Kodlar ro'yxati"],
            ["⚙️ Kanallarni boshqarish", "📢 Reklama xabar"],
            ["⚙️ Bot Sozlamalari"]
        ], resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)

# ==================== OBUNA TEKSHIRUVI ====================
async def is_joined(bot, user_id):
    if not channels:
        return True
    for ch_id in channels:
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

# ==================== KINO YUBORISH ====================
async def send_movie(chat_id, movie_code, bot):
    global ad_post_id, bot_settings
    if movie_code not in movies:
        return False
    data = movies[movie_code]
    video_id = data["video_id"] if isinstance(data, dict) else data
    if not isinstance(video_id, list):
        video_id = [video_id]

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔍 Qidirish", switch_inline_query_current_chat="")
    ]])
    
    admin_user = is_admin(chat_id)
    # Agar admin bo'lsa cheklov ishlamaydi, foydalanuvchi bo'lsa sozlamaga qaraydi:
    protect = False if admin_user else bot_settings.get("protect_content", True)

    for vid in video_id:
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=SOURCE_CHANNEL,
                message_id=int(vid),
                reply_markup=kb,
                protect_content=protect
            )
        except Exception as e:
            print(f"Kino yuborishda xato: {e}")
            await bot.send_message(chat_id=chat_id, text="❌ Film topilmadi yoki bot kanalda admin emas.")

    if ad_post_id and not admin_user:
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=SOURCE_CHANNEL,
                message_id=int(ad_post_id),
                protect_content=True
            )
        except Exception:
            pass
    return True

# ==================== START ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    track_user(user_id)
    args = context.args

    if args and args[0].startswith("kino_"):
        movie_code = args[0].split("_")[1]
        if await is_joined(context.bot, user_id):
            await send_movie(update.effective_chat.id, movie_code, context.bot)
        else:
            await update.message.reply_text(
                "❗ Kinoni olish uchun kanallarga qo'shiling!",
                reply_markup=await get_subscription_keyboard(context.bot)
            )
        return

    if is_admin(user_id):
        admin_states[user_id] = None
        new_movies_temp.pop(user_id, None)
        save_states()
        role = "Asosiy Admin" if is_main_admin(user_id) else "Yordamchi Admin"
        await update.message.reply_text(
            f"👑 Salom {role}! Boshqaruv paneli:",
            reply_markup=get_admin_keyboard(user_id)
        )
        return

    if not await is_joined(context.bot, user_id):
        await update.message.reply_text(
            "❗ Botdan foydalanish uchun kanallarga qo'shiling!",
            reply_markup=await get_subscription_keyboard(context.bot)
        )
        return

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔍 Kinolarni qidirish", switch_inline_query_current_chat="")
    ]])
    await update.message.reply_text(
        "👋 Assalomu alaykum!\n\n"
        "🎥 Sevimli kino kodini yuboring yoki qidiruv orqali toping.",
        reply_markup=kb
    )

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

    results = []
    for code, data in reversed(list(movies.items())):
        name = data.get("name", f"Kino {code}") if isinstance(data, dict) else f"Kino {code}"
        desc = data.get("desc", "") if isinstance(data, dict) else ""
        poster = data.get("poster") if isinstance(data, dict) else None
        if poster and not poster.startswith("http"):
            poster = None

        if not query or query in name.lower() or query in code.lower():
            results.append(InlineQueryResultArticle(
                id=code,
                title=f"🎬 {name.upper()}",
                description=f"{desc} | Kod: {code}",
                thumbnail_url=poster,
                input_message_content=InputTextMessageContent(message_text=code)
            ))

    await update.inline_query.answer(results[:50], cache_time=0)

# ==================== MATN XABARLARI ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ad_post_id
    user_id = update.effective_user.id
    text = update.message.text.strip()
    track_user(user_id)

    if not is_admin(user_id):
        if not await is_joined(context.bot, user_id):
            await update.message.reply_text(
                "❗ Avval kanallarga obuna bo'ling!",
                reply_markup=await get_subscription_keyboard(context.bot)
            )
            return
        if await send_movie(update.effective_chat.id, text, context.bot):
            return
        await update.message.reply_text("❌ Bunday kodli kino topilmadi.")
        return

    state = admin_states.get(user_id)

    if text == "❌ Bekor qilish":
        admin_states[user_id] = None
        new_movies_temp.pop(user_id, None)
        save_states()
        await update.message.reply_text("🏠 Admin paneli", reply_markup=get_admin_keyboard(user_id))
        return

    if state == "add_movie":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) < 5:
            await update.message.reply_text(
                "❌ 5 qator kerak:\n\n"
                "1. Kino nomi\n2. Ma'lumot\n3. Kod\n4. Poster URL\n5. Post ID\n\n"
                "Qaytadan yuboring:", reply_markup=get_cancel_keyboard()
            )
            return
        name, desc, code, poster, video_id = lines[0], lines[1], lines[2], lines[3], lines[4]
        if not video_id.isdigit():
            await update.message.reply_text("❌ 5-qator raqam bo'lishi kerak!", reply_markup=get_cancel_keyboard())
            return
        new_movies_temp[user_id] = {"name": name, "desc": desc, "code": code, "poster": poster, "video_id": video_id}
        admin_states[user_id] = "confirm_movie"
        save_states()
        confirm_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Tasdiqlash", callback_data="confirm_save_movie"),
            InlineKeyboardButton("❌ Bekor", callback_data="cancel_to_main")
        ]])
        await update.message.reply_text(
            f"🎬 {name.upper()}\n📝 {desc}\n🔑 {code}\n🖼 {poster}\n📥 ID: {video_id}\n\nTasdiqlaysizmi?",
            reply_markup=confirm_kb
        )
        return

    if state == "confirm_movie":
        await update.message.reply_text("⏳ Yuqoridagi tugmani bosing.", reply_markup=get_cancel_keyboard())
        return

    if state == "channel_add":
        parts = text.split(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ Format:\n@username Kanal nomi\nyoki\n-1001234567890 Kanal nomi",
                reply_markup=get_cancel_keyboard()
            )
            return
        ch_id, ch_name = parts[0].strip(), parts[1].strip()
        if not ch_id.startswith("@") and not ch_id.lstrip("-").isdigit():
            await update.message.reply_text("❌ Noto'g'ri format!", reply_markup=get_cancel_keyboard())
            return
        channels[ch_id] = ch_name
        admin_states[user_id] = None
        save_states()
        save_and_push("channels.json", channels, "Kanal qo'shildi")
        await update.message.reply_text(f"✅ Kanal qo'shildi: {ch_name}", reply_markup=get_admin_keyboard(user_id))
        return

    if state == "broadcast":
        context.user_data["broadcast_text"] = text
        admin_states[user_id] = None
        save_states()
        confirm_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yuborish", callback_data="broadcast_confirm"),
            InlineKeyboardButton("❌ Bekor", callback_data="cancel_to_main")
        ]])
        await update.message.reply_text(
            f"📣 Xabar:\n\n{text}\n\n👥 {len(users)} ta foydalanuvchiga yuboriladi.\nTasdiqlaysizmi?",
            reply_markup=confirm_kb
        )
        return

    if state == "set_ad":
        if not text.lstrip("-").isdigit():
            await update.message.reply_text("❌ Faqat raqam (Post ID):", reply_markup=get_cancel_keyboard())
            return
        if text == "0":
            ad_post_id = None
        else:
            ad_post_id = text
        admin_states[user_id] = None
        save_states()
        save_and_push("ad_post.json", {"id": ad_post_id}, "Reklama yangilandi")
        msg = "✅ Reklama o'chirildi." if ad_post_id is None else f"✅ Reklama o'rnatildi! Post ID: {ad_post_id}"
        await update.message.reply_text(msg, reply_markup=get_admin_keyboard(user_id))
        return

    if state == "admin_add" and is_main_admin(user_id):
        if not text.isdigit():
            await update.message.reply_text("❌ Faqat Telegram ID raqamini kiriting:", reply_markup=get_cancel_keyboard())
            return
        new_id = int(text)
        if new_id == ADMIN_ID:
            await update.message.reply_text("❌ Bu asosiy admin!", reply_markup=get_cancel_keyboard())
            return
        admins.add(new_id)
        admin_states[user_id] = None
        save_states()
        save_and_push("admins.json", list(admins), "Admin qo'shildi")
        await update.message.reply_text(f"✅ Admin qo'shildi! ID: {new_id}", reply_markup=get_admin_keyboard(user_id))
        return

    if text == "➕ Kino qo'shish":
        admin_states[user_id] = "add_movie"
        save_states()
        await update.message.reply_text(
            "🎬 5 qatorni BITTA xabarda yuboring:\n\n"
            "1. Kino nomi\n2. Ma'lumot (sifat, til)\n3. Kod\n4. Poster URL\n5. Post ID\n\n"
            "Misol:\nAvengers\n4K | O'zbek tilida\navengers\nhttps://example.com/poster.jpg\n12345",
            reply_markup=get_cancel_keyboard()
        )
        return

    if text == "🗑️ Kino o'chirish":
        if not movies:
            await update.message.reply_text("❌ Bazada kino yo'q.")
            return
        kb = []
        for code, data in movies.items():
            name = data.get("name", code).upper() if isinstance(data, dict) else code
            kb.append([InlineKeyboardButton(f"🎬 {name} ({code})", callback_data=f"del_{code}")])
        kb.append([InlineKeyboardButton("❌ Bekor", callback_data="cancel_to_main")])
        await update.message.reply_text("O'chirmoqchi bo'lgan kinoni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if text == "📊 Statistika":
        today = datetime.date.today().strftime("%Y-%m-%d")
        today_count = len(daily_users.get(today, set()))
        await update.message.reply_text(
            f"📊 Statistika:\n\n👥 Jami: {len(users)}\n📅 Bugun: {today_count}\n🎬 Kinolar: {len(movies)}"
        )
        return

    if text == "📋 Kodlar ro'yxati":
        if not movies:
            await update.message.reply_text("Ro'yxat bo'sh.")
            return
        lines = [f"🔑 {code} → {data.get('name', '?').upper() if isinstance(data, dict) else '?'}"
                 for code, data in movies.items()]
        await update.message.reply_text("📋 Kodlar:\n\n" + "\n".join(lines))
        return

    if text == "⚙️ Kanallarni boshqarish":
        ch_list = "\n".join([f"🔹 {n} ({i})" for i, n in channels.items()]) or "Kanallar yo'q"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Qo'shish", callback_data="channel_add"),
             InlineKeyboardButton("🗑️ O'chirish", callback_data="channel_remove")],
            [InlineKeyboardButton("❌ Bekor", callback_data="cancel_to_main")]
        ])
        await update.message.reply_text(f"📢 Kanallar:\n\n{ch_list}", reply_markup=kb)
        return

    if text == "👑 Adminlarni boshqarish" and is_main_admin(user_id):
        adm_list = "\n".join([f"• {a}" for a in admins if a != ADMIN_ID]) or "Yo'q"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Admin qo'shish", callback_data="admin_add"),
             InlineKeyboardButton("➖ Admin o'chirish", callback_data="admin_remove")],
            [InlineKeyboardButton("❌ Bekor", callback_data="cancel_to_main")]
        ])
        await update.message.reply_text(f"👑 Adminlar:\n{adm_list}", reply_markup=kb)
        return

    if text == "📣 Hammaga xabar" and is_main_admin(user_id):
        admin_states[user_id] = "broadcast"
        save_states()
        await update.message.reply_text(
            f"📣 Xabar yozing ({len(users)} ta foydalanuvchi):",
            reply_markup=get_cancel_keyboard()
        )
        return

    if text == "📢 Reklama xabar":
        cur = f"Hozirgi: Post ID {ad_post_id}" if ad_post_id else "Hozircha reklama yo'q"
        admin_states[user_id] = "set_ad"
        save_states()
        await update.message.reply_text(
            f"📢 Reklama sozlamasi\n{cur}\n\nKanaldan reklama post ID ni yuboring.\n(O'chirish uchun 0)",
            reply_markup=get_cancel_keyboard()
        )
        return

    if text == "⚙️ Bot Sozlamalari":
        status = "🔴 BLOKLANGAN (Uzatib bo'lmaydi)" if bot_settings.get("protect_content", True) else "🟢 OCHIQ (Uzatib bo'ladi)"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Holatni o'zgartirish", callback_data="toggle_protect")],
            [InlineKeyboardButton("❌ Orqaga", callback_data="cancel_to_main")]
        ])
        await update.message.reply_text(
            f"⚙️ **Bot Sozlamalari Paneli**\n\n"
            f"Foydalanuvchilar uchun kinoni uzatish/yuklash holati:\n"
            f"**{status}**\n\n"
            f"💡 *Eslatma: Adminlarga bu cheklov baribir ta'sir qilmaydi.*",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        "⚠️ Siz adminsiz! Botni tekshirish uchun boshqa akkountdan foydalaning.",
        reply_markup=get_admin_keyboard(user_id)
    )

# ==================== CALLBACK ====================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ad_post_id, bot_settings
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "cancel_to_main":
        admin_states[user_id] = None
        new_movies_temp.pop(user_id, None)
        save_states()
        await query.answer()
        await query.message.delete()
        if is_admin(user_id):
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="🏠 Admin paneli",
                reply_markup=get_admin_keyboard(user_id)
            )
        return

    if data == "check":
        if await is_joined(context.bot, user_id):
            await query.answer("✅ Tasdiqlandi!")
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔍 Kinolarni qidirish", switch_inline_query_current_chat="")
            ]])
            await query.message.edit_text(
                "👋 Assalomu alaykum!\n\n🎥 Kino kodini yuboring yoki qidiruv orqali toping.",
                reply_markup=kb
            )
        else:
            await query.answer("❌ Hali obuna bo'lmagan!", show_alert=True)
        return

    if not is_admin(user_id):
        return

    if data == "toggle_protect":
        # Holatni teskarisiga o'zgartiramiz
        current_state = bot_settings.get("protect_content", True)
        bot_settings["protect_content"] = not current_state
        save_and_push("settings.json", bot_settings, "Bot sozlamasi o'zgardi")
        
        status = "🔴 BLOKLANGAN (Uzatib bo'lmaydi)" if bot_settings["protect_content"] else "🟢 OCHIQ (Uzatib bo'ladi)"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Holatni o'zgartirish", callback_data="toggle_protect")],
            [InlineKeyboardButton("❌ Orqaga", callback_data="cancel_to_main")]
        ])
        
        await query.answer("✅ Sozlama o'zgartirildi!")
        await query.message.edit_text(
            f"⚙️ **Bot Sozlamalari Paneli**\n\n"
            f"Foydalanuvchilar uchun kinoni uzatish/yuklash holati:\n"
            f"**{status}**\n\n"
            f"💡 *Eslatma: Adminlarga bu cheklov baribir ta'sir qilmaydi.*",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return

    if data == "confirm_save_movie":
        movie_data = new_movies_temp.get(user_id)
        if movie_data and "video_id" in movie_data:
            movies[movie_data["code"]] = {
                "name": movie_data["name"],
                "desc": movie_data["desc"],
                "poster": movie_data["poster"],
                "video_id": movie_data["video_id"]
            }
            admin_states[user_id] = None
            new_movies_temp.pop(user_id, None)
            save_states()
            save_and_push("movies.json", movies, "Kino qo'shildi")
            await query.answer("✅ Saqlandi!")
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"✅ Kino qo'shildi! Kod: {movie_data['code']}",
                reply_markup=get_admin_keyboard(user_id)
            )
        else:
            await query.answer("❌ Ma'lumot topilmadi!", show_alert=True)
        return

    if data.startswith("del_"):
        code = data[4:]
        if code in movies:
            del movies[code]
            save_and_push("movies.json", movies, "Kino o'chirildi")
            await query.answer(f"✅ {code} o'chirildi!", show_alert=True)
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="✅ Kino o'chirildi!",
                reply_markup=get_admin_keyboard(user_id)
            )
        else:
            await query.answer("❌ Kino topilmadi!", show_alert=True)
        return

    if data == "channel_add":
        admin_states[user_id] = "channel_add"
        save_states()
        await query.message.edit_text(
            "➕ Kanal qo'shish:\n\n"
            "Public: @username Kanal nomi\n"
            "Private: -1001234567890 Kanal nomi\n\n"
            "💡 ID bilish uchun @getmyid_bot",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Bekor", callback_data="cancel_to_main")
            ]])
        )
        return

    if data == "channel_remove":
        if not channels:
            await query.answer("❌ Kanal yo'q!", show_alert=True)
            return
        kb = []
        for ch_id, ch_name in channels.items():
            kb.append([InlineKeyboardButton(f"🗑️ {ch_name} ({ch_id})", callback_data=f"delch_{ch_id}")])
        kb.append([InlineKeyboardButton("❌ Bekor", callback_data="cancel_to_main")])
        await query.message.edit_text("O'chirmoqchi bo'lgan kanalni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("delch_"):
        ch_id = data[6:]
        if ch_id in channels:
            ch_name = channels.pop(ch_id)
            save_and_push("channels.json", channels, "Kanal o'chirildi")
            await query.answer(f"✅ {ch_name} o'chirildi!", show_alert=True)
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"✅ {ch_name} o'chirildi!",
                reply_markup=get_admin_keyboard(user_id)
            )
        return

    if data == "admin_add" and is_main_admin(user_id):
        admin_states[user_id] = "admin_add"
        save_states()
        await query.message.edit_text(
            "➕ Yangi admin Telegram ID sini yuboring:\n(@userinfobot orqali bilib olish mumkin)",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Bekor", callback_data="cancel_to_main")
            ]])
        )
        return

    if data == "admin_remove" and is_main_admin(user_id):
        other = [a for a in admins if a != ADMIN_ID]
        if not other:
            await query.answer("❌ O'chiradigan admin yo'q!", show_alert=True)
            return
        kb = [[InlineKeyboardButton(f"❌ {a}", callback_data=f"deladm_{a}")] for a in other]
        kb.append([InlineKeyboardButton("🔙 Bekor", callback_data="cancel_to_main")])
        await query.message.edit_text("O'chirmoqchi bo'lgan adminni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "broadcast_confirm" and is_main_admin(user_id):
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
        success, failed = 0, 0
        for uid in list(users):
            try:
                await context.bot.send_message(chat_id=uid, text=msg_text)
                success += 1
            except Exception:
                failed += 1
        context.user_data.pop("broadcast_text", None)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"✅ Yuborildi!\n📨 Muvaffaqiyatli: {success}\n❌ Yuborilmadi: {failed}",
            reply_markup=get_admin_keyboard(user_id)
        )
        return

    if data.startswith("deladm_") and is_main_admin(user_id):
        rem_id = int(data[7:])
        if rem_id in admins and rem_id != ADMIN_ID:
            admins.discard(rem_id)
            save_and_push("admins.json", list(admins), "Admin o'chirildi")
            await query.answer("✅ Admin o'chirildi!", show_alert=True)
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"✅ Admin o'chirildi! ID: {rem_id}",
                reply_markup=get_admin_keyboard(user_id)
            )
        return

# ==================== ISHGA TUSHIRISH ====================
load_data()

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(InlineQueryHandler(inline_query_handler))
app.add_handler(CallbackQueryHandler(handle_callback))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

if RENDER_EXTERNAL_URL:
    PORT = int(os.environ.get("PORT", 10000))
    print(f"Webhook: {RENDER_EXTERNAL_URL}, Port: {PORT}")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=f"{RENDER_EXTERNAL_URL}/webhook"
    )
else:
    print("Polling rejimida ishga tushdi...")
    app.run_polling()
