# Обработчик для сохранения домашней работы
async def save_homework(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    file_id = None

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document and update.message.document.mime_type.startswith('image/'):
        file_id = update.message.document.file_id

        try:
            # Определяем активный курс
            cursor.execute('''
                    SELECT main_course, auxiliary_course, main_current_lesson 
                    FROM users WHERE user_id = ?
                ''', (user_id,))
            main_course, auxiliary_course, current_lesson = cursor.fetchone()

            course_type = "main_course" if main_course else "auxiliary_course"
            course_name = main_course or auxiliary_course
            lesson = current_lesson - 1  # Текущий урок уже увеличен после отправки

            # Сохраняем ДЗ в БД
            cursor.execute('''
                    INSERT INTO homeworks 
                    (user_id, course_type, lesson, file_id, message_id, status, submission_time) 
                    VALUES (?, ?, ?, ?, NULL, 'pending', DATETIME('now'))
                ''', (user_id, course_type, lesson, file_id))
            conn.commit()

            # Отправляем уведомление админам
            admin_message = await context.bot.send_photo(
                chat_id=ADMIN_GROUP_ID,
                photo=file_id,
                caption=f"Новое ДЗ!\n"
                        f"User ID: {user_id}\n"
                        f"Курс: {course_name}\n"
                        f"Урок: {lesson}",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Принять", callback_data=f"approve_{course_type}_{cursor.lastrowid}"),
                        InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{course_type}_{cursor.lastrowid}")
                    ]
                ])
            )

            # Сохраняем ID сообщения в БД
            cursor.execute('''
                    UPDATE homeworks 
                    SET message_id = ? 
                    WHERE hw_id = ?
                ''', (admin_message.message_id, cursor.lastrowid))
            conn.commit()

            await update.message.reply_text("✅ Домашка принята! Админ проверит её в течение 24 часов.")
            return ConversationHandler.END

        except Exception as e:
            logger.error(f"Ошибка сохранения ДЗ: {e}")
            await update.message.reply_text("⚠️ Ошибка при сохранении работы. Попробуйте ещё раз.")
            return ConversationHandler.END
