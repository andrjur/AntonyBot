        # Формируем приветственное сообщение
        greeting = f"""Приветствую, {full_name.split()[0]}! ✅
        Курс: {active_course_id} ({course_type}) {active_tariff}
        Прогресс: Текущий урок: {progress}
        Домашка: {homework}"""

        # Отправляем меню
        if update.callback_query:
            await update.callback_query.message.reply_text(greeting, reply_markup=reply_markup)
        else:
            await update.message.reply_text(greeting, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Ошибка в show_main_menu: {str(e)}")
        if update.callback_query:
            await update.callback_query.message.reply_text("Ошибка при отображении меню. Попробуйте позже.")
        else:
            await update.message.reply_text("Ошибка при отображении меню. Попробуйте позже.")