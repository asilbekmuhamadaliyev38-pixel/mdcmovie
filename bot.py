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
bot_settings = {"protect_content": True}

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
        
        if "content" in res and filename == "movies.json":
            try:
                github_data = json.loads(base64.b64decode(res["content"]).decode("utf-8"))
                if isinstance(github_data, dict):
                    github_data.update(data)
                    data = github_data
            except Exception:
                pass

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
            return data
    return default

def write_local(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_and_push(filename, data, message):
    if filename == "movies.json":
        global movies
        movies = data
    write_local(filename, data)
    github_put(filename, data, message)

# ==================== MA'LUMOT YUKLASH ====================
def load_data():
    global admins, movies, channels, users, daily_users, admin_states, new_movies_temp, ad_post_id, bot_settings

    if GITHUB_TOKEN:
        git_movies = github_get("movies.json")
        if git_movies:
            movies.update(git_movies)
            write_local("movies.json", git_movies)
            
        git_settings = github_get("settings.json")
        if git_settings:
            bot_settings.update(git_settings)
            write_local("settings.json", git_settings)

    movies.update(read_file("movies.json", {}))
    channels.update(read_file("channels.json", {}))
    
    adm = read_file("admins.json", [ADMIN_ID])
    admins.update(set(adm))
    admins.add(ADMIN_ID)

    users.update(set(read_file("users.json", [])))
    daily_users.update({k: set(v) for k, v in read_file("daily_users.json", {}).items()})
    admin_states.update({int(k): v for k, v in read_file("admin_states.json", {}).items()})
    new_movies_temp.update({int(k): v for k, v in read_file("new_movies_temp.json", {}).items()})

    ad = read_file("ad_post.json", {"id": None})
    ad_post_id = ad.get("id") if isinstance(ad, dict) else None

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

# ==================== KLAVIATURALAR (PASTDAGI TUGMALAR) ====================
def get_admin_keyboard(user_id):
    # Asosiy toza menyu
    return ReplyKeyboardMarkup([
        ["➕ Kino qo'shish", "🗑️ Kino o'chirish"],
        ["📊 Statistika", "📋 Kodlar ro'yxati"],
        ["📣 Hammaga xabar" if is_main_admin(user_id) else "📢 Reklama xabar"],
        ["⚙️ Bot Sozlamalari"]
    ], resize_keyboard=True)

def get_settings_keyboard(user_id):
    # Sozlamalar ichidagi ixcham pastki tugmalar
    status_text = "🔴 Uzatishni Yoqish" if bot_settings.get("protect_content", True) else "🟢 Uzatishni O'chirish"
    buttons = [
        [status_text],
        ["📢 Kanallarni Boshqarish"]
    ]
    if is_main_admin(user_id):
        buttons.append(["👑 Adminlarni Boshqarish"])
    buttons.append(["🏠 Bosh menyu"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

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

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Qidirish", switch_inline_query_current_chat="")]])
    
    admin_user = is_admin(chat_id)
    protect = False if admin_user else bot_settings.get("protect_content", True)

    for vid in video_id:
        try:
            await bot.copy_message(chat_id=chat_id, from_chat_id=SOURCE_CHANNEL, message_id=int(vid), reply_markup=kb, protect_content=protect)
        except Exception as e:
            print(f"Kino yuborishda xato: {e}")
            await bot.send_message(chat_id=chat_id, text="❌ Film topilmadi yoki bot kanalda admin emas.")

    if ad_post_id and not admin_user:
        try:
            await bot.copy_message(chat_id=chat_id, from_chat_id=SOURCE_CHANNEL, message_id=int(ad_post_id), protect_content=True)
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
            await update.message.reply_text("❗ Kinoni olish uchun kanallarga qo'shiling!", reply_markup=await get_subscription_keyboard(context.bot))
        return

    if is_admin(user_id):
        admin_states[user_id] = None
        new_movies_temp.pop(user_id, None)
        save_states()
        await update.message.reply_text("👑 Admin paneli ochildi:", reply_markup=get_admin_keyboard(user_id))
        return

    if not await is_joined(context.bot, user_id):
        await update.message.reply_text("❗ Botdan foydalanish uchun kanallarga qo'shiling!", reply_markup=await get_subscription_keyboard(context.bot))
        return

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Kinolarni qidirish", switch_inline_query_current_chat="")]])
    await update.message.reply_text("👋 Assalomu alaykum!\n\n🎥 Sevimli kino kodini yuboring.", reply_markup=kb)

# ==================== INLINE QUERY ====================
async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    user_id = update.inline_query.from_user.id

    if not await is_joined(context.bot, user_id):
        await update.inline_query.answer([], switch_pm_text="📢 Avval kanallarga obuna bo'ling", switch_pm_parameter="start", cache_time=0)
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

# ==================== MATN XABARLARI (PASTKI TUGMALAR ISHI) ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ad_post_id, bot_settings
    user_id = update.effective_user.id
    text = update.message.text.strip()
    track_user(user_id)

    if not is_admin(user_id):
        if not await is_joined(context.bot, user_id):
            await update.message.reply_text("❗ Avval kanallarga obuna bo'ling!", reply_markup=await get_subscription_keyboard(context.bot))
            return
        if await send_movie(update.effective_chat.id, text, context.bot):
            return
        await update.message.reply_text("❌ Bunday kodli kino topilmadi.")
        return

    state = admin_states.get(user_id)

    # Bekor qilish yoki bosh menyuga qaytish
    if text in ["❌ Bekor qilish", "🏠 Bosh menyu"]:
        admin_states[user_id] = None
        new_movies_temp.pop(user_id, None)
        save_states()
        await update.message.reply_text("🏠 Asosiy admin paneli:", reply_markup=get_admin_keyboard(user_id))
        return

    # SHTATLARGA MUVOFIQ ISH REJIMLARI
    if state == "add_movie":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) < 5:
            await update.message.reply_text("❌ Xato! 5 qator qilib yuboring:", reply_markup=get_cancel_keyboard())
            return
        name, desc, code, poster, video_id = lines[0], lines[1], lines[2], lines[3], lines[4]
        new_movies_temp[user_id] = {"name": name, "desc": desc, "code": code.lower(), "poster": poster, "video_id": video_id}
        admin_states[user_id] = "confirm_movie"
        save_states()
        confirm_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Tasdiqlash", callback_data="confirm_save_movie"),
            InlineKeyboardButton("❌ Bekor", callback_data="cancel_to_main")
        ]])
        await update.message.reply_text(f"🎬 {name.upper()}\n\nTasdiqlaysizmi?", reply_markup=confirm_kb)
        return

    if state == "channel_add":
        parts = text.split(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Format xato! Masalan:\n@kanal_user Mening Kanalim", reply_markup=get_cancel_keyboard())
            return
        channels[parts[0].strip()] = parts[1].strip()
        admin_states[user_id] = None
        save_states()
        save_and_push("channels.json", channels, "Kanal qo'shildi")
        await update.message.reply_text("✅ Kanal muvaffaqiyatli qo'shildi!", reply_markup=get_settings_keyboard(user_id))
        return

    if state == "broadcast":
        context.user_data["broadcast_text"] = text
        admin_states[user_id] = None
        save_states()
        confirm_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Tasdiqlash", callback_data="broadcast_confirm")]])
        await update.message.reply_text("Tasdiqlash tugmasini bosing:", reply_markup=confirm_kb)
        return

    if state == "set_ad":
        if not text.lstrip("-").isdigit():
            await update.message.reply_text("❌ Faqat raqam yuboring:")
            return
        ad_post_id = None if text == "0" else text
        admin_states[user_id] = None
        save_states()
        save_and_push("ad_post.json", {"id": ad_post_id}, "Reklama yangilandi")
        await update.message.reply_text("✅ Reklama sozlamasi yangilandi!", reply_markup=get_admin_keyboard(user_id))
        return

    if state == "admin_add" and is_main_admin(user_id):
        if not text.isdigit():
            await update.message.reply_text("❌ Faqat ID raqam bo'lsin:")
            return
        admins.add(int(text))
        admin_states[user_id] = None
        save_states()
        save_and_push("admins.json", list(admins), "Admin qo'shildi")
        await update.message.reply_text("✅ Yangi admin qo'shildi!", reply_markup=get_settings_keyboard(user_id))
        return

    # ASOSIY PANEL TUGMALARI ISHI
    if text == "➕ Kino qo'shish":
        admin_states[user_id] = "add_movie"
        save_states()
        await update.message.reply_text("🎬 5 qator qilib ma'lumotlarni yuboring:", reply_markup=get_cancel_keyboard())
        return

    if text == "🗑️ Kino o'chirish":
        if not movies:
            await update.message.reply_text("Bazada kino yo'q.")
            return
        kb = [[InlineKeyboardButton(f"🗑️ {c}", callback_data=f"del_{c}")] for c in movies]
        await update.message.reply_text("O'chirish uchun kodni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if text == "📊 Statistika":
        today = datetime.date.today().strftime("%Y-%m-%d")
        today_count = len(daily_users.get(today, set()))
        await update.message.reply_text(f"📊 Statistika:\n\n👥 Jami a'zolar: {len(users)}\n📅 Bugun kirganlar: {today_count}\n🎬 Kinolar soni: {len(movies)}")
        return

    if text == "📋 Kodlar ro'yxati":
        if not movies:
            await update.message.reply_text("Baza bo'sh.")
            return
        lines = [f"🔑 {c} → {d.get('name', '?').upper() if isinstance(d, dict) else '?'}" for c, d in movies.items()]
        await update.message.reply_text("\n".join(lines))
        return

    if text == "📣 Hammaga xabar" and is_main_admin(user_id):
        admin_states[user_id] = "broadcast"
        save_states()
        await update.message.reply_text("Xabaringizni yozing:", reply_markup=get_cancel_keyboard())
        return

    if text == "📢 Reklama xabar":
        admin_states[user_id] = "set_ad"
        save_states()
        await update.message.reply_text("Reklama Post ID raqamini yuboring (O'chirish uchun 0):", reply_markup=get_cancel_keyboard())
        return

    # PASDAGI SOZLAMALAR PANELINI OCHISH
    if text == "⚙️ Bot Sozlamalari":
        cur_status = "🔴 BLOKLANGAN (Uzatish taqiqlangan)" if bot_settings.get("protect_content", True) else "🟢 OCHIQ (Uzatish ruxsat etilgan)"
        await update.message.reply_text(
            f"⚙️ **Sozlamalar bo'limi**\n\nHozirgi holat: **{cur_status}**\n\n*Kerakli tugmani pastdan bosing:*",
            reply_markup=get_settings_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    # SOZLAMALAR ICHIDAGI PASTKI TUGMALAR ISHI
    if text in ["🔴 Uzatishni Yoqish", "🟢 Uzatishni O'chirish"]:
        bot_settings["protect_content"] = not bot_settings.get("protect_content", True)
        save_and_push("settings.json", bot_settings, "Uzatish rejimi o'zgardi")
        
        cur_status = "🔴 BLOKLANGAN (Uzatish taqiqlangan)" if bot_settings["protect_content"] else "🟢 OCHIQ (Uzatish ruxsat etilgan)"
        await update.message.reply_text(
            f"✅ Holat muvaffaqiyatli o'zgartirildi va qulqlandi!\n\nYangi holat: **{cur_status}**",
            reply_markup=get_settings_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    if text == "📢 Kanallarni Boshqarish":
        ch_list = "\n".join([f"🔹 {n} ({i})" for i, n in channels.items()]) or "Kanallar yo'q"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Qo'shish", callback_data="channel_add"), InlineKeyboardButton("🗑️ O'chirish", callback_data="channel_remove")]
        ])
        await update.message.reply_text(f"📢 **Kanallar ro'yxati:**\n\n{ch_list}", reply_markup=kb, parse_mode="Markdown")
        return

    if text == "👑 Adminlarni Boshqarish" and is_main_admin(user_id):
        adm_list = "\n".join([f"• ID: {a}" for a in admins if a != ADMIN_ID]) or "Yordamchi adminlar yo'q"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Qo'shish", callback_data="admin_add"), InlineKeyboardButton("🗑️ O'chirish", callback_data="admin_remove")]
        ])
        await update.message.reply_text(f"👑 **Yordamchi adminlar:**\n\n{adm_list}", reply_markup=kb, parse_mode="Markdown")
        return

# ==================== CALLBACK (FAQAT KANALLAR VA O'CHIRISH UCHUN) ====================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global movies, channels
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "check":
        if await is_joined(context.bot, user_id):
            await query.answer("✅ Tasdiqlandi!")
            await query.message.delete()
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Kinolarni qidirish", switch_inline_query_current_chat="")]])
            await context.bot.send_message(chat_id=user_id, text="🎥 Kino kodini yuboring.", reply_markup=kb)
        else:
            await query.answer("❌ Hali obuna bo'lmagan!", show_alert=True)
        return

    if not is_admin(user_id):
        return

    if data == "confirm_save_movie":
        movie_data = new_movies_temp.get(user_id)
        if movie_data:
            movies[movie_data["code"]] = {"name": movie_data["name"], "desc": movie_data["desc"], "poster": movie_data["poster"], "video_id": movie_data["video_id"]}
            admin_states[user_id] = None
            new_movies_temp.pop(user_id, None)
            save_states()
            save_and_push("movies.json", movies, f"Kino qo'shildi: {movie_data['code']}")
            await query.answer("✅ Saqlandi!")
            await query.message.delete()
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"✅ Qo'shildi: {movie_data['code']}", reply_markup=get_admin_keyboard(user_id))
        return

    if data.startswith("del_"):
        code = data[4:]
        if code in movies:
            del movies[code]
            save_and_push("movies.json", movies, f"O'chirildi: {code}")
            await query.answer("✅ O'chirildi!")
            await query.message.delete()
            await context.bot.send_message(chat_id=query.message.chat_id, text="✅ Kino o'chirildi!", reply_markup=get_admin_keyboard(user_id))
        return

    if data == "channel_add":
        admin_states[user_id] = "channel_add"
        save_states()
        await query.message.delete()
        await context.bot.send_message(chat_id=user_id, text="➕ Formatni yuboring:\n`@username Kanal Nomi`", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
        return

    if data == "channel_remove":
        if not channels:
            await query.answer("Kanal yo'q!", show_alert=True)
            return
        kb = [[InlineKeyboardButton(f"🗑️ {n}", callback_data=f"delch_{i}")] for i, n in channels.items()]
        await query.message.edit_text("O'chirish uchun kanalni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("delch_"):
        ch_id = data[6:]
        if ch_id in channels:
            del channels[ch_id]
            save_and_push("channels.json", channels, "Kanal o'chirildi")
            await query.message.delete()
            await context.bot.send_message(chat_id=query.message.chat_id, text="✅ Kanal o'chirildi!", reply_markup=get_settings_keyboard(user_id))
        return

    if data == "admin_add" and is_main_admin(user_id):
        admin_states[user_id] = "admin_add"
        save_states()
        await query.message.delete()
        await context.bot.send_message(chat_id=user_id, text="➕ Admin Telegram ID sini yuboring:", reply_markup=get_cancel_keyboard())
        return

    if data == "admin_remove" and is_main_admin(user_id):
        other = [a for a in admins if a != ADMIN_ID]
        if not other:
            await query.answer("Yordamchi adminlar yo'q!", show_alert=True)
            return
        kb = [[InlineKeyboardButton(f"❌ {a}", callback_data=f"deladm_{a}")] for a in other]
        await query.message.edit_text("O'chirish uchun adminni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("deladm_") and is_main_admin(user_id):
        rem_id = int(data[7:])
        admins.discard(rem_id)
        save_and_push("admins.json", list(admins), "Admin o'chirildi")
        await query.message.delete()
        await context.bot.send_message(chat_id=query.message.chat_id, text="✅ Admin o'chirildi!", reply_markup=get_settings_keyboard(user_id))
        return

    if data == "broadcast_confirm" and is_main_admin(user_id):
        msg_text = context.user_data.get("broadcast_text", "")
        await query.message.delete()
        success, failed = 0, 0
        for uid in list(users):
            try:
                await context.bot.send_message(chat_id=uid, text=msg_text)
                success += 1
            except Exception:
                failed += 1
        await context.bot.send_message(chat_id=query.message.chat_id, text=f"📣 Xabar yuborildi!\n🟢 {success} | 🔴 {failed}", reply_markup=get_admin_keyboard(user_id))
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
    app.run_webhook(listen="0.0.0.0", port=PORT, url_path="webhook", webhook_url=f"{RENDER_EXTERNAL_URL}/webhook")
else:
    app.run_polling()
