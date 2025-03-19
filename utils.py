# utils.py
import logging
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

async def safe_reply(update: Update, context: CallbackContext, text: str,
                    reply_markup: InlineKeyboardMarkup | None = None):
    """Safely sends a text message."""
    # Get user ID safely, handling None case
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        logger.error("Could not get user ID - effective_user is None")
        return

    try:
        if update.callback_query:
            # Если это callback_query, отвечаем на него
            await update.callback_query.answer()  # Подтверждаем получение callback_query
            if update.callback_query.message:
                await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
            else:
                logger.warning("Это была не кнопка. калбэк - None")
                await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)
        else:
            # Если это обычное сообщение, отправляем новое сообщение
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)

    except TelegramError as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")

def handle_telegram_errors(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except TelegramError as e:
            # Telegram API ошибки (например, сетевые проблемы)
            logger.error(f"Telegram API Error в функции {func.__name__}: {e}")
            update = kwargs.get("update") or args[0] if args else None
            if update:
                await update.effective_message.reply_text(
                    "Ошибка взаимодействия с Telegram. Попробуйте позже."
                )
        except sqlite3.Error as e:
            # Ошибки базы данных
            logger.error(f"Database Error в функции {func.__name__}: {e}")
            update = kwargs.get("update") or args[0] if args else None
            if update:
                await update.effective_message.reply_text(
                    "Ошибка базы данных. Попробуйте позже."
                )
        except Exception as e:
            # Все остальные ошибки
            logger.error(f"Непредвиденная ошибка в функции {func.__name__}: {e}")
            update = kwargs.get("update") or args[0] if args else None
            if update:
                await update.effective_message.reply_text(
                    "Произошла ошибка. Попробуйте позже."
                )
    return wrapper

#  Add a custom error handler decorator
def old_handle_telegram_errors(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except TelegramError as e:
            logger.error(f"Telegram API Error: {e}")
            # Handle specific error types
        except Exception as e:
            logger.error(f"General Error: {e}")

    return wrapper


def is_admin(user_id: int) -> bool:
    """Check if user is an admin."""
    db = DatabaseConnection()
    cursor = db.get_cursor()
    cursor.execute("SELECT level FROM admins WHERE admin_id = ?", (user_id,))
    result = cursor.fetchone()
    return bool(result)


def escape_markdown_v2(text):
    """Escapes special characters for Markdown V2."""
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{char}" if char in escape_chars else char for char in text)


def parse_delay_from_filename(filename):
    """Extracts delay time from filename."""
    match = DELAY_PATTERN.search(filename)
    if not match:
        return None

    value, unit = match.groups()
    value = int(value)

    if unit == "m":  # minutes
        return value * 60
    elif unit == "h":  # hours
        return value * 3600
    return None

async def send_file(bot, chat_id, file_path, file_name):
    """Sends file to user with improved error handling and detailed logging."""
    # ... move the send_file implementation here ...

def get_date(date_string: str):
    """Converts a date string from the format %Y-%m-%d to a date object."""
    try:
        return datetime.strptime(date_string, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None

def format_date(date: date):
    """Formats a date object to a string in the format %Y-%m-%d."""
    return date.strftime("%Y-%m-%d")

def get_ad_message():
    """Возвращает рекламное сообщение """
    courses = load_courses()
    courses_for_bonus = [course for course in courses if "bonus_price" in course]
    if courses_for_bonus:
        ad_message = "Хотите больше контента?\n"
        for course in courses_for_bonus:
            ad_message += (
                f"- Курс '{course['course_name']}' можно приобрести за {course['bonus_price']} antCoins.\n"
            )
        return ad_message
    else:
        return "У нас много интересного! Узнайте больше о доступных курсах и возможностях."


def maybe_add_ad(message_list):
    """Adds an ad message to the list based on the configured percentage."""
    ad_percentage = load_ad_config().get("ad_percentage", 0.3)  # Ensure ad_config is loaded
    if len(message_list) > 0 and random.random() < ad_percentage:
        ad_message = get_ad_message()  # Function to get a promotional message
        message_list.append(ad_message)  # Add it at the end or a random position
    return message_list
