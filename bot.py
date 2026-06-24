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
active_users = set()
deleted_users = set()
admin_states = {}
new_movies_temp = {}
ad_post_id = None
bot_settings = {"protect_content": True}

# ==================== GITHUB TIZIMI ====================
def github_get(filename):
    if not GITHUB_TOKEN:
        return None
    try:
        url = f"https://api.github.com/repos/{REPO_NAME}/contents/{filename}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code == 200:
            res_json = res.json()
            if "content" in res_json:
                return json.loads(base64.b64decode(res_json["content"]).decode("utf-8"))
    except Exception as e:
        print(f"GitHub get xato ({filename}): {e}")
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
        res = requests.get(url, headers=headers, timeout=10)
        sha = None
        if res.status_code == 200:
            sha = res.json().get("sha")

        content = base64.b64encode(
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("utf-8")
        payload = {"message": message, "content": content, "branch": "main"}
        if sha:
            payload["sha"] = sha
        requests.put(url, headers=headers, json=payload, timeout=12)
    except Exception as e:
        print(f"GitHub put xato ({filename}): {e}")

def read_file(filename, default):
    if GITHUB_TOKEN:
        git_data = github_get(filename)
        if git_data is not None:
            write_local(filename, git_data)
            return git_data
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default

def write_local(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_and_push(filename, data, message):
    write_local(filename, data)
    github_put(filename, data, message)

# ==================== MA'LUMOTLARNI YUKLASH ====================
def load_data():
    global admins, movies, channels, users, active_users, deleted_users, ad_post_id, bot_settings
    movies.update(read_file("movies.json", {}))
    channels.update(read_file("channels.json", {}))
    bot_settings.update(read_file("settings.json", {"protect_content": True}))
    
    adm = read_file("admins.json", [ADMIN_ID])
    admins.clear()
    admins.update(set(adm))
    admins.add(ADMIN_ID)

    users.clear()
    users.update(set(read_file("users.json", [])))
    active_users.clear()
    active_users.update(set(read_file("active_users.json", list(users))))
    deleted_users.clear()
    deleted_users.update(set(read_file("deleted_users.json", [])))

    ad = read_file("ad_post.json", {"id": None})
    ad_post_id = ad.get("id") if isinstance(ad, dict) else None

def track_user(user_id):
    global users, active_users, deleted_users
    is_changed = False
    if user_id not in users:
        users.add(user_id)
        is_changed = True
    if user_id not in active_users:
        active_users.add(user_id)
        is_changed = True
    if user_id in deleted_users:
        deleted_users.discard(user_id)
        is_changed = True
    if is_changed:
        save_and_push("users.json", list(users), "User ro'yxati yangilandi")
        save_and_push("active_users.json", list(active_users), "Faol userlar yangilandi")
        save_and_push("deleted_users.json", list(deleted_users), "O'chirilgan userlar yangilandi")

def is_main_admin(user_id):
    return user_id == ADMIN_ID

def is_admin(user_id):
    return user_id in admins

# ==================== TUGMALAR ====================
def get_admin_keyboard(user_id):
    return ReplyKeyboardMarkup([
        ["➕ Kino qo'shish", "🗑️ Kino o'chirish"],
        ["📊 Statistika", "📋 Kodlar ro'yxati"],
        ["📣 Hammaga xabar", "📢 Reklama xabar"],
        ["⚙️ Bot Sozlamalari"]
    ], resize_keyboard=True)

def get_settings_keyboard(user_id):
    status_text = "🔴 Uzatishni Yoqish" if bot_settings.get("protect_content", True) else "🟢 Uzatishni O'chirish"
    buttons = [
        [status_text],
        ["📢 Kanallarni Boshqarish", "👑 Adminlarni Boshqarish"],
        ["🏠 Bosh menyu"]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)

# ==================== OBUNA TEKSHIRUV ====================
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

# ==================== KINO YUBORISH (KO'P QISMLI) ====================
async def send_movie(chat_id, movie_code, bot):
    global ad_post_id, bot_settings
    if movie_code not in movies:
        return False
    data = movies[movie_code]
    
    # Vergul bilan ajratilgan ID raqamlarni ro'yxatga olish
    video_ids_raw = data["video_id"] if isinstance(data, dict) else data
    if isinstance(video_ids_raw, str):
        video_ids = [vid.strip() for vid in video_ids_raw.split(",") if vid.strip()]
    elif isinstance(video_ids_raw, list):
        video_ids = video_ids_raw
    else:
        video_ids = [str(video_ids_raw)]

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Qidirish", switch_inline_query_current_chat="")]])
    admin_user = is_admin(chat_id)
    protect = False if admin_user else bot_settings.get("protect_content", True)

    for vid in video_ids:
        try:
            await bot.copy_message(chat_id=chat_id, from_chat_id=SOURCE_CHANNEL, message_id=int(vid), reply_markup=kb, protect_content=protect)
        except Exception:
            await bot.send_message(chat_id=chat_id, text=f"❌ Film qismi topilmadi (ID: {vid}) yoki bot kanalda admin emas.")

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
        await update.message.reply_text("👑 Admin paneli ochildi:", reply_markup=get_admin_keyboard(user_id))
        return

    if not await is_joined(context.bot, user_id):
        await update.message.reply_text("❗ Botdan foydalanish uchun kanallarga qo'shiling!", reply_markup=await get_subscription_keyboard(context.bot))
        return

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Kinolarni qidirish", switch_inline_query_current_chat="")]])
    await update.message.reply_text("👋 Assalomu alaykum!\n\n🎥 Sevimli kino kodini yuboring.", reply_markup=kb)

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

# ==================== MATNLAR BILAN ISHLASH ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ad_post_id, bot_settings, users, active_users, deleted_users
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

    if text in ["❌ Bekor qilish", "🏠 Bosh menyu"]:
        admin_states[user_id] = None
        new_movies_temp.pop(user_id, None)
        await update.message.reply_text("🏠 Asosiy admin paneli:", reply_markup=get_admin_keyboard(user_id))
        return

    if state == "add_movie":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) < 5:
            await update.message.reply_text("❌ Xato! Ma'lumotlar kam. Iltimos shablondagidek 5 ta qator qilib to'ldiring:", reply_markup=get_cancel_keyboard())
            return
        name, desc, code, poster, video_id = lines[0], lines[1], lines[2], lines[3], lines[4]
        new_movies_temp[user_id] = {"name": name, "desc": desc, "code": code.lower(), "poster": poster, "video_id": video_id}
        admin_states[user_id] = "confirm_movie"
        confirm_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Tasdiqlash", callback_data="confirm_save_movie"),
            InlineKeyboardButton("❌ Bekor", callback_data="cancel_to_main")
        ]])
        await update.message.reply_text(f"🎬 **Kino nomi:** {name.upper()}\n🔑 **Kod:** {code}\n🎥 **Qismlar (ID):** {video_id}\n\nTasdiqlaysizmi?", reply_markup=confirm_kb, parse_mode="Markdown")
        return

    if state == "channel_add":
        parts = text.split(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Format xato! Quyidagi shablon bo'yicha yuboring:", reply_markup=get_cancel_keyboard())
            return
        channels[parts[0].strip()] = parts[1].strip()
        admin_states[user_id] = None
        save_and_push("channels.json", channels, "Kanal ro'yxati yangilandi")
        await update.message.reply_text("✅ Majburiy obuna kanali saqlandi!", reply_markup=get_settings_keyboard(user_id))
        return

    if state == "broadcast":
        context.user_data["broadcast_text"] = text
        admin_states[user_id] = None
        confirm_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Tasdiqlash va Yuborish", callback_data="broadcast_confirm")]])
        await update.message.reply_text(f"📣 Xabar hamma foydalanuvchilarga yuboriladi. Tasdiqlaysizmi?", reply_markup=confirm_kb)
        return

    if state == "set_ad":
        if not text.lstrip("-").isdigit():
            await update.message.reply_text("❌ Faqat raqam (Post ID) yuboring:")
            return
        ad_post_id = None if text == "0" else text
        admin_states[user_id] = None
        save_and_push("ad_post.json", {"id": ad_post_id}, "Reklama post yangilandi")
        await update.message.reply_text("✅ Reklama posti o'rnatildi!", reply_markup=get_admin_keyboard(user_id))
        return

    if state == "admin_add" and is_main_admin(user_id):
        if not text.isdigit():
            await update.message.reply_text("❌ Faqat Telegram ID raqam kiriting:")
            return
        admins.add(int(text))
        admin_states[user_id] = None
        save_and_push("admins.json", list(admins), "Yangi admin qo'shildi")
        await update.message.reply_text("✅ Yangi yordamchi admin qo'shildi!", reply_markup=get_settings_keyboard(user_id))
        return

    # TUGMALAR FUNKSIYASI
    if text == "➕ Kino qo'shish":
        admin_states[user_id] = "add_movie"
        shablon = (
            "➕ **Kino qo'shish uchun quyidagi 5 qatorli shablonni to'ldirib yuboring:**\n\n"
            "`Garri Potter 3`\n"
            "`Fantastik film`\n"
            "`300`\n"
            "`https://poster-url.com/image.jpg`\n"
            "`12,13,14`\n\n"
            "⚠️ **Eslatma:** Oxirgi qatorga agar kino ko'p qismli bo'lsa, xabarlar ID sini vergul bilan ajratib yozing (masalan: `12,13,14`)."
        )
        await update.message.reply_text(shablon, reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
        return

    if text == "🗑️ Kino o'chirish":
        if not movies:
            await update.message.reply_text("Bazada kino yo'q.")
            return
        kb = [[InlineKeyboardButton(f"🗑️ {c}", callback_data=f"del_{c}")] for c in movies]
        await update.message.reply_text("O'chirish uchun kodni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
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

    if text == "📋 Kodlar ro'yxati":
        if not movies:
            await update.message.reply_text("Baza bo'sh.")
            return
        lines = [f"🔑 {c} → {d.get('name', '?').upper() if isinstance(d, dict) else '?'}" for c, d in movies.items()]
        await update.message.reply_text("\n".join(lines))
        return

    if text == "📣 Hammaga xabar":
        admin_states[user_id] = "broadcast"
        await update.message.reply_text("Barcha foydalanuvchilarga yuboriladigan xabarni yozing:", reply_markup=get_cancel_keyboard())
        return

    if text == "📢 Reklama xabar":
        admin_states[user_id] = "set_ad"
        await update.message.reply_text("Reklama Post ID raqamini kiriting (O'chirish uchun 0):", reply_markup=get_cancel_keyboard())
        return

    if text == "⚙️ Bot Sozlamalari":
        cur_status = "🔴 BLOKLANGAN" if bot_settings.get("protect_content", True) else "🟢 OCHIQ"
        await update.message.reply_text(
            f"⚙️ **Sozlamalar bo'limi**\n\nHozirgi uzatish holati: **{cur_status}**",
            reply_markup=get_settings_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    if text in ["🔴 Uzatishni Yoqish", "🟢 Uzatishni O'chirish"]:
        bot_settings["protect_content"] = not bot_settings.get("protect_content", True)
        save_and_push("settings.json", bot_settings, "Uzatish rejimi o'zgardi")
        cur_status = "🔴 BLOKLANGAN" if bot_settings["protect_content"] else "🟢 OCHIQ"
        await update.message.reply_text(
            f"✅ Uzatish rejimi o'zgartirildi!\nYangi holat: **{cur_status}**",
            reply_markup=get_settings_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    if text == "📢 Kanallarni Boshqarish":
        ch_list = "\n".join([f"🔹 {n} (`{i}`)" for i, n in channels.items()]) or "Kanallar yo'q"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Qo'shish", callback_data="channel_add"), InlineKeyboardButton("🗑️ O'chirish", callback_data="channel_remove")]
        ])
        await update.message.reply_text(f"📢 **Majburiy obuna kanallari:**\n\n{ch_list}", reply_markup=kb, parse_mode="Markdown")
        return

    if text == "👑 Adminlarni Boshqarish":
        adm_list = "\n".join([f"• ID: {a} " + ("(Asosiy)" if a == ADMIN_ID else "(Yordamchi)") for a in admins])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Admin qo'shish", callback_data="admin_add"), InlineKeyboardButton("🗑️ Admin o'chirish", callback_data="admin_remove")]
        ])
        await update.message.reply_text(f"👑 **Bot Adminlari:**\n\n{adm_list}", reply_markup=kb, parse_mode="Markdown")
        return

# ==================== CALLBACK ISHLARI ====================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global movies, channels, users, active_users, deleted_users
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "check":
        if await is_joined(context.bot, user_id):
            await query.answer("✅ Rahmat, tasdiqlandi!")
            await query.message.delete()
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Kinolarni qidirish", switch_inline_query_current_chat="")]])
            await context.bot.send_message(chat_id=user_id, text="🎥 Kino kodini yuborishingiz mumkin.", reply_markup=kb)
        else:
            await query.answer("❌ Kanallarga a'zo bo'lmadingiz!", show_alert=True)
        return

    if not is_admin(user_id):
        return

    if data == "confirm_save_movie":
        movie_data = new_movies_temp.get(user_id)
        if movie_data:
            movies[movie_data["code"]] = {"name": movie_data["name"], "desc": movie_data["desc"], "poster": movie_data["poster"], "video_id": movie_data["video_id"]}
            admin_states[user_id] = None
            new_movies_temp.pop(user_id, None)
            save_and_push("movies.json", movies, f"Kino qo'shildi: {movie_data['code']}")
            await query.answer("✅ Kino saqlandi!")
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
            await context.bot.send_message(chat_id=query.message.chat_id, text="✅ Kino muvaffaqiyatli o'chirildi!", reply_markup=get_admin_keyboard(user_id))
        return

    if data == "channel_add":
        admin_states[user_id] = "channel_add"
        await query.message.delete()
        text_hint = (
            "➕ **Kanalni qo'shish formatini yuboring.**\n\n"
            "Siz ham `@username`, ham `-100...` formatidagi ID orqali qo'shishingiz mumkin:\n\n"
            "📌 **1-shablon (Username orqali):**\n"
            "`@kanal_username Mening Kanalim`\n\n"
            "📌 **2-shablon (ID raqam orqali):**\n"
            "`-100234567890 Mening Premium Kanalim`"
        )
        await context.bot.send_message(chat_id=user_id, text=text_hint, reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
        return

    if data == "channel_remove":
        if not channels:
            await query.answer("Kanallar yo'q!", show_alert=True)
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

    if data == "admin_add" or data == "admin_remove":
        if not is_main_admin(user_id):
            await query.answer("⚠️ Bu amal faqat Asosiy Admin uchun ruxsat etilgan!", show_alert=True)
            return
        if data == "admin_add":
            admin_states[user_id] = "admin_add"
            await query.message.delete()
            await context.bot.send_message(chat_id=user_id, text="➕ Admin Telegram ID raqamini yuboring:", reply_markup=get_cancel_keyboard())
        else:
            other = [a for a in admins if a != ADMIN_ID]
            if not other:
                await query.answer("Yordamchi adminlar mavjud emas!", show_alert=True)
                return
            kb = [[InlineKeyboardButton(f"❌ O'chirish: {a}", callback_data=f"deladm_{a}")] for a in other]
            await query.message.edit_text("O'chirish uchun yordamchi adminni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("deladm_"):
        if not is_main_admin(user_id):
            await query.answer("❌ Huquqingiz yo'q!", show_alert=True)
            return
        rem_id = int(data[7:])
        admins.discard(rem_id)
        save_and_push("admins.json", list(admins), "Admin o'chirildi")
        await query.message.delete()
        await context.bot.send_message(chat_id=query.message.chat_id, text="✅ Yordamchi admin o'chirildi!", reply_markup=get_settings_keyboard(user_id))
        return

    if data == "broadcast_confirm":
        msg_text = context.user_data.get("broadcast_text", "")
        await query.message.delete()
        success, failed = 0, 0
        
        for uid in list(users):
            try:
                await context.bot.send_message(chat_id=uid, text=msg_text)
                success += 1
                if uid not in active_users:
                    active_users.add(uid)
                if uid in deleted_users:
                    deleted_users.discard(uid)
            except Exception:
                failed += 1
                if uid in active_users:
                    active_users.discard(uid)
                if uid not in deleted_users:
                    deleted_users.add(uid)
                    
        save_and_push("active_users.json", list(active_users), "Faollar yangilandi")
        save_and_push("deleted_users.json", list(deleted_users), "O'chirilganlar yangilandi")
        await context.bot.send_message(chat_id=query.message.chat_id, text=f"📣 Xabar yakunlandi:\n\n🟢 Muvaffaqiyatli: {success}\n🔴 Blocklangan: {failed}", reply_markup=get_admin_keyboard(user_id))
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
