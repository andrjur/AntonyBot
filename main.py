# main.py

import os
import time
from datetime import timedelta
import mimetypes


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
    PicklePersistence,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

# Local imports
from database import (
    DatabaseConnection,
    create_all_tables,
    load_courses,
    load_bonuses,

)
from utils import safe_reply, logger, get_db_and_user, db_handler
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

from constants import (
    WAIT_FOR_NAME,
    WAIT_FOR_CODE,
    ACTIVE,
    COURSE_SETTINGS,
    WAIT_FOR_SUPPORT_TEXT,
    WAIT_FOR_SELFIE,
    WAIT_FOR_DESCRIPTION,
    WAIT_FOR_CHECK,
    WAIT_FOR_GIFT_USER_ID,
    WAIT_FOR_PHONE_NUMBER
)


# Manager imports
from menu_manager import MenuManager
from reminder_manager import ReminderManager
from shop_manager import ShopManager

from course_manager import CourseManager   #course_manager,

from purchase_manager import PurchaseManager
from stats_manager import StatsManager
from token_manager import TokenManager
from gallery_manager import GalleryManager
from support_manager import SupportManager
from scheduler_manager import SchedulerManager
from admin_manager import AdminManager
from conversation_manager import ConversationManager
from database import load_ad_config, load_course_data, load_delay_messages
from constants import ADMIN_GROUP_ID, CONFIG_FILES

from constants import DELAY_PATTERN

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))

# Update persistence initialization
persistence = PicklePersistence(filepath=PERSISTENCE_FILE)

# Initialize database and managers
db = DatabaseConnection()


# Load configurations
bonuses_config = None

ad_config = load_ad_config()
course_data = load_course_data(CONFIG_FILES["COURSES"])
delay_messages = load_delay_messages()

logger.info(f"Loaded {len(delay_messages)} delay messages")

# не работает, скотина и всё ломает. Оставлена в назидание
# async def logging_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Логирует все входящие сообщения."""
#     try:
#         user_id = update.effective_user.id if update.effective_user else None
#         state = context.user_data['state'] if context.user_data else 'NO_STATE'
#         logger.info(f"Пользователь {user_id} находится в состоянии {state}")
#         return True  # Продолжаем обработку
#     except Exception as e:
#         logger.error(f"Ошибка в logging_middleware: {e}")
#         return True  # Важно не блокировать обработку

# персистентность
persistence = PicklePersistence(filepath="bot_data.pkl")


# Регулярное выражение для извлечения времени задержки из имени файла
# DELAY_PATTERN = re.compile(r"_(\d+)(hour|min|m|h)$") расширение сраное забыли
#DELAY_PATTERN = re.compile(r"_(\d+)(hour|min|m|h)(?:\.|$)")

logger.info(
    f"ПОЕХАЛИ {DEFAULT_LESSON_DELAY_HOURS=} {DEFAULT_LESSON_INTERVAL=} время старта {time.strftime('%d/%m/%Y %H:%M:%S')}")

managers = {}



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

    logger.info(f"45 button_handler  {course_manager=}")

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
            logger.info(f"46 ща вызовем  {data=} ... и handlers[data]= {handlers[data]}")
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
    logger.info(f"50 Handling text message from user {user_id}: {text}")

    try:
        if context.user_data.get("waiting_for_code"):
            logger.info("51 Ignoring message as user is waiting for code.")
            return

        # Handle specific commands
        if "предварительные" in text or "пм" in text:
            await managers['course'].send_preliminary_material(update, context)
            return

        if "текущий урок" in text or "ту" in text:
            logger.info(f"55 main вызов get_current_lesson ")
            logger.info(f"56 {update=}, {context=} ")
            await managers['course'].get_current_lesson(update, context)

            return

        if "галерея дз" in text or "гдз" in text:
            await context.bot_data['galery']['menu'].show_gallery(update, context)

            return

        if "тарифы" in text or "ТБ" in text:
            await context.bot_data['shop'].show_tariffs(update, context)
            return

        if "поддержка" in text or "пд" in text:
            await context.bot_data['support']['menu'].start_support_request(update, context)

            return

        # Если это не команда, считаем, что это имя пользователя
        logger.info(f"отлично это будет имя {text} для {user_id}")

        # Сохраняем имя пользователя в контекст, чтобы использовать его позже
        context.user_data['full_name'] = text

        await safe_reply(update, context, "Имя введено, жду код")

        # Устанавливаем состояние ожидания кода в user_data
        context.user_data['waiting_for_code'] = True  # <--- ВОТ ЭТО ВАЖНО

        # Возвращаем состояние ожидания кода
        return WAIT_FOR_CODE

    except Exception as e:
        logger.error(f"Error in handle_text_message: {e}")
        await safe_reply(update, context, "Произошла ошибка. Попробуйте позже.")
        return ConversationHandler.END  # Завершаем диалог при ошибке


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

        return count  # Returns count, so that we know how many lessons there

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
    try:
        await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=error_message)
    except Exception as e:
        logger.error(f"Failed to send error message to admin group {ADMIN_GROUP_ID}: {e}")


def register_main_menu_handlers(application: Application, managers: dict):
    """Регистрация обработчиков кнопок главного меню."""
    try:
        application.add_handler(CallbackQueryHandler(
            managers['course'].get_current_lesson,
            pattern="^get_current_lesson$"
        ))
        application.add_handler(CallbackQueryHandler(
            managers['gallery'].show_gallery,
            pattern="^gallery$"
        ))
        application.add_handler(CallbackQueryHandler(
            managers['shop'].show_tariffs,
            pattern="^tariffs$"
        ))
        application.add_handler(CallbackQueryHandler(
            managers['course'].show_course_settings,
            pattern="^course_settings$"
        ))
        application.add_handler(CallbackQueryHandler(
            managers['stats'].show_statistics,
            pattern="^statistics$"
        ))
        application.add_handler(CallbackQueryHandler(
            managers['support'].start_support_request,
            pattern="^support$"
        ))
    except Exception as e:
        logger.error(f"Ошибка при регистрации обработчиков главного меню: {e}")
        raise

def setup_handlers(
    application: Application,
    conv_handler: ConversationHandler,
    menu_manager: MenuManager,
    reminder_manager: ReminderManager,
    shop_manager: ShopManager,
    stats_manager: StatsManager,
    course_manager: CourseManager,
    gallery_manager: GalleryManager,
    support_manager: SupportManager
) -> None:
    """
    Регистрация всех обработчиков для приложения.
    """
    try:
        # 1. Регистрация ConversationHandler
        application.add_handler(conv_handler)

        # 2. Команды меню и информации
        register_menu_commands(application, menu_manager)

        # 3. Команды напоминаний
        register_reminder_commands(application, reminder_manager)

        # 4. Команды курсов
        register_course_commands(application, course_manager)

        # 5. Команды магазина
        register_shop_commands(application, shop_manager)
        # Set up remaining handlers
        application.add_handler(CommandHandler("start", menu_manager.start))  # !!!!

        # 6. Команды галереи
        register_gallery_commands(application, gallery_manager)

        # 7. Команды поддержки
        register_support_commands(application, support_manager)

        # 8. Обработчики кнопок главного меню
        register_main_menu_handlers(application, {
            'course': course_manager,
            'gallery': gallery_manager,
            'shop': shop_manager,
            'stats': stats_manager,
            'support': support_manager
        })

        # 8. Обработчики callback'ов
        register_callback_handlers(application, course_manager)

        # 9. Дополнительные обработчики
        register_additional_handlers(application, managers)

    except Exception as e:
        logger.error(f"Ошибка при регистрации обработчиков: {e}")
        raise


# Вспомогательные функции для регистрации обработчиков
def register_menu_commands(application: Application, menu_manager: MenuManager):
    """Регистрация команд меню."""
    application.add_handler(CommandHandler("menu", menu_manager.show_main_menu))
    application.add_handler(CommandHandler("info", menu_manager.info_command))
    application.add_handler(CommandHandler("admins", menu_manager.admins_command))

    # Регистрация обработчиков кнопок
    application.add_handler(CallbackQueryHandler(menu_manager.handle_gallery, pattern="^gallery$"))
    application.add_handler(CallbackQueryHandler(menu_manager.handle_tariffs, pattern="^tariffs$"))
    application.add_handler(CallbackQueryHandler(menu_manager.handle_course_settings, pattern="^course_settings$"))
    application.add_handler(CallbackQueryHandler(menu_manager.handle_statistics, pattern="^statistics$"))
    application.add_handler(CallbackQueryHandler(menu_manager.handle_support, pattern="^support$"))


def register_reminder_commands(application: Application, reminder_manager: ReminderManager):
    """Регистрация команд напоминаний."""
    application.add_handler(CommandHandler("reminders", reminder_manager.show_reminders))
    application.add_handler(CommandHandler("set_morning", lambda update, context:
        reminder_manager.set_reminder(update, context, "morning")))
    application.add_handler(CommandHandler("set_evening", lambda update, context:
        reminder_manager.set_reminder(update, context, "evening")))
    application.add_handler(CommandHandler("disable_reminders", reminder_manager.disable_reminders))


def register_course_commands(application: Application, course_manager: CourseManager):
    """Регистрация команд курсов."""
    application.add_handler(CommandHandler("course", course_manager.course_management))
    application.add_handler(CommandHandler("lesson", course_manager.get_current_lesson))
    application.add_handler(MessageHandler(
        filters.PHOTO | filters.Document.ALL,
        course_manager.handle_homework
    ))
    application.add_handler(CallbackQueryHandler(course_manager.get_current_lesson, pattern="^get_current_lesson$"))


def register_shop_commands(application: Application, shop_manager: ShopManager):
    """Регистрация команд магазина."""
    application.add_handler(CommandHandler("tariffs", shop_manager.show_tariffs))
    application.add_handler(CommandHandler("buy", shop_manager.handle_buy_tariff))


def register_gallery_commands(application: Application, gallery_manager: GalleryManager):
    """Регистрация команд галереи."""
    application.add_handler(CommandHandler("gallery", gallery_manager.show_gallery))


def register_support_commands(application: Application, support_manager: SupportManager):
    """Регистрация команд поддержки."""
    application.add_handler(CommandHandler("support", support_manager.start_support_request))


def register_callback_handlers(application: Application, course_manager: CourseManager):
    """Регистрация callback-обработчиков."""
    application.add_handler(CallbackQueryHandler(
        course_manager.handle_course_callback,
        pattern="^(change_tariff|my_courses|hw_history)$"
    ))
    application.add_handler(CallbackQueryHandler(
        course_manager.handle_homework_approval,
        pattern='^hw_(approve|reject)_\d+'
    ))


def register_additional_handlers(application: Application, managers: dict):
    """Регистрация дополнительных обработчиков."""
    application.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & filters.User(ADMIN_IDS),
        managers['admin'].save_admin_comment
    ))
    application.add_handler(CallbackQueryHandler(button_handler))

def main():
    global managers

    try:
        # Initialize application and scheduler
        application = ApplicationBuilder().token(TOKEN).persistence(persistence).build()
        scheduler = AsyncIOScheduler()

        # Initialize database
        db = DatabaseConnection()
        application.bot_data['db'] = db

        logger.info(f"1 перед create_all_tables() db = {db}.")
        create_all_tables()
        logger.info("БД жива")

        # Загрузка конфигураций
        courses = load_courses()
        bonuses = load_bonuses()
        ad_config = load_ad_config()

        global bonuses_config
        bonuses_config = bonuses

        if TOKEN is None:
            logger.error("Bot token not found. Please set the TOKEN environment variable.")



        logger.info(f"3 создали приложение ")

        # Инициализация менеджеров через объекты
        managers = {
            'menu': MenuManager(db),
            'reminder': ReminderManager(db),
            'shop': ShopManager(db),
            'course': CourseManager(db),
            'purchase': PurchaseManager(db),
            'stats': StatsManager(db),
            'token': TokenManager(db),
            'gallery': GalleryManager(db),
            'support': SupportManager(db),
            'scheduler': SchedulerManager(db),
            'admin': AdminManager(db)
        }
        logger.info(f" 4 Managers initialized: {managers}")

        # Устанавливаем зависимости между менеджерами
        application.bot_data['managers'] = managers
        managers['token'].shop_manager = managers['shop']
        managers['shop'].token_manager = managers['token']
        managers['course'].token_manager = managers['token']
        managers['course'].stats_manager = managers['stats']

        logger.info(f" 5 conversation_manager initialized")

        # Загружаем данные о курсах из файла CONFIG_FILES["COURSES"]
        course_data = load_course_data(CONFIG_FILES["COURSES"])
        logger.info(f" 6 Данные о курсах загружены: {course_data}")
        if not course_data:
            logger.error("Не удалось загрузить данные о курсах. Бот не сможет функционировать правильно.")
            return  # Завершаем выполнение, если данные о курсах не загружены

        logger.info(f"Данные о курсах загружены: {len(course_data)} шт курсов")


        # Создаем ConversationManager и ConversationHandler
        conversation_manager = ConversationManager(
            db,
            managers['menu'],
            managers['course'],
            managers['purchase'],
            managers['support'],
            course_data
        )

        conv_handler = conversation_manager.create_conversation_handler()

        logger.info(f"7 before app")

        # Регистрируем все обработчики через setup_handlers
        setup_handlers(
            application,
            conv_handler,
            managers['menu'],
            managers['reminder'],
            managers['shop'],
            managers['stats'],
            managers['course'],
            managers['gallery'],
            managers['support']
        )

        logger.info(f"9 после setup_handlers")

        # Регистрируем обработчик ошибок
        application.add_error_handler(error_handler)

        logger.info(f"15 внизу мэина")

        # Настраиваем очередь задач (job queue)
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_repeating(
                callback = managers['reminder'].send_reminders,
                interval = timedelta(minutes=1),  # Интервал 1 минута
                first = 10.0  # Первая задача через 10 секунд

            )
        else:
            logger.error("Failed to initialize job queue")

        # Запускаем планировщик и бота
        scheduler.start()
        logger.info("Bot started successfully...")
        application.run_polling()

    except Exception as e:
        logger.critical(f"Critical error in main: {e}")

    finally:
        db.close()
        logger.info("Bot shutdown complete")


if __name__ == "__main__":
    main()


