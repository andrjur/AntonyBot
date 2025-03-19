import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext
)
from database import DatabaseConnection

logger = logging.getLogger(__name__)

# Conversation States
(
    WAIT_FOR_NAME,
    WAIT_FOR_CODE,
    ACTIVE,
    COURSE_SETTINGS,
    WAIT_FOR_SUPPORT_TEXT,
    WAIT_FOR_SELFIE,
    WAIT_FOR_DESCRIPTION,
    WAIT_FOR_CHECK,
    WAIT_FOR_GIFT_USER_ID,
    WAIT_FOR_PHONE_NUMBER,
) = range(10)

class ConversationManager:
    def __init__(self, menu_manager, course_manager, purchase_manager, support_manager):
        self.menu_manager = menu_manager
        self.course_manager = course_manager
        self.purchase_manager = purchase_manager
        self.support_manager = support_manager
        
    def create_conversation_handler(self):
        """Creates and returns the conversation handler with all states and handlers."""
        return ConversationHandler(
            entry_points=[telegram.ext.CommandHandler("start", self.start)],
            states={
                WAIT_FOR_NAME: [telegram.ext.MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_user_info)],
                WAIT_FOR_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_code_words)],
                ACTIVE: [
                    CommandHandler("lesson", self.course_manager.get_current_lesson),
                    CommandHandler("menu", self.menu_manager.show_main_menu),
                    MessageHandler(filters.PHOTO | filters.Document.ALL, self.course_manager.handle_homework),
                ],
                WAIT_FOR_SUPPORT_TEXT: [MessageHandler((filters.TEXT & ~filters.COMMAND) | filters.PHOTO, self.support_manager.process_support_request)],
                WAIT_FOR_SELFIE: [MessageHandler(filters.PHOTO, self.purchase_manager.process_selfie)],
                WAIT_FOR_DESCRIPTION: [MessageHandler(filters.TEXT, self.purchase_manager.process_description)],
                WAIT_FOR_CHECK: [MessageHandler(filters.PHOTO, self.purchase_manager.process_check)],
                WAIT_FOR_GIFT_USER_ID: [MessageHandler(filters.TEXT, self.purchase_manager.process_gift_user_id)],
                WAIT_FOR_PHONE_NUMBER: [MessageHandler(filters.CONTACT, self.purchase_manager.process_phone_number)],
            },
            fallbacks=[telegram.ext.CommandHandler("cancel", self.cancel)],
            name="my_conversation",
            allow_reentry=True,
        )

        # Move create_conversation_handler function here
        
    # получение имени и проверка *
    async def handle_user_info(self, update: Update, context: CallbackContext):  # Добавил conn и cursor
        # Get user ID safely, handling None case
        db = DatabaseConnection()
        conn = db.get_connection()
        cursor = db.get_cursor()
        
        user_id = update.effective_user.id if update.effective_user else None
        if user_id is None:
            logger.error("Could not get user ID - effective_user is None")
            return
        full_name = update.effective_message.text.strip()
        # Логирование текущего состояния пользователя
        logger.info(f" handle_user_info {user_id} ============================================")

        # Проверка на пустое имя
        if not full_name:
            await update.effective_message.reply_text("Имя не может быть пустым. Введите ваше полное имя:")
            return WAIT_FOR_NAME

        logger.info(f" full_name {full_name} ==============================")

        try:
                    # Сохранение имени пользователя в базе данных
            if cursor:
                cursor.execute(
                    """
                    INSERT INTO users (user_id, full_name) 
                    VALUES (?, ?)
                    ON CONFLICT(user_id) DO 
                    UPDATE SET full_name = excluded.full_name
                    """,
                    (user_id, full_name),
                )      
            if conn:
                conn.commit()

            # Подтверждение записи
            cursor.execute("SELECT user_id, full_name FROM users WHERE user_id = ?", (user_id,))
            user_data = cursor.fetchone()

            if user_data:
                saved_name = user_data[1]  # Используем индекс 1 для получения full_name
            else:
                saved_name = None

            if saved_name != full_name:
                logger.error(f"Имя не совпадает с сохраненным {saved_name} != {full_name}")
                print(f"Имя не совпадает с сохраненным {saved_name} != {full_name}")

            # Успешное сохранение, переход к следующему шагу
            await update.effective_message.reply_text(
                f"Отлично, {full_name}! Теперь введите кодовое слово для активации курса.")
            return WAIT_FOR_CODE
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite: {e}")
            await update.effective_message.reply_text("Произошла ошибка при работе с базой данных. Попробуйте позже.")
            return WAIT_FOR_NAME

        except Exception as e:
            # Обработка ошибок при сохранении имени
            logger.error(f"Ошибка при сохранении имени: {e}")
            logger.error(f"Ошибка SQL при сохранении пользователя {user_id}: {e}")
            await update.effective_message.reply_text("Произошла ошибка при сохранении данных. Попробуйте снова.")
            return WAIT_FOR_NAME
            
    async def handle_code_words(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        if user_id is None:
            logger.error("Could not get user ID - effective_user is None")
            return ConversationHandler.END

        user_code = update.message.text.strip() if update.message and update.message.text else ""
        logger.info(f"handle_code_words {user_id} {user_code}")

        if user_code in course_data:
            try:
                # Use course_manager instance instead of direct function
                success = await course_manager.activate_course(update, context, user_id, user_code)
                if success:
                    await safe_reply(update, context, "Course activated! Get your first lesson.")
                    await get_current_lesson(update, context)
                    return ACTIVE
            except Exception as e:
                logger.error(f"Error in handle_code_words: {e}")
                await safe_reply(update, context, "Error activating course. Please try again later.")
                return WAIT_FOR_CODE
        else:
            await safe_reply(update, context, "Invalid code word. Please try again.")
            return WAIT_FOR_CODE
