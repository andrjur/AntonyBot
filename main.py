# main.py
# Standard library imports
import logging
import os
from datetime import datetime, timedelta
import mimetypes
from typing import Callable

# Third-party imports
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,  
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
    PicklePersistence
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

# Local imports
from database import (
    DatabaseConnection,
    create_all_tables,
    load_courses,
    load_bonuses,
    load_ad_config
)
from utils import safe_reply, handle_telegram_errors
from constants import (
    TOKEN,
    ADMIN_GROUP_ID,
    ADMIN_IDS,
    CONFIG_FILES,
    DEFAULT_LESSON_INTERVAL,
    DEFAULT_LESSON_DELAY_HOURS,
    TOKEN_TO_RUB_RATE,
    HARD_CODE_DELAY,
    PERSISTENCE_FILE,
    DELAY_PATTERN,
    COMMUNITY_CHAT_URL
)

# Manager imports
from menu_manager import MenuManager
from reminder_manager import ReminderManager
from shop_manager import ShopManager
from course_manager import CourseManager, Course  # Updated import path
from purchase_manager import PurchaseManager
from stats_manager import StatsManager
from token_manager import TokenManager
from gallery_manager import GalleryManager
from support_manager import SupportManager
from scheduler_manager import SchedulerManager
from admin_manager import AdminManager
from conversation_manager import ConversationManager

# Remove these as they're now in constants.py
# TARIFFS_FILE = "tariffs.json"
# COURSE_DATA_FILE = "courses.json"
# AD_CONFIG_FILE = "ad_config.json"
# BONUSES_FILE = "bonuses.json"
# DELAY_MESSAGES_FILE = "delay_messages.txt"
# PAYMENT_INFO_FILE = "payment_info.json"
# DELAY_PATTERN = re.compile(r"_(\d+)(hour|min|m|h)(?:\.|$)")

# Update persistence initialization
persistence = PicklePersistence(filepath=PERSISTENCE_FILE)

# Initialize database and managers
db = DatabaseConnection()


# Load configurations
bonuses_config = None

ad_config = db.load_ad_config()
course_data = db.load_course_data()
delay_messages = db.load_delay_messages()

logger.info(f"Loaded {len(delay_messages)} delay messages")

# не работает, скотина и всё ломает. Оставлена в назидание
async def logging_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Логирует все входящие сообщения."""
    try:
        user_id = update.effective_user.id if update.effective_user else None
        state = context.user_data['state'] if context.user_data else 'NO_STATE'
        logger.info(f"Пользователь {user_id} находится в состоянии {state}")
        return True  # Продолжаем обработку
    except Exception as e:
        logger.error(f"Ошибка в logging_middleware: {e}")
        return True  # Важно не блокировать обработку

# персистентность
persistence = PicklePersistence(filepath="bot_data.pkl")


# Регулярное выражение для извлечения времени задержки из имени файла
# DELAY_PATTERN = re.compile(r"_(\d+)(hour|min|m|h)$") расширение сраное забыли
DELAY_PATTERN = re.compile(r"_(\d+)(hour|min|m|h)(?:\.|$)")

logger.info(
    f"ПОЕХАЛИ {DEFAULT_LESSON_DELAY_HOURS=} {DEFAULT_LESSON_INTERVAL=} время старта {time.strftime('%d/%m/%Y %H:%M:%S')}")



#18-03 17-10 Perplexity
@handle_telegram_errors
async def start(update: Update, context: CallbackContext) -> int:
    """Starts the conversation and asks the user for their name."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        logger.error("Could not get user ID - effective_user is None")
        return ConversationHandler.END

    logger.info(f"Начало разговора с пользователем {user_id} =================================================================")
    logger.info(f"Пользователь {user_id} запустил команду /start")

    # Fetch user info from the database
    user_data=None
    if cursor:
        cursor.execute("SELECT full_name, active_course_id FROM users WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()

    if user_data:
        full_name = user_data[0]
        active_course_id = user_data[1]

        if full_name:
            if active_course_id:
                logger.info(f"Пользователь {user_id} уже зарегистрирован и курс активирован.")
                greeting = f"Приветствую, {full_name.split()[0]}! 👋"
                await safe_reply(update, context, greeting)
                await show_main_menu(update, context)  # Direct user to main menu
                return ACTIVE  # User is fully set up
            else:
                logger.info(f"Пользователь {user_id} зарегистрирован, но курс не активирован.")
                greeting = f"Приветствую, {full_name.split()[0]}! 👋"
                await safe_reply(update, context, f"{greeting}\nДля активации курса, введите кодовое слово:")
                return WAIT_FOR_CODE  # Ask for the code word
        else:
            logger.info(f"Пользователь {user_id} зарегистрирован, но имя отсутствует.")
            await safe_reply(update, context, "Пожалуйста, введите ваше имя:")
            return WAIT_FOR_NAME  # Ask for the name
    else:
        # Insert new user into the database
        cursor.execute("""
            INSERT INTO users (user_id, full_name, registration_date) 
            VALUES (?, ?, ?)
        """, (user_id, 'ЧЕБУРАШКА', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        logger.info(f"Новый пользователь {user_id} - запрашиваем имя")
        await safe_reply(update, context, "Привет! Пожалуйста, введите ваше имя:")
        return WAIT_FOR_NAME  # Ask for the name





async def unknown_command(update: Update, context: CallbackContext):
    """Обработчик для неизвестных команд."""
    await update.message.reply_text("Извините, я не знаю такой команды. Пожалуйста, введите /help, чтобы увидеть список доступных команд.")

# Trae 19-03 15:53
async def button_handler(update: Update, context: CallbackContext):
    """Handles button presses."""
    query = update.callback_query
    if query is None:
        logger.warning("Query is None - cannot access callback data")
        return
        
    data = query.data
    managers = context.bot_data.get('managers', {})
    
    # Get all required managers
    shop_manager = managers.get('shop')
    purchase_manager = managers.get('purchase')
    menu_manager = managers.get('menu')
    course_manager = managers.get('course')
    gallery_manager = managers.get('gallery')
    support_manager = managers.get('support')
    stats_manager = managers.get('stats')
    token_manager = managers.get('token')

    # Define all button handlers with null checks
    handlers = {
        'menu': menu_manager.show_main_menu if menu_manager else None,
        'buy_tariff': purchase_manager.buy_tariff if purchase_manager else None,
        'gift_tariff': purchase_manager.gift_tariff if purchase_manager else None,
        'admin_approve_purchase': purchase_manager.admin_approve_purchase if purchase_manager else None,
        'admin_reject_purchase': purchase_manager.admin_reject_purchase if purchase_manager else None,
        'admin_approve_discount': purchase_manager.admin_approve_discount if purchase_manager else None,
        'admin_reject_discount': purchase_manager.admin_reject_discount if purchase_manager else None,
        'get_current_lesson': course_manager.get_current_lesson if course_manager else None,
        'gallery': gallery_manager.show_gallery if gallery_manager else None,
        'gallery_next': gallery_manager.get_random_homework if gallery_manager else None,
        'menu_back': menu_manager.show_main_menu if menu_manager else None,
        'support': support_manager.start_support_request if support_manager else None,
        'tariffs': shop_manager.show_tariffs if shop_manager else None,
        'course_settings': course_manager.show_course_settings if course_manager else None,
        'statistics': stats_manager.show_statistics if stats_manager else None,
        'preliminary_tasks': course_manager.send_preliminary_material if course_manager else None,
        'buy_lootbox': token_manager.buy_lootbox if token_manager else None,
        'show_tokens': token_manager.show_token_balance if token_manager else None,
    }

    try:
        if data in handlers and handlers[data]:
            await handlers[data](update, context)
            await query.answer()
            return

        # Handle special cases
        if data.startswith('tariff_'):
            await shop_manager.handle_tariff_selection(update, context)
            await query.answer()
            return

        if data.startswith('set_tariff|'):
            _, course_id, tariff = data.split('|')
            await shop_manager.change_tariff(update, context, course_id, tariff)
            await query.answer()
            return

        logger.warning(f"No handler found for callback data: {data}")
        await query.answer("Command not found")

    except Exception as e:
        logger.error(f"Error in button_handler: {e}")
        await safe_reply(update, context, "An error occurred. Please try again later.")
        await query.answer("Error processing command")

async def handle_text_message(update: Update, context: CallbackContext):
    """Handles text messages."""
    user_id = update.effective_user.id
    text = update.message.text.lower()
    logger.info(f"Handling text message from user {user_id}: {text}")

    try:
        if context.user_data.get("waiting_for_code"):
            logger.info("Ignoring message as user is waiting for code.")
            return

        # Handle specific commands
        if "предварительные" in text or "пм" in text:
            await course_manager.send_preliminary_material(update, context)
            return

        if "текущий урок" in text or "ту" in text:
            await course_manager.get_current_lesson(update, context)
            return

        if "галерея дз" in text or "гдз" in text:
            await gallery_manager.show_gallery(update, context)
            return

        if "тарифы" in text or "ТБ" in text:
            await shop_manager.show_tariffs(update, context)
            return

        if "поддержка" in text or "пд" in text:
            await support_manager.start_support_request(update, context)
            return

        await safe_reply(update, context, "Я не понимаю эту команду.")

    except Exception as e:
        logger.error(f"Error in handle_text_message: {e}")
        await safe_reply(update, context, "Произошла ошибка. Попробуйте позже.")


def parse_delay_from_filename( filename):
    """
    Извлекает время задержки из имени файла. TODO повторяет функционал get_lesson_files
    Возвращает задержку в секундах или None, если задержка не указана.
    """
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    match = DELAY_PATTERN.search(filename)
    if not match:
        return None

    value, unit = match.groups()
    value = int(value)

    if unit == "m":  # минуты
        return value * 60
    elif unit == "h":  # часы
        return value * 3600
    return None

async def send_file(bot, chat_id, file_path, file_name):
    """
    Отправляет файл пользователю с улучшенной обработкой ошибок и подробным логированием.

    Args:
        bot: Объект бота Telegram.
        chat_id: ID чата, куда нужно отправить файл.
        file_path: Путь к файлу.
        file_name: Имя файла (для отправки как документа).
    """
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    logger.info(f"Начинаем отправку файла: {file_name} ({file_path}) в чат {chat_id}")

    try:
        # Проверяем, существует ли файл
        if not os.path.exists(file_path):
            logger.error(f"Файл не найден: {file_path}")
            await bot.send_message(chat_id=chat_id, text="Файл не найден. Пожалуйста, обратитесь в поддержку.")
            return  # Важно: выходим из функции, если файл не найден

        # Определяем MIME-тип файла
        mime_type = mimetypes.guess_type(file_path)[0]
        if not mime_type:
            logger.warning(
                f"Не удалось определить MIME-тип для файла: {file_path}. Используем 'application/octet-stream'.")
            mime_type = 'application/octet-stream'

        logger.info(f"Определен MIME-тип файла: {mime_type}")

        # Открываем файл для чтения в бинарном режиме
        with open(file_path, "rb") as file:
            # Отправляем файл в зависимости от MIME-типа
            if mime_type.startswith('image/'):
                logger.info(f"Отправляем файл как изображение.")
                await bot.send_photo(chat_id=chat_id, photo=file)
            elif mime_type.startswith('video/'):
                logger.info(f"Отправляем файл как видео.")
                await bot.send_video(chat_id=chat_id, video=file)
            elif mime_type.startswith('audio/'):
                logger.info(f"Отправляем файл как аудио.")
                await bot.send_audio(chat_id=chat_id, audio=file)
            else:
                logger.info(f"Отправляем файл как документ.")
                await bot.send_document(chat_id=chat_id, document=file, filename=file_name)

        logger.info(f"Файл {file_name} успешно отправлен в чат {chat_id}")

    except Exception as e:
        # Обрабатываем любые исключения, которые могут возникнуть
        logger.exception(
            f"Ошибка при отправке файла {file_name} в чат {chat_id}: {e}")  # Используем logger.exception для трассировки стека
        await bot.send_message(
            chat_id=chat_id,
            text="Произошла ошибка при отправке файла. Пожалуйста, попробуйте позже или обратитесь в поддержку."
        )


async def check_last_lesson( update: Update, context: CallbackContext):
    """Checks the number of remaining lessons in the course and shows InlineKeyboard."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id

    try:
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            logger.info("17 check_last_lesson: Callback query received.")
        else:
            query = None
            logger.warning("17 check_last_lesson: This function should be called from a callback query.")
            await safe_reply(update, context, "17 This function can only be used via button press.")  # added context
            return None

        # Get active_course_id from users
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await safe_reply(update, context, "У вас не активирован курс. Пожалуйста, введите кодовое слово.")
            logger.info("17 check_last_lesson: No active course found for user.")
            return None

        active_course_id = active_course_data[0].split("_")[0]
        logger.info(f"17check_last_lesson: active_course_id='{active_course_id}'")

        # Get the number of available lesson files for the course
        count = 0
        while True:
            lesson_paths = [
                f"courses/{active_course_id}/lesson{count + 1}.md",
                f"courses/{active_course_id}/lesson{count + 1}.html",
                f"courses/{active_course_id}/lesson{count + 1}.txt",
            ]
            found = any(os.path.exists(path) for path in lesson_paths)
            if not found:
                break
            count += 1
        logger.warning(f"check_last_lesson: Number of available lessons = {count}")

        # Get the user's current progress
        cursor.execute(
            "SELECT progress FROM user_courses WHERE user_id = ? AND course_id LIKE ?",
            (user_id, f"{active_course_id}%"),
        )
        progress_data = cursor.fetchone()
        current_lesson = progress_data[0] if progress_data else 0

        # If the current lesson is the last one
        if current_lesson >= count:
            keyboard = [
                [
                    InlineKeyboardButton(
                        "Перейти в чат болтать", url=COMMUNITY_CHAT_URL
                    )
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await safe_reply(update, context,
                             "Поздравляем! Вы прошли все уроки этого курса! Вы можете перейти в чат, чтобы поделиться впечатлениями и пообщаться с другими участниками.",
                             reply_markup=reply_markup,
                             )
        else:
            await safe_reply(update, context, "В этом курсе еще есть уроки. Продолжайте обучение!")
        # Returns count, so that we know how many lessons there
        return count

    except Exception as e:
        logger.error(f"check_last_lesson: Error while checking the last lesson: {e}")
        await safe_reply(update, context, "Произошла ошибка при проверке последнего урока.")
        return None

async def cancel (update, context):
    await update.message.reply_text("Разговор завершён.")
    return ConversationHandler.END

# Add error handler to catch and log any unhandled exceptions
async def error_handler(update: Update, context: CallbackContext):
    """Log Errors caused by Updates."""
    logger.error(f"Update {update} caused error {context.error}")
    
    # Send error message to admin
    error_message = f"An error occurred:\nUpdate: {update}\nError: {context.error}"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=error_message)
        except Exception as e:
            logger.error(f"Failed to send error message to admin {admin_id}: {e}")

def setup_handlers(application: Application, conv_handler: ConversationHandler, 
                  menu_manager: MenuManager, reminder_manager: ReminderManager,
                  shop_manager: ShopManager, course_manager: CourseManager,
                  gallery_manager: GalleryManager, support_manager: SupportManager) -> None:
    """Sets up all handlers for the application."""
    application.add_handler(conv_handler)

    # Menu and info commands
    application.add_handler(CommandHandler("menu", menu_manager.show_main_menu))
    application.add_handler(CommandHandler("info", menu_manager.info_command))
    application.add_handler(CommandHandler("admins", menu_manager.admins_command))
    
    # Reminder commands
    application.add_handler(CommandHandler("reminders", reminder_manager.show_reminders))
    application.add_handler(CommandHandler("set_morning", lambda update, context: 
        reminder_manager.set_reminder(update, context, "morning")))
    application.add_handler(CommandHandler("set_evening", lambda update, context: 
        reminder_manager.set_reminder(update, context, "evening")))
    application.add_handler(CommandHandler("disable_reminders", reminder_manager.disable_reminders))
    
    # Course commands
    application.add_handler(CommandHandler("course", course_manager.course_management))
    application.add_handler(CommandHandler("lesson", course_manager.get_current_lesson))
    application.add_handler(MessageHandler(
        filters.PHOTO | filters.Document.ALL, 
        course_manager.handle_homework
    ))
    
    # Shop commands
    application.add_handler(CommandHandler("tariffs", shop_manager.show_tariffs))
    application.add_handler(CommandHandler("buy", shop_manager.handle_buy_tariff))
    
    # Gallery commands
    application.add_handler(CommandHandler("gallery", gallery_manager.show_gallery))
    
    # Support commands
    application.add_handler(CommandHandler("support", support_manager.start_support_request))
    
    # Course-related callbacks
    application.add_handler(CallbackQueryHandler(
        course_manager.handle_course_callback, 
        pattern="^(change_tariff|my_courses|hw_history)$"
    ))
    
    # Other callback queries
    application.add_handler(CallbackQueryHandler(button_handler))


def main():
    try:
        # Initialize database
        db = DatabaseConnection()
        create_all_tables()

        # Load configurations
        courses = load_courses()
        bonuses = load_bonuses()
        ad_config = load_ad_config()
        
        global bonuses_config
        bonuses_config = bonuses
        
        if TOKEN is None:
            raise ValueError("Bot token not found. Please set the TOKEN environment variable.")

        # Initialize application and scheduler
        application = ApplicationBuilder().token(TOKEN).persistence(persistence).build()
        scheduler = AsyncIOScheduler()
        
        # Initialize managers
        managers = {
            'menu': MenuManager(),
            'reminder': ReminderManager(),
            'shop': ShopManager(
                admin_group_id=ADMIN_GROUP_ID,
                tariffs_file=CONFIG_FILES["TARIFFS"],
                payment_info_file=CONFIG_FILES["PAYMENT_INFO"]
            ),
            'course': CourseManager(),
            'purchase': PurchaseManager(
                admin_group_id=ADMIN_GROUP_ID,
                admin_ids=ADMIN_IDS
            ),
            'stats': StatsManager(ADMIN_IDS),
            'token': TokenManager(ADMIN_IDS),
            'gallery': GalleryManager(),
            'support': SupportManager(ADMIN_GROUP_ID),
            'scheduler': SchedulerManager(),
            'admin': AdminManager(ADMIN_IDS)  # Add AdminManager
        }
        
        # Set up manager dependencies
        application.bot_data['managers'] = managers
        managers['token'].shop_manager = managers['shop']
        managers['shop'].token_manager = managers['token']
        managers['course'].token_manager = managers['token']
        managers['course'].stats_manager = managers['stats']
        
        # Create conversation manager and handler
        conversation_manager = ConversationManager(
            managers['menu'],
            managers['course'],
            managers['purchase'],
            managers['support']
        )
        conv_handler = conversation_manager.create_conversation_handler()
        
        # Set up all handlers
        if __name__ == "__main__":
            # Move these handlers into setup_handlers function
            setup_handlers(
                application, 
                conv_handler, 
                managers['menu'], 
                managers['reminder'], 
                managers['shop'], 
                managers['course'],
                managers['gallery'],
                managers['support']
            )
            main()
        
        # Set up remaining handlers
        application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
        application.add_error_handler(error_handler)
        
          # Set up job queue
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_repeating(
                callback=managers['reminder'].send_reminders,
                interval=timedelta(minutes=1),  # 60 seconds = 1 minute
                first=10.0  # Start first run after 10 seconds
            )
        else:
            logger.error("Failed to initialize job queue")

        # Start scheduler and bot
        scheduler.start()
        logger.info("Bot started successfully...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Critical error in main: {e}")
        raise
    finally:
        db.close()
        logger.info("Bot shutdown complete")

if __name__ == "__main__":
    main()
    # Add homework approval handlers
    application.add_handler(CallbackQueryHandler(
        course_manager.handle_homework_approval,
        pattern='^hw_(approve|reject)_\d+'
    ))
    
    # Add admin comment handler
    application.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & filters.User(ADMIN_IDS),
        managers['admin'].save_admin_comment
    ))