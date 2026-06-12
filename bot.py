async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    track_user(user_id)
    text = update.message.text.strip()
    
    # Rejimni aniqlaymiz: default admin rejim bo'ladi
    current_mode = context.user_data.get("mode", "admin" if is_admin(user_id) else "user")
    state = context.user_data.get("admin_state")

    # Rejimlararo o'tish tugmalari (Adminlar uchun)
    if is_admin(user_id):
        if text == "👤 Foydalanuvchi rejimiga o'tish":
            context.user_data["mode"] = "user"
            context.user_data["admin_state"] = None
            await update.message.reply_text("🔄 Foydalanuvchi rejimiga o'tdingiz.", reply_markup=get_user_keyboard(user_id))
            await send_welcome(update, user_id)
            return
        elif text == "👑 Admin rejimiga o'tish":
            context.user_data["mode"] = "admin"
            await update.message.reply_text("🔄 Admin rejimiga qaytdingiz.", reply_markup=get_admin_keyboard(user_id))
            return

    # ----- ADMIN REJIMI LOGIKASI -----
    if is_admin(user_id) and current_mode == "admin":
        # 1. Agar bekor qilish bosilsa
        if text == "❌ Bekor qilish":
            context.user_data["admin_state"] = None
            context.user_data.pop("new_movie", None)
            await go_to_main_panel(update, user_id)
            return

        # 2. Bosqichma-bosqich jarayonlar (State bo'lsa)
        if state:
            if state == "add_movie_name":
                context.user_data["new_movie"] = {"name": text}
                context.user_data["admin_state"] = "add_movie_desc"
                await update.message.reply_text("📝 2-Qadam: Kino ma'lumotlarini kiriting (sifati, tili...):", reply_markup=get_cancel_keyboard())
                return

            elif state == "add_movie_desc":
                context.user_data["new_movie"]["desc"] = text
                context.user_data["admin_state"] = "add_movie_code"
                await update.message.reply_text("🔑 3-Qadam: Kinoga beriladigan kodni kiriting:", reply_markup=get_cancel_keyboard())
                return

            elif state == "add_movie_code":
                context.user_data["new_movie"]["code"] = text
                context.user_data["admin_state"] = "add_movie_poster"
                await update.message.reply_text("🖼️ 4-Qadam: Kino posteri (rasm) havolasini (linkini) yuboring:", reply_markup=get_cancel_keyboard())
                return

            elif state == "add_movie_poster":
                context.user_data["new_movie"]["poster"] = text
                context.user_data["admin_state"] = "add_movie_vid"
                await update.message.reply_text("📥 5-Qadam: Kanaldagi Post ID raqamini yuboring:", reply_markup=get_cancel_keyboard())
                return

            elif state == "add_movie_vid":
                if not text.isdigit():
                    await update.message.reply_text("❌ Post ID faqat raqam bo'ladi. Qaytadan kiriting:", reply_markup=get_cancel_keyboard())
                    return
                movie_data = context.user_data["new_movie"]
                movie_data["video_id"] = text
                preview = (
                    f"🎬 Nomi: {movie_data['name'].upper()}\n"
                    f"📝 Ma'lumot: {movie_data['desc']}\n"
                    f"🔑 Kod: {movie_data['code']}\n"
                    f"🖼️ Poster: {movie_data['poster']}\n"
                    f"📥 Video ID: {movie_data['video_id']}\n\n"
                    f"Tasdiqlaysizmi?"
                )
                confirm_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Tasdiqlash", callback_data="confirm_save_movie"),
                     InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")]
                ])
                await update.message.reply_text(preview, reply_markup=confirm_kb)
                return

            elif state == "waiting_channel_add":
                parts = text.split(" ", 1)
                if len(parts) < 2:
                    await update.message.reply_text("❌ Format xato!\nTo'g'ri format: @kanal_username Kanal Nomi", reply_markup=get_cancel_keyboard())
                    return
                channels[parts[0]] = parts[1]
                save_data()
                context.user_data["admin_state"] = None
                await update.message.reply_text(f"✅ Kanal qo'shildi: {parts[1]}")
                await go_to_main_panel(update, user_id)
                return

            elif state == "waiting_channel_remove":
                if text in channels:
                    del channels[text]
                    save_data()
                    context.user_data["admin_state"] = None
                    await update.message.reply_text("✅ Kanal o'chirildi.")
                    await go_to_main_panel(update, user_id)
                else:
                    await update.message.reply_text("❌ Bunday kanal topilmadi. Qaytadan kiriting:", reply_markup=get_cancel_keyboard())
                return

            elif state == "waiting_admin_add" and is_main_admin(user_id):
                if not text.isdigit():
                    await update.message.reply_text("❌ Faqat Telegram ID raqamini kiriting:", reply_markup=get_cancel_keyboard())
                    return
                new_id = int(text)
                if new_id == ADMIN_ID:
                    await update.message.reply_text("❌ Bu allaqachon asosiy admin!", reply_markup=get_cancel_keyboard())
                    return
                admins.add(new_id)
                save_data()
                context.user_data["admin_state"] = None
                await update.message.reply_text(f"✅ Yangi admin qo'shildi!\nID: {new_id}")
                await go_to_main_panel(update, user_id)
                return

            elif state == "waiting_admin_remove" and is_main_admin(user_id):
                if not text.isdigit():
                    await update.message.reply_text("❌ Faqat Telegram ID raqamini kiriting:", reply_markup=get_cancel_keyboard())
                    return
                remove_id = int(text)
                if remove_id == ADMIN_ID:
                    await update.message.reply_text("❌ Asosiy adminni o'chirib bo'lmaydi!", reply_markup=get_cancel_keyboard())
                    return
                if remove_id in admins:
                    admins.remove(remove_id)
                    save_data()
                    context.user_data["admin_state"] = None
                    await update.message.reply_text(f"✅ Admin o'chirildi!\nID: {remove_id}")
                    await go_to_main_panel(update, user_id)
                else:
                    await update.message.reply_text("❌ Bunday admin topilmadi. Qaytadan kiriting:", reply_markup=get_cancel_keyboard())
                return

            elif state == "broadcast_wait" and is_main_admin(user_id):
                context.user_data["broadcast_text"] = text
                context.user_data["admin_state"] = None
                confirm_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Yuborish", callback_data="broadcast_confirm"),
                     InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")]
                ])
                await update.message.reply_text(
                    f"📣 Xabar ko'rinishi:\n\n{text}\n\n"
                    f"👥 {len(users)} ta foydalanuvchiga yuboriladi.\n"
                    f"Tasdiqlaysizmi?",
                    reply_markup=confirm_kb
                )
                return

        # 3. Admin Asosiy Menyu Tugmalari
        if text == "➕ Kino qo'shish":
            context.user_data["admin_state"] = "add_movie_name"
            await update.message.reply_text("🎬 1-Qadam: Kino nomini kiriting:", reply_markup=get_cancel_keyboard())
            return
        elif text == "🗑️ Kino o'chirish":
            if not movies:
                await update.message.reply_text("❌ Bazada hech qanday kino yo'q.")
                return
            keyboard = []
            for kod, m_data in movies.items():
                name = m_data.get("name", f"Kino {kod}").upper() if isinstance(m_data, dict) else f"Kino {kod}"
                keyboard.append([InlineKeyboardButton(f"🎬 {name} (Kod: {kod})", callback_data=f"del_movie_{kod}")])
            keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")])
            await update.message.reply_text("👇 O'chirmoqchi bo'lgan kinoni tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        elif text == "📊 Statistika":
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            today_count = len(daily_users.get(today_str, set()))
            await update.message.reply_text(
                f"📊 Statistika:\n\n"
                f"👥 Jami foydalanuvchi: {len(users)}\n"
                f"📅 Bugun: {today_count}\n"
                f"🎬 Kinolar soni: {len(movies)}"
            )
            return
        elif text == "📋 Kodlar ro'yxati":
            if not movies:
                await update.message.reply_text("Ro'yxat bo'sh.")
                return
            text_codes = "📋 Kodlar ro'yxati:\n\n"
            for kod, data in movies.items():
                name = data.get("name", "Nomsiz").upper() if isinstance(data, dict) else "Kino"
                text_codes += f"🔑 {kod} → {name}\n"
            await update.message.reply_text(text_codes)
            return
        elif text == "⚙️ Kanallarni boshqarish":
            text_ch = "📢 Kanal ro'yxati:\n\n"
            for ch_id, ch_name in channels.items():
                text_ch += f"🔹 {ch_name} ({ch_id})\n"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Kanal qo'shish", callback_data="ask_channel_add"),
                 InlineKeyboardButton("🗑️ Kanal o'chirish", callback_data="ask_channel_remove")],
                [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")]
            ])
            await update.message.reply_text(text_ch, reply_markup=kb)
            return
        elif text == "📣 Hammaga xabar yuborish" and is_main_admin(user_id):
            context.user_data["admin_state"] = "broadcast_wait"
            await update.message.reply_text(
                f"📣 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yozing:\n\n"
                f"👥 Jami foydalanuvchilar: {len(users)} ta",
                reply_markup=get_cancel_keyboard()
            )
            return
        elif text == "👑 Adminlarni boshqarish" and is_main_admin(user_id):
            admin_list = "\n".join([f"• {a_id}" for a_id in admins if a_id != ADMIN_ID]) or "Hozircha yo'q"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Admin qo'shish", callback_data="ask_admin_add"),
                 InlineKeyboardButton("➖ Admin o'chirish", callback_data="ask_admin_remove")],
                [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_to_main")]
            ])
            await update.message.reply_text(f"👑 Adminlar:\n{admin_list}", reply_markup=kb)
            return
        
        # Agarda hech qanday jarayon (state) faol bo'lmasa va admin panelda shunchaki biror matn yozib yuborilsa:
        if not state:
            await update.message.reply_text("⚠️ Siz hozir Admin rejimidasiz! Kinolarni kod orqali tekshirib ko'rish uchun avval pastdagi '👤 Foydalanuvchi rejimiga o'tish' tugmasini bosing.")
        return

    # ----- FOYDALANUVCHI REJIMI LOGIKASI -----
    if not await is_joined(context.bot, user_id):
        reply_markup = await get_subscription_keyboard(context.bot)
        await update.message.reply_text("❗ Avval kanallarga obuna bo'ling!", reply_markup=reply_markup)
        return

    if await send_movie_by_code(update.effective_chat.id, text, context.bot, context):
        return
    else:
        await update.message.reply_text("❌ Bunday kodli kino topilmadi.")
