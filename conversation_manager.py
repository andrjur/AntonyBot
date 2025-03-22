# conversation_manager.py
import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext
)
from database import DatabaseConnection
from utils import safe_reply, get_db_and_user, db_handler

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

    def __init__(self, db, menu_manager, course_manager, purchase_manager, support_manager, course_data):
        logger.info("15 Initializing ConversationManager")
        self.db = db
        self.menu_manager = menu_manager
        self.course_manager = course_manager
        self.purchase_manager = purchase_manager
        self.support_manager = support_manager
        self.course_data = course_data

    def create_conversation_handler(self):
        """Creates and returns the conversation handler with all states and handlers."""
        return ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                WAIT_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_user_info)],
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
            fallbacks=[CommandHandler("cancel", self.cancel)],
            name="my_conversation",
            allow_reentry=True,
        )

    @db_handler
    async def start(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """    Обрабатывает команду /start.
        Инициализирует взаимодействие с пользователем и управляет потоком разговора на основе состояния пользователя.    """
        logger.info(f"Начало разговора с пользователем {user_id} =================================" )
        logger.info(f"Пользователь {user_id} запустил команду /start")

        # Проверка существования пользователя в базе данных
        cursor.execute(
            "SELECT user_id, active_course_id, full_name FROM users WHERE user_id = ?",
            (user_id,)
        )
        user_data = cursor.fetchone()

        if user_data and user_data[0]:  # Если у пользователя есть активный курс
            logger.info(f"У пользователя {user_id} есть активный курс, показываем главное меню")
            await update.effective_message.reply_text(f"👋 Привет! ID пользователя: {user_id}")
            await self.menu_manager.show_main_menu(update, context)
            return ACTIVE
        # Отправка приветственного сообщения


        if not user_data:
            # Новый пользователь - запрос имени
            logger.info(f"Новый пользователь {user_id} - запрашиваем имя")
            context.user_data["waiting_for_name"] = True
            keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.effective_message.reply_text(
                "📝 Пожалуйста, введите ваше имя:",
                reply_markup=reply_markup
            )
            return WAIT_FOR_NAME

        # Существующий пользователь - проверка статуса курса
        active_course = user_data[1]
        full_name = user_data[2]

        if not active_course:
            # Нет активного курса - запрос кода активации
            logger.info(f"Пользователю {user_id} требуется активация курса")
            context.user_data["waiting_for_code"] = True
            keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.effective_message.reply_text(
                f"📝 {full_name}, пожалуйста, введите кодовое слово для активации курса:",
                reply_markup=reply_markup
            )
            return WAIT_FOR_CODE

        # У пользователя есть активный курс - показываем главное меню
        logger.info(f"У пользователя {user_id} есть активный курс, показываем главное меню")
        await self.menu_manager.show_main_menu(update, context)
        return ACTIVE

    @db_handler
    async def handle_user_info(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):


        full_name = update.effective_message.text.strip() if update.effective_message and update.effective_message.text else ""
        logger.info(f" handle_user_info {user_id} ============================================")

        if not full_name:
            await update.effective_message.reply_text("Имя не может быть пустым. Введите ваше полное имя:")
            return WAIT_FOR_NAME

        try:
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

            cursor.execute("SELECT user_id, full_name FROM users WHERE user_id = ?", (user_id,))
            user_data = cursor.fetchone()

            if user_data:
                saved_name = user_data[1]  # Используем индекс 1 для получения full_name
            else:
                saved_name = None

            if saved_name != full_name:
                logger.error(f"Имя не совпадает с сохраненным {saved_name} != {full_name}")
                print(f"Имя не совпадает с сохраненным {saved_name} != {full_name}")

            await update.effective_message.reply_text(
                f"Отлично, {full_name}! Теперь введите кодовое слово для активации курса.")
            return WAIT_FOR_CODE
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite: {e}")
            await update.effective_message.reply_text("Произошла ошибка при работе с базой данных. Попробуйте позже.")
            return WAIT_FOR_NAME
        except Exception as e:
            logger.error(f"Ошибка при сохранении имени: {e}")
            logger.error(f"Ошибка SQL при сохранении пользователя {user_id}: {e}")
            await update.effective_message.reply_text("Произошла ошибка при сохранении данных. Попробуйте снова.")
            return WAIT_FOR_NAME

    @db_handler
    async def handle_code_words(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        user_id = update.effective_user.id
        if user_id is None:
            logger.error("Could not get user ID - effective_user is None")
            return ConversationHandler.END

        user_code = update.message.text.strip() if update.message and update.message.text else ""
        logger.info(f"handle_code_words {user_id} {user_code}")

        if user_code in self.course_data:
            try:
                success = await self.course_manager.activate_course(update, context, user_id, user_code)
                if success:
                    await safe_reply(update, context, "Курс активирован! Получите свой первый урок.")
                    await self.course_manager.get_current_lesson(update, context)
                    return ACTIVE
            except Exception as e:
                logger.error(f"Error in handle_code_words: {e}")
                await safe_reply(update, context, "Ошибка при активации курса. Пожалуйста, попробуйте позже.")
                return WAIT_FOR_CODE
        else:
            await safe_reply(update, context, "Неверное кодовое слово. Пожалуйста, попробуйте снова.")
            return WAIT_FOR_CODE

    @db_handler
    async def cancel(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """Handles cancellation of the conversation."""
        user_id = update.effective_user.id if update.effective_user else None
        if user_id is None:
            logger.error("Could not get user ID - effective_user is None")
            return ConversationHandler.END

        logger.info(f"User {user_id} canceled the conversation.")
        await update.message.reply_text("Диалог отменен. До свидания!")
        return ConversationHandler.END
