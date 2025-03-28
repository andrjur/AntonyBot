async def show_main_menu(update: Update, context: CallbackContext):
    """Выводит главное меню с информацией о курсе, прогрессе и т.д."""
    user_id = update.effective_user.id
    logger.info(f" show_main_menu       {update.effective_user} ---")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    #  Load data
    try:
        cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
        user_tokens = cursor.fetchone()
        tokens = user_tokens[0] if user_tokens else 0
        logger.info(f"Select tokens FROM user_tokens WHERE user_id = ? ({tokens,}) для {user_id} ")

        coins_display = f" {PLATINUM_COIN}x{0}{GOLD_COIN}x{0}{SILVER_COIN}x{1}{BRONZE_COIN}x{5}"

        # Получаем данные о последнем начислении
        cursor.execute("SELECT reason FROM user_bonus_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1",
                       (user_id,))
        last_bonus = cursor.fetchone()
        last_bonus_reason = last_bonus[0] if last_bonus else "Нет данных"

        # Рассчитываем дату следующего ежемесячного бонуса
        now = datetime.now()
        next_bonus_time = now + timedelta(days=30)
        next_bonus_str = next_bonus_time.strftime("%d.%m.%Y")

        message = f"  222 Ваши antCoins: {tokens}   {coins_display}\n" \
                  f"Последнее начисление: {last_bonus_reason}\n" \
                  f"Следующее начисление: +1 (Ежемесячный бонус)\n" \
                  f"\nВ магазине пока нет товаров."
        logger.info(
            f"434 active_course_data= ('femininity_premium',) на будущее message='{message[:150]}...' ---- ")

        # Получаем информацию о курсе
        cursor.execute(
            "SELECT active_course_id FROM users WHERE user_id = ?",
            (user_id,),
        )
        active_course_data = cursor.fetchone()
        course_data = None
        if active_course_data:
            active_course_id = active_course_data[0]
            logger.info(f"435 course_data= {active_course_data} ----- ")
            cursor.execute(
                "SELECT course_type, progress FROM user_courses WHERE user_id = ? AND course_id = ?",
                (user_id, active_course_id),
            )
            course_data = cursor.fetchone()

        # Формируем меню в зависимости от наличия курса и прогресса
        if course_data:
            course_type, progress = course_data
            logger.info(f"436 Тип курса: {course_type=} Прогресс: {progress=} ------ ")
            logger.info(f"437 {course_type=} {progress=} ------ ")
            cursor.execute("SELECT settings FROM user_settings WHERE user_id = ?", (user_id,))
            settings_data = cursor.fetchone()
            logger.info(f"438 Настройки уведомлений:  {settings_data=} ------- ")

            cursor.execute("SELECT name FROM users WHERE user_id = ?", (user_id,))
            name_data = cursor.fetchone()
            logger.info(f"439 Имя пользователя:  {name_data=} -------- ")
            settings = settings_data[0] if settings_data else None
            logger.info(f"440 {settings=} ------- ")
            name_data = cursor.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)).fetchone()
            logger.info(f" 441 {name_data=} -------- ")

            full_name = name_data[0] if name_data else "Пользователь"
            logger.info(f"443 {full_name=} --------- ")

            # Получаем статус домашки и формируем текст
            homework_status = await get_homework_status_text(user_id, progress)
            logger.info(f"444 homework={homework_status=} --------- ")

            # Calculate next lesson time
            next_lesson_time = datetime.now() + timedelta(hours=DEFAULT_LESSON_INTERVAL)
            formatted_next_lesson_time = next_lesson_time.strftime("%d-%m-%Y %H:%M")

            # Combine homework status and next lesson time
            homework_and_next_lesson = f"{homework_status}  \nСледующий урок в {formatted_next_lesson_time} "

            # Получаем файлы урока
            lesson_dir = f"courses\\{active_course_id}"
            lesson_files = get_lesson_files(user_id, progress, lesson_dir)  # исправил на await

            main_menu_text = f"Приветствую, {full_name}! ✅\n" \
                             f"        Курс: {active_course_id} (main) premium\n" \
                             f"        Прогресс: Текущий урок: {progress}\n" \
                             f"        Домашка: {homework_and_next_lesson}   \n" \
                             f" {PLATINUM_COIN}AntCoins{PLATINUM_COIN} {tokens}  =      {coins_display}"

            lesson_files = await get_lesson_files(user_id, progress, lesson_dir)
            logger.info(f"445 lesson_files = {lesson_files}  -=- ")

        else:
            main_menu_text = "Чтобы начать обучение, активируйте курс с помощью кодового слова."

        # Создаем клавиатуру
        keyboard = create_main_keyboard(has_active_course=bool(course_data), is_admin=is_admin(user_id))
        # Выводим сообщение с клавиатурой
        await safe_reply(update, context, main_menu_text, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"time {time.strftime('%H:%M:%S')} Error in show_main_menu: {e}")
        await safe_reply(update, context, "Error display menu. Try later.")
    finally:
        if conn:
            conn.close()

        logger.info(f"User {user_id} transitioning to  ConversationHandler.END state")
    return ConversationHandler.END





