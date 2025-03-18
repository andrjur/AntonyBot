# utils.py
import logging
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


async def safe_reply(update: Update, context: CallbackContext, text: str,
                     reply_markup: InlineKeyboardMarkup | None = None):
    """
    Безопасно отправляет текстовое сообщение, автоматически определяя тип update.

    Args:
        update: Объект Update от Telegram.
        context: Объект CallbackContext.
        text: Текст сообщения для отправки.
        reply_markup: (необязательный) Объект InlineKeyboardMarkup для добавления к сообщению.
    """
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
