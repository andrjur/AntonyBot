# main.py
import asyncio
import logging
import mimetypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.constants import ParseMode
from telegram.ext import PicklePersistence, ContextTypes

from telegram import (
    Update,
    InputMediaPhoto,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaDocument,
    KeyboardButton,
    ReplyKeyboardMarkup,
    # ReplyKeyboardRemove,  # <--- Добавьте эту строку
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
    Application  # <--- Добавьте это

)

import sqlite3
from datetime import datetime, timedelta, date
import time
from dotenv import load_dotenv
import os
import re
import asyncio
from telegram.error import TelegramError
import json
import random

# Константы для команд (на английском языке)
CMD_LESSON = "lesson"
CMD_INFO = "info"
CMD_HOMEWORK = "homework"
CMD_ADMINS = "admins"

DATABASE_FILE = "bot_db.sqlite"

TARIFFS_FILE = "tariffs.json"

COURSE_DATA_FILE = "courses.json"
AD_CONFIG_FILE = "ad_config.json"  # Путь к файлу с настройками рекламы
BONUSES_FILE = "bonuses.json"  # Путь к файлу с бонусами
DELAY_MESSAGES_FILE = "delay_messages.txt"
PAYMENT_INFO_FILE = "payment_info.json"

# Coin emojis
BRONZE_COIN = "🟤"  # Bronze coin
SILVER_COIN = "⚪️"  # Silver coin
GOLD_COIN = "🟡"  # Gold coin
PLATINUM_COIN = "💎"  # Platinum Coin

TOKEN_TO_RUB_RATE = 100  # 1 token = 100 rubles

WAIT_FOR_REJECTION_REASON_TIMEOUT = 300  # 5 минут в секундах

class DatabaseConnection:
    _instance = None

    def __new__(cls, db_file=DATABASE_FILE):
        if cls._instance is None:
            cls._instance = super(DatabaseConnection, cls).__new__(cls)
            try:
                cls._instance.conn = sqlite3.connect(db_file)
                cls._instance.cursor = cls._instance.conn.cursor()
                logger.info(f"DatabaseConnection: Подключение к {db_file}")
            except sqlite3.Error as e:
                logger.error(f"DatabaseConnection: Ошибка при подключении к базе данных: {e}")
                cls._instance.conn = None
                cls._instance.cursor = None
        return cls._instance

    def get_connection(self):
        return self.conn

    def get_cursor(self):
        return self.cursor

    def close(self):
        if self.conn:
            self.conn.close()
            logger.info("DatabaseConnection: Соединение с базой данных закрыто.")
            self.conn = None
            self.cursor = None


class Course:
    def __init__(self, course_id, course_name, course_type, code_word, price_rub=None, price_tokens=None):
        self.course_id = course_id
        self.course_name = course_name
        self.course_type = course_type
        self.code_word = code_word

        # Extract tariff from course_id
        self.tariff = course_id.split('_')[1] if '_' in course_id else 'default'
        self.price_rub = price_rub
        self.price_tokens = price_tokens

    def __str__(self):
        return f"Course(id={self.course_id}, name={self.course_name}, type={self.course_type}, code={self.code_word}, price_rub={self.price_rub}, price_tokens={self.price_tokens})"


class CustomFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        full_time = super().formatTime(record, datefmt)
        return full_time[-9:]

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO,handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),  # Указываем кодировку utf-8 для файла
        logging.StreamHandler()  # Для вывода в консоль
    ],)


# Замена стандартного Formatter на пользовательский
for handler in logging.getLogger().handlers:
    handler.setFormatter(CustomFormatter('%(asctime)s - %(levelname)s - %(message)s'))

logger = logging.getLogger(__name__)

# Настройка уровня логирования для библиотеки httpx
logging.getLogger("httpx").setLevel(logging.WARNING)


def load_bonuses():
    """Загружает настройки бонусов из файла."""
    try:
        with open(BONUSES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Файл {BONUSES_FILE} не найден. Используются значения по умолчанию.")
        return {
            "monthly_bonus": 1,
            "birthday_bonus": 8,
            "referral_bonus": 4,
            "homework_bonus": 3,
            "course_completion_bonus": 10,
            "bonus_check_interval": 86400,  # 24 hours
        }
    except json.JSONDecodeError:
        logger.error(f"Ошибка при чтении JSON из файла {BONUSES_FILE}. Используются значения по умолчанию.")
        return {
            "monthly_bonus": 1,
            "birthday_bonus": 8,
            "referral_bonus": 4,
            "homework_bonus": 3,
            "course_completion_bonus": 10,
            "bonus_check_interval": 86400,  # 24 hours
        }


def load_courses():
    """Загружает список курсов из файла."""
    try:
        with open(COURSE_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Файл {COURSE_DATA_FILE} не найден.")
        return []
    except json.JSONDecodeError:
        logger.error(f"Ошибка при чтении JSON из файла {COURSE_DATA_FILE}.")
        return []


def load_ad_config():
    """Загружает конфигурацию рекламы из файла."""
    try:
        with open(AD_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Файл {AD_CONFIG_FILE} не найден. Используются значения по умолчанию.")
        return {"ad_percentage": 0.3}  # Default 5% ad percentage
    except json.JSONDecodeError:
        logger.error(f"Ошибка при чтении JSON из файла {AD_CONFIG_FILE}. Используются значения по умолчанию.")
        return {"ad_percentage": 0.3}

bonuses_config = load_bonuses()  # Загружаем бонусы при старте
ad_config = load_ad_config()

def handle_telegram_errors2(func):
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
def handle_telegram_errors(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except TelegramError as e:
            logger.error(f"Telegram API Error: {e}")
            # Handle specific error types
        except Exception as e:
            logger.error(f"General Error: {e}")

    return wrapper


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


def load_course_data(filename):
    """Загружает данные о курсах из JSON файла."""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            courses = []
            logger.info(f"Файл с данными о курсах: {filename}")
            logger.info(f"========курсы data[:2] {data[:2]}")
            for course_info in data:
                try:
                    course = Course(
                        course_id=course_info.get("course_id"),
                        course_name=course_info.get("course_name"),
                        course_type=course_info.get("course_type"),
                        code_word=course_info.get("code_word"),
                        price_rub=course_info.get("price_rub"),
                        price_tokens=course_info.get("price_tokens"),
                    )
                    courses.append(course)

                except TypeError as e:
                    logger.error(f"Ошибка при создании экземпляра Course: {e}, данные: {course_info}")
                except Exception as e:
                    logger.error(f"Неизвестная ошибка при создании экземпляра Course: {e}, данные: {course_info}")

            logger.info(f"346=============КУРсЫ {courses}")
            return {course.code_word: course for course in courses}
    except FileNotFoundError:
        logger.error(f"Файл с данными о курсах не найден: {filename}")
        return {}
    except json.JSONDecodeError:
        logger.error(f"Ошибка при чтении JSON файла: {filename}")
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке данных о курсах: {e}")
        return {}


COURSE_DATA = load_course_data(COURSE_DATA_FILE)


# Функция для загрузки фраз из текстового файла
def load_delay_messages(file_path=DELAY_MESSAGES_FILE):
    """Загружает список фраз из текстового файла."""
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            messages = [line.strip() for line in file if line.strip()]
            logger.info(f"Загружено {len(messages)} фразочек ------------------------- 333")
        return messages

    except FileNotFoundError:
        logger.error(f"Файл c фразами не найден: {file_path}")
        return ["Ф Ещё материал идёт, домашнее задание - можно уже делать."]

    except Exception as e:
        logger.error(f"Ошибка при загрузке фраз из файла: {e}")
        return ["О Ещё материал идёт, домашнее задание - можно уже делать!"]


# Загрузка фраз в начале программы
HARD_CODE_DELAY = 5  # секунд. Даже если 5 часов укажешь
DELAY_MESSAGES = load_delay_messages(DELAY_MESSAGES_FILE)

logger.info(f"DELAY_MESSAGES загружено {len(DELAY_MESSAGES)} строк вот две {DELAY_MESSAGES[:2]}")

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
# Get admin IDs from env, default to empty list if not set
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",") if os.getenv("ADMIN_IDS") else []

# персистентность
persistence = PicklePersistence(filepath="bot_data.pkl")

# Состояния
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
    WAIT_FOR_REJECTION_REASON,  # Добавлено состояние ожидания причины отказа
) = range(11)


# Регулярное выражение для извлечения времени задержки из имени файла
# DELAY_PATTERN = re.compile(r"_(\d+)([mh])$") эта регулярка min не поддерживает
# DELAY_PATTERN = re.compile(r"_(\d+)(hour|min|m|h)$") расширение сраное забыли
DELAY_PATTERN = re.compile(r"_(\d+)(hour|min|m|h)(?:\.|$)")

# Интервал между уроками по умолчанию (в часах)
DEFAULT_LESSON_INTERVAL = 0.1  # интервал уроков 72 часа а не 6 минут!!!

DEFAULT_LESSON_DELAY_HOURS = 3

logger.info(
    f"ПОЕХАЛИ {DEFAULT_LESSON_DELAY_HOURS=} {DEFAULT_LESSON_INTERVAL=} время старта {time.strftime('%d/%m/%Y %H:%M:%S')}")

# Словарь для кэширования данных
USER_CACHE = {}


def get_user_data(user_id: int):  # Добавил conn и cursor
    """Получает данные пользователя из кэша или базы данных."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    
    if user_id in USER_CACHE:
        return USER_CACHE[user_id]

    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    data = cursor.fetchone()

    if data:
        USER_CACHE[user_id] = data
        return data

    return None


def clear_user_cache(user_id: int):  # Добавил conn и cursor
    """Очищает кэш для указанного пользователя."""
    
    logger.info(f" clear_user_cache {user_id} очистили")
    if user_id in USER_CACHE:
        del USER_CACHE[user_id]


async def safe_reply(update: Update, context: CallbackContext, text: str, parse_mode: ParseMode = None,
                     reply_markup: InlineKeyboardMarkup | None = None):
    """    Безопасно отправляет текстовое сообщение, автоматически определяя тип update.
    Args:
        update: Объект Update от Telegram.
        context: Объект CallbackContext.
        text: Текст сообщения для отправки.
        parse_mode: ParseMode = None,
        reply_markup: (необязательный) Объект InlineKeyboardMarkup для добавления к сообщению.    """

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
                await context.bot.send_message(chat_id=user_id, text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            # Если это обычное сообщение, отправляем новое сообщение
            await context.bot.send_message(chat_id=user_id, text=text,parse_mode=parse_mode, reply_markup=reply_markup)

    except TelegramError as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")


# отсыпать ему монет!
def add_coins(user_id: int, amount: int):
    """Добавляет коины пользователю в базе данных."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        cursor.execute(
            """
            INSERT INTO user_tokens (user_id, tokens) 
            VALUES (?, ?)
            ON CONFLICT(user_id) DO 
            UPDATE SET tokens = tokens + ?
            """,
            (user_id, amount, amount),
        )
        conn.commit()
        logger.info(f"Пользователю {user_id} добавлено {amount} коинов.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при добавлении коинов пользователю {user_id}: {e}")


def get_user_tokens(user_id: int) -> int:
    """Получает количество токенов у пользователя."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            return result[0]
        else:
            return 0  # Если пользователя нет в базе, возвращаем 0
    except sqlite3.Error as e:
        logger.error(f"Ошибка при получении количества токенов пользователя {user_id}: {e}")
        return 0  # В случае ошибки возвращаем 0

def is_birthday(user_id: int) -> bool:
    """Проверяет, является ли сегодня день рождения пользователя."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        cursor.execute("SELECT birthday FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result and result[0]:
            birthday_str = result[0]  # Получаем строку с датой дня рождения
            birthday = datetime.strptime(birthday_str, '%Y-%m-%d').date()
            today = date.today()
            return birthday.month == today.month and birthday.day == today.day
        return False
    except sqlite3.Error as e:
        logger.error(f"Ошибка при проверке дня рождения пользователя {user_id}: {e}")
        return False
    except ValueError as e:
        logger.error(f"Ошибка при преобразовании даты дня рождения пользователя {user_id}: {e}. Убедитесь, что формат даты верный (YYYY-MM-DD).")
        return False

async def check_and_award_birthday_bonus(context: CallbackContext):
    """Проверяет, у кого сегодня день рождения, и начисляет бонус."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    try:
        cursor.execute("SELECT user_id FROM users")  # Получаем всех пользователей
        users = cursor.fetchall()

        for user in users:
            user_id = user[0]
            if is_birthday(user_id):
                bonus_amount = bonuses_config.get("birthday_bonus", 5)
                add_coins(user_id, bonus_amount)
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"🎉 С днем рождения! Вам начислено {bonus_amount} коинов в честь вашего дня рождения!",
                    )
                except TelegramError as e:
                    logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

    except sqlite3.Error as e:
        logger.error(f"Ошибка при выборке пользователей для проверки дня рождения: {e}")



# кому платить строго ненадо    
def load_payment_info(filename):
    """Загружает данные оплаты из JSON файла."""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            logger.info(f"Файл с данными об оплате: {filename}")
            return data
    except FileNotFoundError:
        logger.error(f"Файл с данными об оплате не найден: {filename}")
        return {}
    except json.JSONDecodeError:
        logger.error(f"Ошибка при чтении JSON файла: {filename}")
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке данных об оплате: {e}")
        return {}


PAYMENT_INFO = load_payment_info(PAYMENT_INFO_FILE)


async def handle_error(update: Update, context: CallbackContext, error=None):
    """Handles errors that occur in the bot."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    logger.error(f"Произошла ошибка:: {error}")
    await safe_reply(update, context, "Произошла ошибка. Попробуйте позже.")


# получение имени и проверка *
async def handle_user_info(update: Update, context: CallbackContext):  # Добавил conn и cursor
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
        logger.info(f"User {update.effective_user.id} transitioning to  WAIT_FOR_NAME state")
        return WAIT_FOR_NAME

    logger.info(f" full_name {full_name} ==============================")

    try:
        # Сохранение имени пользователя в базе данных
        cursor.execute(
            """
            INSERT INTO users (user_id, full_name) 
            VALUES (?, ?)
            ON CONFLICT(user_id) DO 
            UPDATE SET full_name = excluded.full_name
            """,
            (user_id, full_name),
        )

        # Проверка существования токенов для пользователя
        cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
        tokens_data = cursor.fetchone()

        if tokens_data is None:
            # Если токены не существуют, создаем новую запись с начальным количеством токенов
            cursor.execute(
                "INSERT INTO user_tokens (user_id, tokens) VALUES (?, ?)",
                (user_id, 3)  # Начальное количество токенов
            )
        else:
            # Если запись существует, можно обновить количество токенов при необходимости
            logger.info(f"Пользователь {user_id} уже имеет {tokens_data[0]} токенов.")

        # Сохранение изменений в базе данных

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
        logger.info(f"User {update.effective_user.id} transitioning to  WAIT_FOR_CODE state")
        return WAIT_FOR_CODE
    except sqlite3.Error as e:
        logger.error(f"Ошибка SQLite: {e}")
        await update.effective_message.reply_text("Произошла ошибка при работе с базой данных. Попробуйте позже.")
        logger.info(f"User {update.effective_user.id} transitioning to  WAIT_FOR_NAME state")
        return WAIT_FOR_NAME

    except Exception as e:
        # Обработка ошибок при сохранении имени
        logger.error(f"Ошибка при сохранении имени: {e}")
        logger.error(f"Ошибка SQL при сохранении пользователя {user_id}: {e}")
        await update.effective_message.reply_text("Произошла ошибка при сохранении данных. Попробуйте снова.")
        logger.info(f"User {update.effective_user.id} transitioning to  WAIT_FOR_NAME state")
        return WAIT_FOR_NAME


# проверка оплаты через кодовые слова *
@handle_telegram_errors
async def handle_code_words(update: Update, context: CallbackContext):
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        logger.error("Could not get user ID - effective_user is None")
        logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
        return ConversationHandler.END

    user_code = update.message.text.strip() if update.message and update.message.text else ""

    logger.info(f" handle_code_words {user_id}   {user_code}")
    logger.info(f"345 COURSE_DATA {COURSE_DATA}   ")

    if user_code in COURSE_DATA:
        try:
            # Активируем курс
            await activate_course(update, context, user_id, user_code)
            logger.info(f" 346 активирован {user_id}   ")

            # Отправляем сообщение об успешной активации
            await safe_reply(update, context, "Курс активирован! Получите первый урок.")

            # Отправляем текущий урок
            await get_current_lesson(update, context)

            # Сбрасываем состояние ожидания кодового слова
            if context.user_data is not None:
                context.user_data["waiting_for_code"] = False

            logger.info(f" 348   return ACTIVE")
            logger.info(f"User {update.effective_user.id} transitioning to  ACTIVE state")
            return ACTIVE  # Переходим в состояние ACTIVE

        except Exception as e:
            logger.error(f"Ошибка при активации курса: {e}")
            await safe_reply(update, context, "Произошла ошибка при активации курса. Попробуйте позже.")
            logger.info(f"User {update.effective_user.id} transitioning to  WAIT_FOR_CODE state")
            return WAIT_FOR_CODE
    else:
        # Неверное кодовое слово
        logger.info(f" Неверное кодовое слово.   return WAIT_FOR_CODE")
        await safe_reply(update, context, "Неверное кодовое слово. Попробуйте еще раз.")
        logger.info(f"User {update.effective_user.id} transitioning to  WAIT_FOR_CODE state")
        return WAIT_FOR_CODE



def escape_markdown_v2(text):
    """Экранирует специальные символы для Markdown V2."""
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{char}" if char in escape_chars else char for char in text)


# Commands
@handle_telegram_errors
async def lesson_command(update: Update, context: CallbackContext):
    """Обработчик команды /урок."""
    logger.warning("сраная обёртка")
    await get_current_lesson(update, context)


@handle_telegram_errors
async def info_command(update: Update, context: CallbackContext):
    """Обработчик команды /инфо."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user = update.effective_user
    # Safely get user_id, handling None case
    user_id = user.id if user else None
    if user_id is None:
        logger.error("Could not get user ID - user is None")
        return
    cursor.execute("SELECT full_name, active_course_id FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()

    if user_data:
        full_name = user_data[0]
        active_course_id = user_data[1]

        if active_course_id:
            await update.message.reply_text(
                f"Информация о пользователе:\n"
                f"Имя: {full_name}\n"
                f"Активный курс: {active_course_id}\n"
                f"Вы можете использовать команду /{CMD_LESSON} для получения текущего урока."
            )
        else:
            await update.message.reply_text(
                f"Информация о пользователе:\n"
                f"Имя: {full_name}\n"
                f"У вас нет активного курса. Активируйте курс, введя кодовое слово."
            )
    else:
        await update.message.reply_text(
            "Вы не зарегистрированы. Пожалуйста, начните с команды /start и введите ваше имя и кодовое слово."
        )


@handle_telegram_errors
async def homework_command(update: Update, context: CallbackContext):
    """Обработчик команды /сдать_домашку."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Для сдачи домашнего задания используйте соответствующую кнопку в главном меню.",
    )


@handle_telegram_errors
async def admins_command( update: Update, context: CallbackContext):
    """Обработчик команды /написать_админам."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    context.user_data['state'] = WAIT_FOR_SUPPORT_TEXT  # SET status
    await update.message.reply_text(
        "Пожалуйста, введите ваше сообщение для администраторов:"
    )


# текущий урок заново - из меню 321
@handle_telegram_errors
async def get_current_lesson(update: Update, context: CallbackContext):
    """Отправляет все материалы текущего урока."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f"get_current_lesson: user_id={user_id}")

    try:
        # Получаем active_course_id из users
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await context.bot.send_message(chat_id=user_id, text="Активируйте курс через кодовое слово.")
            return

        active_course_id_full = active_course_data[0]
        active_course_id = active_course_id_full.split("_")[0]
        logger.info(f"active_course_id: {active_course_id}")

        # Получаем progress (номер урока) из user_courses
        cursor.execute(
            "SELECT progress FROM user_courses WHERE user_id = ? AND course_id = ?",
            (user_id, active_course_id_full),
        )
        progress_data = cursor.fetchone()

        # Если progress не найден, начинаем с первого урока
        if not progress_data:
            lesson = 1
            cursor.execute(
                "INSERT INTO user_courses (user_id, course_id, course_type, progress, tariff) VALUES (?, ?, ?, ?, ?)",
                (user_id, active_course_id_full, context.user_data.get("course_type", "main"), lesson,
                 context.user_data.get("tariff", "self_check")),
            )
            await conn.commit()
            logger.warning(f"Начали курс с первого урока: {active_course_id_full}")
            await context.bot.send_message(chat_id=user_id, text="Вы начинаете курс с первого урока.")
        else:
            lesson = progress_data[0]

        # Получаем текст урока
        logger.info(f"1514 Получаем текст урока:")
        lesson_data = get_lesson_text(lesson, active_course_id)
        logger.info(f"1515 Получили lesson_data длиной {len(lesson_data)} ")

        if not lesson_data:
            logger.error(
                f"Файл с уроком не найден: lessons/{active_course_id}/lesson{lesson}.md, lessons/{active_course_id}/lesson{lesson}.html или lessons/{active_course_id}/lesson{lesson}.txt")
            await context.bot.send_message(chat_id=user_id, text="Файл с уроком не найден.")
            return

        lesson_text, parse_mode = lesson_data
        logger.info(f"777 lesson_text={lesson_text[:35]}  {parse_mode=} отправляем методом context.bot.send_message() ---")
        # Отправляем текст урока
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=lesson_text,
                parse_mode=parse_mode,
            )
            logger.info(f"1517 отправили await context.bot.send_message(")
        except Exception as e:
            logger.error(f"Ошибка при отправке текста урока: {e}")
            await context.bot.send_message(chat_id=user_id, text=f"Ошибка при отправке текста урока: {e}")

            # Отправляем файлы урока
            logger.info(f"8880 Перед await get_lesson_files user_id={user_id} lesson={lesson} active_course_id={active_course_id}")
            lesson_files = await get_lesson_files(user_id, lesson, f"courses\\{active_course_id}")
            logger.info(f"8881 После  get_lesson_files {lesson_files=}")
            await send_lesson_files(update, context, lesson_files)  # Используем новую функцию

        # Сообщение о количестве отправленных файлов
        await context.bot.send_message(chat_id=user_id, text=f"Отправлено хз сколько файлов.")

        # Рассчитываем время следующего урока
        next_lesson = lesson + 1
        next_lesson_release_time = datetime.now() + timedelta(hours=DEFAULT_LESSON_INTERVAL)
        next_lesson_release_str = next_lesson_release_time.strftime("%d-%m-%Y %H:%M:%S")
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Следующий урок {next_lesson} будет доступен {next_lesson_release_str}.",
        )
        logger.info(f"Следующий урок {next_lesson} будет доступен {next_lesson_release_str}.")

        # Показываем главное меню
        await show_main_menu (update, context)

    except Exception as e:
        logger.error(f"Ошибка при получении текущего урока: {e}")
        await context.bot.send_message(chat_id=user_id, text="Ошибка при получении текущего урока. Попробуйте позже.")



async def send_lesson_files(update: Update, context: CallbackContext, lesson_files):
    """Отправляет файлы урока, используя функцию send_file."""
    user_id = update.effective_user.id
    for i, file_info in enumerate(lesson_files, start=1):
        file_path = file_info["path"]
        file_type = file_info["type"]
        delay = file_info["delay"]
        delay_message = file_info["delay_message"]  # Добавляем получение delay_message
        logger.info(f"000 Файл {i}: {file_path=}, {file_type=}, {delay=}")

        # Задержка перед отправкой
        if delay > 0:
            # Выбираем случайное сообщение из DELAY_MESSAGES
            if not delay_message:
                delay_message = random.choice(DELAY_MESSAGES)  # Заменяем выбор сообщения
            logger.info(f"Ожидание {delay} секунд перед отправкой файла {file_path}. Сообщение: {delay_message}")
            await context.bot.send_message(chat_id=user_id, text=delay_message)
            delay = HARD_CODE_DELAY  # todo починить HARD_CODE_DELAY при рефакторинге
            logger.warning(f"Ожидание стало {delay} секунд. Fix it in beta release ")
            await asyncio.sleep(delay)

        try:
            await send_file(user_id, file_path, file_type, delay, delay_message, context)
        except Exception as e:
            logger.error(f"Ошибка при отправке файла {file_path}: {e}")
            await context.bot.send_message(chat_id=user_id, text=f"Ошибка при отправке файла: {e}")



@handle_telegram_errors
async def process_lesson(user_id, lesson_number, active_course_id, context):
    """Обрабатывает текст урока и отправляет связанные файлы."""
    logger.info(f"800 process_lesson {user_id=} {lesson_number=}, {active_course_id=}, {context=}")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        # 1. Читаем текст урока
        lesson_data = get_lesson_text(lesson_number, active_course_id)
        if lesson_data:
            lesson_text, parse_mode = lesson_data
            try:
                await context.bot.send_message(chat_id=user_id, text=lesson_text, parse_mode=parse_mode)
            except Exception as e:
                logger.error(f"Ошибка при отправке текста урока: {e}")
                await context.bot.send_message(chat_id=user_id, text="Ошибка при отправке текста урока.")
        else:
            await context.bot.send_message(chat_id=user_id, text="Текст урока не найден.")

        # 2. Получаем файлы для урока
        lesson_files = await get_lesson_files(user_id, lesson_number, active_course_id)

        # 3. Отправляем файлы с задержкой и обрабатываем ошибки
        for file_info in lesson_files:
            file_path = file_info["path"]
            file_name = os.path.basename(file_path)
            file_type = file_info["type"]
            delay = file_info["delay"]

            try:
                # Если есть задержка, отправляем сообщение о задержке
                if delay > 0:
                    delay_message = random.choice(DELAY_MESSAGES)
                    logger.info(
                        f"Ожидание {delay} секунд перед отправкой файла {file_path}. Сообщение: {delay_message}")
                    await context.bot.send_message(chat_id=user_id, text=delay_message)
                    await asyncio.sleep(delay)

                # Отправляем файл, используя функцию send_file
                await send_file_with_file_id(context.bot, user_id, active_course_id, lesson_number, file_path,
                                             file_name, file_type)

            except FileNotFoundError:
                logger.error(f"Файл не найден: {file_path}")
                await context.bot.send_message(chat_id=user_id, text=f"Файл не найден: {file_path}")
            except Exception as e:
                logger.error(f"Ошибка при отправке файла {file_path}: {e}")
                await context.bot.send_message(chat_id=user_id, text=f"Ошибка при отправке файла: {e}")

    except Exception as e:
        logger.error(f"Ошибка при обработке урока: {e}")
        await context.bot.send_message(chat_id=user_id, text="Произошла ошибка при обработке урока.")


async def send_file_with_file_id(bot, chat_id: int, course_id: str, lesson_number: int, file_path: str,
                                 file_name: str, file_type: str):
    """
    Отправляет файл пользователю, используя file_id, если он есть, или загружая новый файл.

    Args:
        bot: Объект бота Telegram.
        chat_id: ID чата, куда нужно отправить файл.
        course_id: ID курса.
        lesson_number: Номер урока.
        file_path: Путь к файлу.
        file_name: Имя файла (для отправки как документа).
    """
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    logger.info(f"224 send_file Начинаем отправку файла: {file_name} ({file_path}) в чат {chat_id}")

    try:
        # 1. Проверяем, существует ли файл
        if not os.path.exists(file_path):
            logger.error(f"Файл не найден: {file_path}")
            await bot.send_message(chat_id=chat_id, text="Файл не найден. Пожалуйста, обратитесь в поддержку.")
            return  # Важно: выходим из функции, если файл не найден

        # 2. Получаем video_file_id из базы данных (если есть)
        cursor.execute(
            """
            SELECT video_file_id FROM lessons
            WHERE course_id = ? AND lesson = ?
            """,
            (course_id, lesson_number),
        )
        result = cursor.fetchone()
        file_id = result[0] if result else None

        if file_id:
            logger.info(f"Найден video_file_id {file_id} для {file_name} в базе данных.")
            try:
                # Попытка отправить файл с использованием video_file_id

                if file_type == 'photo':
                    await bot.send_photo(chat_id=chat_id, photo=file_id)
                elif file_type == 'video':
                    await bot.send_video(chat_id=chat_id, video=file_id)
                elif file_type == 'audio':
                    await bot.send_audio(chat_id=chat_id, audio=file_id)
                else:
                    await bot.send_document(chat_id=chat_id, document=file_id, filename=file_name)
                logger.info(f"Файл {file_name} успешно отправлен с использованием video_file_id.")
                return  # Выходим из функции, если отправка прошла успешно

            except TelegramError as e:
                logger.warning(f"Не удалось отправить файл с video_file_id: {e}. Попытка отправки как нового файла.")
                # Если не удалось отправить с video_file_id, отправляем как новый файл
                await send_as_new_file(bot, chat_id, course_id, lesson_number, file_path, file_name, file_type)
                return  # Выходим из функции

        else:
            # Если video_file_id не найден, отправляем как новый файл
            logger.info(f"video_file_id не найден, отправляем {file_name} как новый файл.")
            await send_as_new_file(bot, chat_id, course_id, lesson_number, file_path, file_name, file_type)
            return  # Выходим из функции

    except sqlite3.Error as e:
        logger.error(f"Ошибка базы данных при отправке файла {file_name}: {e}")
        await bot.send_message(
            chat_id=chat_id,
            text="Произошла ошибка базы данных при отправке файла. Пожалуйста, попробуйте позже."
        )
    except Exception as e:
        logger.exception(f"Ошибка при отправке файла {file_name}: {e}")
        await bot.send_message(
            chat_id=chat_id,
            text="Произошла ошибка при отправке файла. Пожалуйста, попробуйте позже."
        )


async def send_as_new_file(bot, chat_id: int, course_id: str, lesson_number: int, file_path: str, file_name: str,
                           file_type: str):
    """Отправляет файл как новый, получает его video_file_id и сохраняет в базе данных."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:

        # Открываем файл для чтения в бинарном режиме
        with open(file_path, "rb") as file:
            # Отправляем файл в зависимости от MIME-типа
            if file_type == 'photo':
                logger.info(f"Отправляем файл как изображение.")
                msg = await bot.send_photo(chat_id=chat_id, photo=file)
            elif file_type == 'video':
                logger.info(f"Отправляем файл как видео.")
                msg = await bot.send_video(chat_id=chat_id, video=file)
            elif file_type == 'audio':
                logger.info(f"Отправляем файл как аудио.")
                msg = await bot.send_audio(chat_id=chat_id, audio=file)
            else:
                logger.info(f"Отправляем файл как документ.")
                msg = await bot.send_document(chat_id=chat_id, document=file, filename=file_name)
        # Сохраняем file_id в базу данных
        file_id = msg.document.file_id if msg.document else msg.photo[
            -1].file_id if msg.photo else msg.video.file_id if msg.video else msg.audio.file_id if msg.audio else None  # Берем нужный file_id
        if file_id:
            logger.info(f"Получен file_id: {file_id}")
            cursor.execute(
                """
                UPDATE lessons
                SET video_file_id = ?
                WHERE course_id = ? AND lesson = ?
                """,
                (file_id, course_id, lesson_number),
            )
            conn.commit()
            logger.info(f"video_file_id {file_id} сохранен в базе данных для файла {file_name}.")
        else:
            logger.error(f"Не удалось получить file_id для {file_name}!")

    except Exception as e:
        # Обрабатываем любые исключения, которые могут возникнуть
        logger.exception(
            f"Ошибка при отправке файла {file_name} в чат {chat_id}: {e}")  # Используем logger.exception для трассировки стека
        await bot.send_message(
            chat_id=chat_id,
            text="Произошла ошибка при отправке файла. Пожалуйста, попробуйте позже или обратитесь в поддержку."
        )


def get_lesson_text(lesson_number, course_id):
    """Извлекает текст урока из файла и возвращает его вместе с режимом форматирования."""
    # Список возможных путей к файлам урока
    logger.info(f"855 get_lesson_textПолучаем текст урока {lesson_number} из {course_id}")
    lesson_paths = [
        f"courses/{course_id}/lesson{lesson_number}.md",
        f"courses/{course_id}/lesson{lesson_number}.html",
        f"courses/{course_id}/lesson{lesson_number}.txt",
    ]
    logger.info(f"Проверяемые пути для урока {lesson_number}: {lesson_paths}")

    # Перебираем пути и ищем существующий файл
    for path in lesson_paths:
        if os.path.exists(path):
            logger.info(f"Файл найден: {path}")
            try:
                with open(path, "r", encoding="utf-8") as file:
                    lesson_text = file.read()
                    logger.info(f"Файл {path} успешно открыт. lesson_text='{lesson_text[:35]}...'")

                    # Определяем режим форматирования в зависимости от расширения файла
                    if path.endswith(".html"):
                        parse_mode = ParseMode.HTML
                    elif path.endswith(".md"):
                        # parse_mode = ParseMode.MARKDOWN_V2 # Или ParseMode.MARKDOWN
                        parse_mode = ParseMode.MARKDOWN
                        # lesson_text = escape_markdown_v2(lesson_text)  # Экранирует специальные символы
                    else:
                        parse_mode = ParseMode.HTML  # По умолчанию для .txt

                    return lesson_text, parse_mode

            except Exception as e:
                logger.error(f"Ошибка при чтении файла {path}: {e}")
                return None, None

    # Если файл не найден
    logger.error(f"Файл с уроком не найден: {lesson_paths}")
    return None, None


async def get_next_bonus_info( user_id: int) -> dict:
    """Получает информацию о следующем и последнем начислении бонусов."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    bonuses_config = load_bonuses()
    today = date.today()

    # 1. Monthly bonus
    last_bonus_date = get_last_bonus_date(cursor, user_id)
    if not last_bonus_date or (
            last_bonus_date.year != today.year or last_bonus_date.month != today.month
    ):
        next_bonus = f"+{bonuses_config.get('monthly_bonus', 1)} (Ежемесячный бонус)"
    else:
        next_bonus = "Ежемесячный бонус уже начислен в этом месяце"

    # 2. Birthday bonus
    cursor.execute("SELECT birthday FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    birthday_str = user_data[0] if user_data else None
    if birthday_str:
        birthday = datetime.strptime(birthday_str, "%Y-%m-%d").date()
        if birthday.month == today.month and birthday.day == today.day:
            next_bonus += f"\n+{bonuses_config.get('birthday_bonus', 5)} (Бонус на день рождения)"
        else:
            next_bonus += f"\nБонус на день рождения будет начислен {birthday_str}"

    return {"last_bonus": "За регистрацию", "next_bonus": next_bonus}  # Пример


async def get_available_products( tokens: int) -> str:
    """Возвращает информацию о доступных продуктах в магазине."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    #  Здесь надо подгрузить товары из бд
    # 1. Make a database query
    cursor.execute("SELECT product_name, price FROM products")  # WHERE price <= ? ORDER BY price ASC
    logger.info(f"  get_available_products  Начало выполнения функции с tokens={tokens}")  # Добавлено логирование
    products = cursor.fetchall()
    if not products:
        return "\nВ магазине пока нет товаров."

    logger.info(f" get_available_products  Найдено {len(products)} товаров.")  # Добавлено логирование
    # 2. Find the cheapest product
    affordable_products = []
    unaffordable_products = []
    for product in products:
        if product[1] <= tokens:
            affordable_products.append(product)
        else:
            unaffordable_products.append(product)
    if not affordable_products:
        return "\nУ вас недостаточно средств для покупки каких-либо товаров."
    # 3. Suggest Products
    products_str = ""
    if affordable_products:
        products_str += f"\nВы можете купить:\n"
        for product in affordable_products:
            products_str += f"- {product[0]} (Цена: {product[1]})\n"
    products_str = products_str[:-1] if products_str else products_str
    if unaffordable_products:
        products_str += f"\nВам немного не хватает для:\n"
        for product in unaffordable_products:
            if product[1] - tokens <= 10:
                products_str += f"- {product[0]} (Цена: {product[1]})\n"
    products_str = products_str[:-1] if products_str else products_str
    return products_str



@handle_telegram_errors
async def show_main_menu( update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user = update.effective_user
    logger.info(f" show_main_menu       {update.effective_user} ---")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()


    # 1. Получаем количество токенов пользователя
    cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
    tokens_data = cursor.fetchone()
    tokens = tokens_data[0] if tokens_data else 0

    # 2. Получаем информацию о следующем бонусе
    next_bonus_info = await get_next_bonus_info(user_id)

    logger.info(f"432 из базы получили токены ")

    # 3. Формируем сообщение
    # Преобразуем токены в монеты
    bronze_coins = tokens % 10  # 1 BRONZE_COIN = 1 токен
    tokens //= 10  # остались десятки
    silver_coins = tokens % 10  # 1 SILVER_COIN = 10 токенов
    tokens //= 10  # остались сотки
    gold_coins = tokens % 10  # 1 GOLD_COIN = 100 токенов
    tokens //= 10  # остались тыщи
    platinum_coins = tokens  # 1 GEM_COIN = 1000 токенов

    # Формируем строку с монетами
    coins_display = (
        f"{PLATINUM_COIN}x{platinum_coins}"
        f"{GOLD_COIN}x{gold_coins}"
        f"{SILVER_COIN}x{silver_coins}"
        f"{BRONZE_COIN}x{bronze_coins}"
    )
    tokens = tokens_data[0] if tokens_data else 0  # просто считали заново
    logger.info(f"222  Ваши antCoins {coins_display} --- ")

    message = f" Ваши antCoins: {tokens}   {coins_display}\n"
    message += f"Последнее начисление: {next_bonus_info['last_bonus']}\n"
    message += f"Следующее начисление: {next_bonus_info['next_bonus']}\n"

    # 4. Получаем доступные товары для покупки
    products_message = await get_available_products(tokens)
    message += products_message
    try:
        # Get data of course
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user.id,))
        active_course_data = cursor.fetchone()
        logger.info(f"434 active_course_data= {active_course_data} на будущее {message=} ---- ")
        # TODO: продукты подсовывать доступные
        if not active_course_data or not active_course_data[0]:
            message_text = "Активируйте курс с помощью кодового слова."
            await safe_reply(update, context, message_text)
            logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
            return ConversationHandler.END

        active_course_id_full = active_course_data[0]
        # Short name
        active_course_id = active_course_id_full.split("_")[0]
        active_tariff = active_course_id_full.split("_")[1] if len(active_course_id_full.split("_")) > 1 else "default"

        # Получаем данные о типе курса и прогрессе
        cursor.execute(
            """
            SELECT course_type, progress
            FROM user_courses
            WHERE user_id = ? AND course_id = ?
        """,
            (user.id, active_course_id_full),
        )
        course_data = cursor.fetchone()
        logger.info(f"435 course_data= {course_data} ----- ")

        if not course_data:
            logger.warning(f"Не найден course_type для user_id={user.id} и course_id={active_course_id_full}")
            course_type, progress = "unknown", 0  # Установите значения по умолчанию
        else:
            course_type, progress = course_data

        logger.info(f"436 Тип курса: {course_type=} Прогресс: {progress=} ------ ")
        logger.info(f"437 {course_type=} {progress=} ------ ")

        # Notifications
        cursor.execute(
            "SELECT morning_notification, evening_notification FROM user_settings WHERE user_id = ?",
            (user.id,),
        )
        settings = cursor.fetchone()

        logger.info(f"438 Настройки уведомлений:  {settings=}  ------- ")
        morning_time = settings[0] if settings and len(settings) > 0 else "Not set"  # CHECK LENGHT
        evening_time = settings[1] if settings and len(settings) > 1 else "Not set"  # CHECK LENGHT

        # Получаем имя пользователя
        cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user.id,))
        name_data = cursor.fetchone()
        logger.info(f"439 Имя пользователя:  {name_data=}  -------- ")

        logger.info(f"440 {settings=}  ------- ")
        morning_time = settings[0] if settings and len(settings) > 0 else "Not set"  # CHECK LENGHT
        evening_time = settings[1] if settings and len(settings) > 1 else "Not set"  # CHECK LENGHT

        # Get username
        cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user.id,))
        name_data = cursor.fetchone()
        logger.info(f" 441 {name_data=}  -------- ")

        if name_data and len(name_data) > 0:
            full_name = name_data[0]
        else:
            full_name = "Пользователь"
            logger.warning(f"442 Не найдено имя пользователя {user.id} в базе данных")
        logger.info(f"443 {full_name=}  --------- ")

        # Получаем статус домашнего задания
        homework = await get_homework_status_text(user.id, active_course_id_full)

        logger.info(f"4424 --- {homework=}  --------- ")

        lesson_files = await get_lesson_files(user.id, progress, active_course_id)
        logger.info(f"445 lesson_files = {lesson_files[:3]}  -=- ")

        # Removing this as it should happen only on "lesson" button press
        # last_lesson = await check_last_lesson (update, context)
        # logger.info(f" {last_lesson=}  --------- ")

        # Debug state
        if context.user_data and context.user_data.get("waiting_for_code"):
            state_emoji = "🔑"  # Key emoji for 'waiting_for_code' state
        else:
            state_emoji = "✅"  # Checkmark for other states

        progress_text = f"Текущий урок: {progress}" if progress else "--"
        greeting = f"""Приветствую, {full_name.split()[0]}! {state_emoji}
        Курс: {active_course_id} ({course_type}) {active_tariff}
        Прогресс: {progress_text}
        Домашка: {homework}  """

        logger.info(f" show_main_menu {user} --- ")

        # 1. Получаем количество токенов пользователя
        cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
        tokens_data = cursor.fetchone()
        logger.info(f"Select tokens FROM user_tokens WHERE user_id = ? {tokens_data} для {user_id} ")
        tokens = tokens_data[0] if tokens_data else 0

        # 2. Получаем информацию о следующем бонусе
        next_bonus_info = await get_next_bonus_info(user_id)

        logger.info(f"14 получили токены и бонусы в меню {tokens}")

        # 3. Формируем сообщение
        # Преобразуем токены в монеты
        bronze_coins = tokens % 10  # 1 BRONZE_COIN = 1 токен
        tokens //= 10  # остались десятки
        silver_coins = tokens % 10  # 1 SILVER_COIN = 10 токенов
        tokens //= 10  # остались сотки
        gold_coins = tokens % 10  # 1 GOLD_COIN = 100 токенов
        tokens //= 10  # остались тыщи
        platinum_coins = tokens  # 1 GEM_COIN = 1000 токенов

        # Формируем строку с монетами
        coins_display = (
            f"{PLATINUM_COIN}x{platinum_coins}"
            f"{GOLD_COIN}x{gold_coins}"
            f"{SILVER_COIN}x{silver_coins}"
            f"{BRONZE_COIN}x{bronze_coins}"
        )
        tokens = tokens_data[0] if tokens_data else 0  # просто считали заново


        greeting2=  f" \n "
        # 3. Формируем сообщение
        # Преобразуем токены в монеты
        bronze_coins = tokens % 10  # 1 BRONZE_COIN = 1 токен
        tokens //= 10  # остались десятки
        silver_coins = tokens % 10  # 1 SILVER_COIN = 10 токенов
        tokens //= 10  # остались сотки
        gold_coins = tokens % 10  # 1 GOLD_COIN = 100 токенов
        tokens //= 10  # остались тыщи
        platinum_coins = tokens  # 1 GEM_COIN = 1000 токенов

        # Формируем строку с монетами
        gem = f"{PLATINUM_COIN}{platinum_coins}" if platinum_coins else ""
        gol = f"{GOLD_COIN}{gold_coins}" if gold_coins>0 else ""
        sil = f"{SILVER_COIN}{silver_coins}" if silver_coins>0 else ""
        bro = f"{BRONZE_COIN}{bronze_coins}" if bronze_coins>0 else ""

        coins_display = (
            f"{gem} "
            f"{gol} "
            f"{sil} "
            f"{bro}"
        )
        logger.info(f"14,5 считаем токены {coins_display=}")
        tokens = tokens_data[0] if tokens_data else 0  # просто считали заново

        greeting2 += f"💰AntCoins💰 {tokens}  =    {coins_display}  \n"

       # greeting2 += f"Последнее начисление: {next_bonus_info['last_bonus']}\n"   пока выключим, но TODO добавить замануху чтобы делали что то за очки
       # greeting2 += f"Следующее начисление: {next_bonus_info['next_bonus']}\n"

        # Make buttons
        keyboard = [
            [
                InlineKeyboardButton("📚 Текущий Урок - повтори всё", callback_data="get_current_lesson"),
                InlineKeyboardButton("🖼 Галерея ДЗ", callback_data="gallery"),
            ],
            [
                InlineKeyboardButton(
                    f"⚙ Настройка Курса ⏰({morning_time}, {evening_time})",
                    callback_data="course_settings",
                )
            ],
            [
                InlineKeyboardButton("💰 Тарифы и Бонусы <- тут много", callback_data="tariffs"),
            ],
            [InlineKeyboardButton("🙋 ПоДдержка", callback_data="support")],
        ]

        # ADD DYNAMIC BUTTON для предварительных материалов
        # Find lesson
        next_lesson = progress + 1

        # If lesson available add it
        lessons = get_preliminary_materials(active_course_id, next_lesson)
        if len(lessons) > 0 and not (homework.startswith("есть")):
            keyboard.insert(
                0,
                [
                    InlineKeyboardButton(
                        "🙇🏼Предварительные материалы к след. уроку",
                        callback_data="preliminary_tasks",
                    )
                ],
            )

        # Кнопка самоодобрения для тарифа self_check
        if active_tariff == "self_check":
            keyboard.insert(
                0,
                [
                    InlineKeyboardButton(
                        "✅ Самоодобрение ДЗ",
                        callback_data=f"self_approve_{progress}"
                    )
                ],
            )

        reply_markup = InlineKeyboardMarkup(keyboard)

        logger.info(f"888 pre #Send menu  ---------- ")
        # Send menu
        try:
            await safe_reply(update, context, greeting+greeting2, reply_markup=reply_markup)
            logger.info(f"889 норм всё - послали safe_reply")
        except TelegramError as e:
            logger.error(f"Telegram API error: {e}")
            await context.bot.send_message(user.id, "Произошла ошибка. Попробуйте позже.")

    except Exception as e:
        logger.error(f"time {time.strftime('%H:%M:%S')} Error in show_main_menu: {str(e)}")
        await safe_reply(update, context, "Error display menu. Try later.")
        logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
        return ConversationHandler.END


# формирование сообщения 17-03 вечер perplexity
async def old_get_main_menu_message( user: Update.effective_user) -> str:
    """Формирует текст сообщения для главного меню."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = user.id

    try:
        # 1. Get user's tokens
        cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
        tokens_data = cursor.fetchone()
        tokens = tokens_data[0] if tokens_data else 0

        # 2. Get next bonus information
        next_bonus_info = await get_next_bonus_info(user_id)

        # 3. Construct the message
        message = f"555 Ваши antCoins: {tokens}\n"
        message += f"Последнее начисление: {next_bonus_info['last_bonus']}\n"
        message += f"Следующее начисление: {next_bonus_info['next_bonus']}\n"

        # 4. Get available products for purchase
        products_message = await get_available_products(tokens)
        message += products_message

        # Get data of course
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user.id,))
        active_course_data = cursor.fetchone()
        logger.info(f" active_course_data= {active_course_data} ---- ")

        if not active_course_data or not active_course_data[0]:
            return "Активируйте курс с помощью кодового слова."

        active_course_id_full = active_course_data[0]
        # Short name
        active_course_id = active_course_id_full.split("_")[0]
        active_tariff = active_course_id_full.split("_")[1] if len(active_course_id_full.split("_")) > 1 else "default"

        # Data of course
        cursor.execute(
            """
            SELECT course_type, progress
            FROM user_courses
            WHERE user_id = ? AND course_id = ?
        """,
            (user.id, active_course_id_full),
        )
        course_data = cursor.fetchone()
        logger.info(f" course_data= {course_data} ----- ")

        if not course_data:
            logger.warning(f"Не найден course_type для user_id={user.id} и course_id={active_course_id_full}")
            course_type, progress = "unknown", 0  # Установите значения по умолчанию
        else:
            course_type, progress = course_data
        logger.info(f" 558 {course_type=} {progress=} ------ ")
        # Notifications
        cursor.execute(
            "SELECT morning_notification, evening_notification FROM user_settings WHERE user_id = ?",
            (user.id,),
        )
        settings = cursor.fetchone()
        logger.info(f"559 {settings=}  ------- ")
        morning_time = settings[0] if settings and len(settings) > 0 else "Not set"  # CHECK LENGHT
        evening_time = settings[1] if settings and len(settings) > 1 else "Not set"  # CHECK LENGHT

        # Get username
        cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user.id,))
        name_data = cursor.fetchone()
        logger.info(f"560{name_data=}  -------- ")

        if name_data and len(name_data) > 0:
            full_name = name_data[0]
        else:
            full_name = "Пользователь"
            logger.warning(f" 561 Не найдено имя пользователя {user.id} в базе данных")
        logger.info(f"562 {full_name=}  --------- ")

        homework = await get_homework_status_text(user.id, active_course_id_full)
        logger.info(f"563 {homework=}  --------- ")

        message = f"Приветствую, {full_name}! ✅\n"
        message += f"        Курс: {active_course_id} \n"  # TODO получить course_name из course_id
        message += homework

        return message

    except Exception as e:
        logger.error(f"564 Ошибка при формировании сообщения для главного меню: {e}")
        return "Произошла ошибка. Попробуйте позже."


@handle_telegram_errors
async def old_start(update: Update, context: CallbackContext) -> int:
    """Starts the conversation and asks the user for their name."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        logger.error("Could not get user ID - effective_user is None")
        logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
        return ConversationHandler.END

    logger.info(f"Начало разговора с пользователем {user_id} =================================================================")
    logger.info(f"Пользователь {user_id} запустил команду /start")

    # Fetch user info from the database
    cursor.execute("SELECT full_name, active_course_id FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()

    if user_data:
        full_name = user_data[0]
        active_course_id = user_data[1]

        if full_name:
            if active_course_id:
                logger.info(f"Пользователь {user_id} уже зарегистрирован и курс активирован.")
                await show_main_menu(update, context)  # Direct user to main menu
                logger.info(f"User {update.effective_user.id} transitioning to ACTIVE state")
                return ACTIVE  # User is fully set up
            else:
                logger.info(f"Пользователь {user_id} зарегистрирован, но курс не активирован.")
                await safe_reply(update, context, f"{full_name}, для активации курса, введите кодовое слово:")
                return WAIT_FOR_CODE  # Ask for the code word
        else:
            logger.info(f"Пользователь {user_id} зарегистрирован, но имя отсутствует.")
            await safe_reply(update, context, "Пожалуйста, введите ваше имя:")
            logger.info(f"User {update.effective_user.id} transitioning to WAIT_FOR_NAME state")
            return WAIT_FOR_NAME  # Ask for the name
    else:
        # TODO исправить ошибку username нету есть full_name
        # CREATE   TABLE  IF  NOT   EXISTS
        # users( user_id   INTEGER   PRIMARY        KEY,
        # full_name   TEXT        NOT   NULL    DEFAULT      'ЧЕБУРАШКА',
        cursor.execute("INSERT INTO users (user_id, username, reg_date) VALUES (?, ?, ?)",
                       (user_id, update.effective_user.username, datetime.now()))
        conn.commit()
        logger.info(f"Новый пользователь {user_id} - запрашиваем имя")
        await safe_reply(update, context, "Привет! Пожалуйста, введите ваше имя:")
        logger.info(f"User {update.effective_user.id} transitioning to WAIT_FOR_NAME state")
        return WAIT_FOR_NAME  # Ask for the name

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
                logger.info(f"User {update.effective_user.id} transitioning to WAIT_FOR_NAME state")
                return WAIT_FOR_CODE  # Ask for the code word
        else:
            logger.info(f"Пользователь {user_id} зарегистрирован, но имя отсутствует.")
            await safe_reply(update, context, "Пожалуйста, введите ваше имя:")
            logger.info(f"User {update.effective_user.id} transitioning to WAIT_FOR_NAME state")
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
        logger.info(f"User {update.effective_user.id} transitioning to WAIT_FOR_NAME state")
        return WAIT_FOR_NAME  # Ask for the name



# обработчик  всего неизвестного 17 03 ночь
async def unknown(update: Update, context: CallbackContext):
    """Handles unknown commands."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Я не понимаю эту команду. Пожалуйста, используйте /start для начала или /help для списка команд.",
    )
    logger.warning(f"Пользователь {update.effective_user.id} ввел неизвестную команду: {update.message.text}")

async def course_completion_actions( update: Update,  context: CallbackContext):
    """Actions to perform upon course completion."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f"course_completion_actions  {user_id} 44 ")
    # Get active_course_id from user
    cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
    active_course_data = cursor.fetchone()
    active_course_id_full = active_course_data[0]
    # Inform user
    await update.message.reply_text("Congratulations, you have finished the course")

    await show_statistics (update, context)

    # Update to aux
    cursor.execute(
        """
        UPDATE user_courses
        SET course_type = 'auxiliary'
        WHERE user_id = ? AND course_id = ?
    """,
        (user_id, active_course_id_full),
    )
    conn.commit()

    # End homeworks
    cursor.execute(
        """
        DELETE FROM homeworks
        WHERE user_id = ? AND course_id = ?
    """,
        (user_id, active_course_id_full),
    )
    conn.commit()

    # Generate button to watch every lesson
    available_lessons = get_available_lessons(active_course_id_full)
    keyboard = generate_lesson_keyboard(available_lessons)
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("All finished .", reply_markup=reply_markup)

def get_available_lessons( course_id):
    """Get all existing lessons by course."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    lesson_dir = f"courses/{course_id}/"
    lessons = [
        int(f.replace("lesson", "").replace(".txt", ""))
        for f in os.listdir(lesson_dir)
        if f.startswith("lesson") and f.endswith(".txt")
    ]
    lessons.sort()
    logger.info(f"get_available_lessons  {lessons} 333 ")
    return lessons

def generate_lesson_keyboard( lessons, items_per_page=10):
    """Generate buttons with page"""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    keyboard = []
    logger.info(f"generate_lesson_keyboard ")
    for lesson in lessons:
        keyboard.append([InlineKeyboardButton(f"Lesson {lesson}", callback_data=f"lesson_{lesson}")])  # type: ignore
    return keyboard

# домашка ???
async def get_homework_status_text( user_id, course_id):
    """Возвращает текст статуса проверки домашнего задания."""
    logger.info(f"223 get_homework_status_text  {user_id=}  ")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    # Проверяем статус домашнего задания
    cursor.execute(
        """
        SELECT hw_id, lesson, status
        FROM homeworks
        WHERE user_id = ? AND course_id = ?
        ORDER BY lesson DESC LIMIT 1
    """,
        (user_id, course_id),
    )
    homework_data = cursor.fetchone()

    if not homework_data:
        # Если домашки еще не отправлялись
        cursor.execute(
            """
            SELECT progress
            FROM user_courses
            WHERE user_id = ? AND course_id = ?
        """,
            (user_id, course_id),
        )
        progress_data = cursor.fetchone()
        if progress_data:
            lesson = progress_data[0]
            return f"Жду домашку к {lesson} уроку"
        else:
            return "Информация о прогрессе недоступна"

    hw_id, lesson, status = homework_data
    logger.info(f"224 внутри get_homework_status_text  {hw_id=}  {lesson=}  {status=} ")
    # Формируем текст в зависимости от статуса
    if status == "pending":
        logger.info(f"225 Домашка к {lesson} уроку на проверке у админов")
        return f"Домашка к {lesson} уроку на проверке у админов"
    elif status == "approved":
        logger.info(f"226 Домашка к {lesson} уроку принята")
        return f"Домашка к {lesson} уроку принята"
    else:
        logger.info(f"227 попали в 'else' Статус домашки неизвестен странен и загадочен")
        return "Статус домашки неизвестен странен и загадочен"


async def fetch_user_data(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id: int):
    """Fetches user data from the database."""
    try:
        # Get the user data from the database
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()
        return user_data
    except sqlite3.Error as e:
        logger.error(f"Database error fetching user data: {e}")
        return None


async def activate_course(update: Update, context: CallbackContext, user_id: int, user_code: str):
    """Активирует курс для пользователя."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        # Получаем данные о курсе из COURSE_DATA по кодовому слову
        course = COURSE_DATA[user_code]
        course_id_full = course.course_id  # Полное название курса (например, femininity_premium)
        course_id = course_id_full.split("_")[0]  # Базовое название курса (например, femininity)
        course_type = course.course_type  # 'main' или 'auxiliary'
        tariff = course_id_full.split("_")[1] if len(
            course_id_full.split("_")) > 1 else "default"  # Тариф (premium, self_check и т.д.)
        logger.info(f"544 activate_course {tariff} название курса из файла {course_id_full}")

        # Проверяем, есть ли уже какой-то курс с таким базовым названием у пользователя
        cursor.execute(
            """
            SELECT course_id, tariff FROM user_courses
            WHERE user_id = ? AND course_id LIKE ?
        """,
            (user_id, f"{course_id}%"),
        )
        existing_course = cursor.fetchone()


        # продолжается
        user_data = await fetch_user_data(conn, cursor, user_id)
        if user_data:
            diamond_coins = user_data[5]
            gold_coins = user_data[6]
            silver_coins = user_data[7]
            bronze_coins = user_data[8]
        else:
            diamond_coins = 0
            gold_coins = 0
            silver_coins = 0
            bronze_coins = 0

        logger.info(f"coins {bronze_coins=} {silver_coins=} {gold_coins=} {diamond_coins=}")

        # закончили

        # Handle course activation logic
        if existing_course:
            existing_course_id = existing_course[0]
            existing_tariff = existing_course[1]

            if existing_course_id == course_id_full:
                # Полное совпадение - курс уже активирован
                await safe_reply(update, context, "Этот курс уже активирован для вас. \n Your antCoins: 💎x{diamond_coins}🟡x{gold_coins}⚪️x{silver_coins}🟤x{bronze_coins}")
                return

            else:
                # Обновляем тариф существующего курса
                cursor.execute(
                    """
                    UPDATE user_courses
                    SET course_id = ?, tariff = ?
                    WHERE user_id = ? AND course_id = ?
                """,
                    (course_id_full, tariff, user_id, existing_course_id),
                )
                conn.commit()
                await safe_reply(update, context, f"Вы перешли с тарифа {existing_tariff} на тариф {tariff}.")

                # Обновляем active_course_id в users
                cursor.execute(
                    """
                    UPDATE users
                    SET active_course_id = ?
                    WHERE user_id = ?
                """,
                    (course_id_full, user_id),
                )
                conn.commit()
                logger.info(
                    f"Обновлен тариф пользователя {user_id} с {existing_tariff} на {tariff} для курса {course_id}")

                return  # Важно: завершаем функцию после обновления
        else:
            # Курса с таким базовым названием еще нет - создаем новый
            cursor.execute(
                """
                INSERT INTO user_courses (user_id, course_id, course_type, progress, tariff)
                VALUES (?, ?, ?, ?, ?)
            """,
                (user_id, course_id_full, course_type, 1, tariff),
            )
            conn.commit()

            await safe_reply(update, context, f"Курс {course_id} ({tariff}) активирован!")

            # Обновляем active_course_id в users
            cursor.execute(
                """
                UPDATE users
                SET active_course_id = ?
                WHERE user_id = ?
            """,
                (course_id_full, user_id),
            )
            conn.commit()
            logger.info(
                f"Курс {course_id} типа {course_type} активирован для пользователя {user_id} с тарифом {tariff}")

    except Exception as e:
        logger.error(f"Ошибка при активации или обновлении курса для пользователя {user_id}: {e}")
        await safe_reply(update, context, "Произошла ошибка при активации курса. Попробуйте позже.")


# вычисляем время следующего урока *
async def update_next_lesson_time( user_id, course_id):
    """Обновляет время следующего урока для пользователя."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        # Получаем текущее время
        now = datetime.now()

        # Вычисляем время следующего урока
        next_lesson_time = now + timedelta(hours=DEFAULT_LESSON_DELAY_HOURS)
        next_lesson_time_str = next_lesson_time.strftime("%Y-%m-%d %H:%M:%S")

        # Обновляем время в базе данных
        cursor.execute(
            """
            UPDATE users 
            SET next_lesson_time = ? 
            WHERE user_id = ?
        """,
            (next_lesson_time_str, user_id),
        )
        conn.commit()

        logger.info(f"Для пользователя {user_id} установлено время следующего урока: {next_lesson_time_str}")

    except Exception as e:
        logger.error(f"Ошибка при обновлении времени следующего урока: {e}")


# управление курсом и КНОПОЧКИ СВОИ *
async def course_management( update: Update, context: CallbackContext):
    """Управление курсом."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f" 445566 course_management {user_id}")

    # Получаем active_course_id из базы данных
    cursor.execute(
        """
        SELECT active_course_id
        FROM users
        WHERE user_id = ?
    """,
        (user_id,),
    )
    active_course_data = cursor.fetchone()

    if not active_course_data or not active_course_data[0]:
        await update.message.reply_text("У вас не активирован ни один курс.")
        return

    active_course_id = active_course_data[0]

    # Формируем кнопки
    keyboard = [
        [InlineKeyboardButton("Сменить $$$ тариф", callback_data="change_tariff")],
        [InlineKeyboardButton("Мои курсы", callback_data="my_courses")],
        [InlineKeyboardButton("История ДЗ", callback_data="hw_history")],
    ]
    await update.message.reply_text("Управление курсом:", reply_markup=InlineKeyboardMarkup(keyboard))

def create_admin_keyboard(user_id: int, course_id: str, lesson: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру для админа с кнопками: - Принять - Отклонить - История отказов"""
    # Формируем callback_data для каждой кнопки
    callback_data_accept = f"approve_admin_check|{user_id}|{course_id}|{lesson}"
    logger.info(f"{callback_data_accept=}")
    callback_data_decline = f"decline_homework|{user_id}|{course_id}|{lesson}"
    logger.info(f"{callback_data_decline=}")
    callback_data_history = f"history_callback|{user_id}|{course_id}|{lesson}"
    logger.info(f"{callback_data_history=}")

    # Создаем клавиатуру
    keyboard = [
        [InlineKeyboardButton("✅ Принять", callback_data=callback_data_accept),
         InlineKeyboardButton("❌ Отклонить", callback_data=callback_data_decline)],
        [InlineKeyboardButton("📜 История отказов", callback_data=callback_data_history)]
    ]
    return InlineKeyboardMarkup(keyboard)





async def handle_homework_submission(update: Update, context: CallbackContext):
    """Обрабатывает отправку домашнего задания."""
    user_id = update.effective_user.id
    course_id = context.user_data.get("current_course_id")
    lesson = context.user_data.get("current_lesson")

    logger.info(f"1599 ==== handle_homework_submission ========================= {user_id=}")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        # 1. Получаем текущий курс пользователя
        cursor.execute(
            """
            SELECT active_course_id, tariff
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        )
        user_data = cursor.fetchone()

        if not user_data:
            logger.warning(f"  user_data not user_data {user_id=}")
            await safe_reply(update, context, "Вы не записаны ни на один курс.")
            return

        active_course_id, tariff = user_data
        logger.info(f"1600 active_course_id {active_course_id=}  tariff {tariff=}")
        if not active_course_id:
            logger.warning(f"  active_course_id not active_course_id {user_id=}")
            await safe_reply(update, context, "У вас не выбран курс.")
            return

        # 2. Получаем текущий урок пользователя для данного курса
        cursor.execute(
            """
            SELECT progress
            FROM user_courses
            WHERE user_id = ? AND course_id = ?
            """,
            (user_id, active_course_id),
        )
        progress_data = cursor.fetchone()

        if not progress_data:
            logger.warning(f" progress_data not progress_data {user_id=}")
            await safe_reply(update, context, "У вас нет активного прогресса по курсу.")
            return

        lesson = progress_data[0]
        logger.info(f"1601 user_id {user_id=}  progress_data {progress_data=}  lesson {lesson=}")
        # 3. Получаем информацию о загруженном файле
        message = update.message or update.callback_query.message
        if message and message.photo:
            file_id = message.photo[-1].file_id
            file_type = "photo"
        elif message and message.video:
            file_id = message.video.file_id
            file_type = "video"
        elif message and message.document:
            file_id = message.document.file_id
            file_type = "document"
        else:
            logger.warning(f" Ни одного файла file_id not file_id {user_id=}")
            await safe_reply(update, context, "Пожалуйста, отправьте фото, видео или документ.")
            return

        try:
            file_info = await context.bot.get_file(file_id)
            logger.info(f"1602 file_info {file_info=}")
        except Exception as e:
            logger.error(f"Ошибка при получении информации о файле: {e}")
            await safe_reply(update, context, "Ошибка при получении информации о файле.")
            return

        # 4. Сохраняем информацию о домашнем задании в базе данных
        cursor.execute(
            """
            INSERT INTO homeworks (user_id, course_id, lesson, file_id, file_type, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, active_course_id, lesson, file_id, file_type, "pending"),
        )
        conn.commit()
        logger.info(f"1603  Домашка user_id {user_id=} сохранена в базе данных")

        # 5. Формируем ответ в зависимости от тарифа
        if tariff == "self_check":
            logger.info(f"  Тариф самостоятельный self_check {tariff=}")
            callback_data = f"approve_self_check|{user_id}|{active_course_id.replace('_', '|')}|{lesson}"  # вот тут
            keyboard = [[InlineKeyboardButton("✅ СамоПринять домашнее задание", callback_data=callback_data)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"Домашнее задание по уроку {lesson} отправлено. Вы самостоятельно подтверждаете выполнение.",
                reply_markup=reply_markup)
        else:
            # 5. Отправляем домашнее задание админу

            # 5. Отправляем домашнее задание админу
            # Создаем клавиатуру для админа
            if active_course_id:  # Проверяем, что active_course_id не None
                logger.info(f"5554  есть курс {active_course_id=}")
                reply_markup = create_admin_keyboard(user_id, active_course_id, lesson)  # Исправлено: используем active_course_id
            else:
                logger.error("555 :-( active_course_id is None, cannot create admin keyboard.")
                await safe_reply(update, context, "Произошла ошибка при обработке домашнего задания.")
                return



            # Получаем историю отказов для текущего урока
            logger.info(f"1604  Получаем историю отказов для текущего урока")
            cursor.execute(
                """
                SELECT reason, rejected_at
                FROM homework_rejections
                WHERE user_id = ? AND course_id = ? AND lesson = ?
                ORDER BY rejected_at DESC
                """,
                (user_id, active_course_id, lesson),
            )
            rejections = cursor.fetchall()
            logger.info(f"1605  Получили {rejections=}")

            # Формируем текст истории
            if rejections:
                history_text = "История отказов по этому уроку:\n\n"
                for reason, rejected_at in rejections:
                    history_text += f"Причина: {reason}\nДата: {rejected_at}\n\n"
            else:
                history_text = " отказов небыло"
                logger.info(f"1606  нет отказов то")

            logger.info(f"160666  {ADMIN_GROUP_ID=} Пользователь {user_id=} отправил домашнее задание по курсу {active_course_id=}, урок {lesson=}. {history_text=}  {reply_markup=}")
            if active_course_id:
                await context.bot.send_message(
                    ADMIN_GROUP_ID,
                    f"Пользователь {user_id} отправил домашнее задание по курсу {active_course_id}, урок {lesson}.\n\n{history_text}",
                    reply_markup=reply_markup,
                )
            else:
                logger.error("active_course_id is None, cannot send homework to admin.")
                await safe_reply(update, context, "Произошла ошибка при обработке домашнего задания.")
                return
            logger.info(f"1607  Отправили админу {ADMIN_GROUP_ID=}")
            await safe_reply(update, context, f"ДЗ {lesson} отправлено админам.")
            logger.info(f"1608  после safe_reply")
        # 6. Перерисовываем меню для пользователя
        await show_main_menu(update, context)

    except sqlite3.Error as e:
        logger.error(f"1610 Ошибка БД при сохранении ДЗ: {e}")
        await safe_reply(update, context, "Ошибка базы данных. Попробуйте позже.")
    except Exception as e:
        logger.error(f"1609 Непредвиденная ошибка при отправке ДЗ: {e}")
        await safe_reply(update, context, "Произошла ошибка при обработке домашнего задания. Попробуйте позже.")

async def callback_data_history(update: Update, context: CallbackContext):
    """  Обработчик для кнопки "Посмотреть историю всех непринятых домашек этого курса".
    Показывает историю всех домашних заданий пользователя по конкретному курсу.    """
    logger.info(f"1618 callback_data_history")
    query = update.callback_query
    await query.answer()  # Подтверждаем получение callback_query

    # Разбираем callback_data
    data = query.data.split('_')  # Формат: "history_{user_id}_{course_id}"
    action = data[0]  # "history"
    user_id = int(data[1])
    course_id = data[2]

    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        # Получаем историю домашних заданий по курсу
        cursor.execute(
            """
            SELECT lesson, status, rejection_reason, submission_time
            FROM homeworks
            WHERE user_id = ? AND course_id = ?
            ORDER BY lesson ASC, submission_time ASC
            """,
            (user_id, course_id),
        )
        homeworks = cursor.fetchall()

        if not homeworks:
            await query.edit_message_text(text="История домашних заданий пуста для этого курса.")
            return

        # Формируем сообщение с историей
        message = f"📜 *История домашних заданий по курсу {course_id}:*\n\n"
        for lesson, status, rejection_reason, submission_time in homeworks:
            message += f"📚 Урок: {lesson}\n"
            message += f"📝 Статус: {status.capitalize()}\n"
            if status == 'rejected' and rejection_reason:
                message += f"❌ Причина отказа: {rejection_reason}\n"
            message += f"⏰ Дата сдачи: {submission_time}\n\n"

        # Отправляем сообщение с историей
        await query.edit_message_text(
            text=message,
            parse_mode="Markdown",  # Для форматирования текста
        )
    except sqlite3.Error as e:
        logger.error(f"Ошибка при получении истории домашних заданий: {e}")
        await query.edit_message_text(text="Произошла ошибка при получении истории домашних заданий.")



def get_user_rejection_history(user_id: int):
    """    Retrieves the rejection history for a given user from the database.
    Args:        user_id (int): The ID of the user whose rejection history is to be retrieved.
    Returns:
        list: A list of tuples, where each tuple represents a rejection record
              (date, reason). Returns an empty list if no history is found or an error occurs.
    """
    logger.info(f"  get_user_rejection_history {user_id=}")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        cursor.execute(
            "SELECT rejection_date, reason FROM rejection_history WHERE user_id = ? ORDER BY rejection_date DESC",
            (user_id,),
        )
        history = cursor.fetchall()
        return history
    except sqlite3.Error as e:
        logger.error(f"Database error while fetching rejection history for user {user_id}: {e}")
        return []

async def handle_history_callback(update: Update, context: CallbackContext):
    """
    Универсальная функция для обработки всех запросов на историю:
    - История отказов.
    - История всех домашних заданий по курсу.
    """
    query = update.callback_query
    await query.answer()  # Подтверждаем получение callback_query

    # Разбираем callback_data
    data = query.data.split('|')  # Формат: "history_callback|{user_id}|{course_id}|{lesson}"
    action = data[0]  # "history_callback"
    user_id = int(data[1])
    course_id = data[2].replace('|', '_')  # Восстанавливаем исходный формат course_id
    lesson = int(data[3]) if len(data) > 3 else None  # Урок может отсутствовать

    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        if action == "history_callback":
            # Получаем историю отказов для текущего урока
            cursor.execute(
                """
                SELECT rejected_at, reason
                FROM homework_rejections
                WHERE user_id = ? AND course_id = ? AND lesson = ?
                ORDER BY rejected_at DESC
                """,
                (user_id, course_id, lesson),
            )
            rejections = cursor.fetchall()

            if rejections:
                message = "📜 *История Отказов:*\n\n"
                for date, reason in rejections:
                    message += f"🗓️ Дата: {date}\n📝 Причина: {reason}\n\n"
            else:
                message = "📜 У вас пока нет истории отказов."

        else:
            # Получаем историю всех домашних заданий по курсу
            cursor.execute(
                """
                SELECT lesson, status, rejection_reason, submission_time
                FROM homeworks
                WHERE user_id = ? AND course_id = ?
                ORDER BY lesson ASC, submission_time ASC
                """,
                (user_id, course_id),
            )
            homeworks = cursor.fetchall()

            if not homeworks:
                await query.edit_message_text(text="История домашних заданий пуста для этого курса.")
                return

            message = f"📜 *История домашних заданий по курсу {course_id}:*\n\n"
            for lesson, status, rejection_reason, submission_time in homeworks:
                message += f"📚 Урок: {lesson}\n"
                message += f"📝 Статус: {status.capitalize()}\n"
                if status == 'rejected' and rejection_reason:
                    message += f"❌ Причина отказа: {rejection_reason}\n"
                message += f"⏰ Дата сдачи: {submission_time}\n\n"

        # Отправляем сообщение с историей
        await query.edit_message_text(
            text=message,
            parse_mode="Markdown",  # Для форматирования текста
        )

    except sqlite3.Error as e:
        logger.error(f"Ошибка при получении истории: {e}")
        await query.edit_message_text(text="Произошла ошибка при получении истории.")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка: {e}")
        await query.edit_message_text(text="Произошла непредвиденная ошибка.")


async def check_if_homework_has_rejections(user_id: int, course_id: str, lesson: int, homework_id: int) -> bool:
    """Проверяет, есть ли отказы для конкретного домашнего задания."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM homeworks
            WHERE user_id = ? AND course_id = ? AND lesson = ? AND id = ? AND status = 'rejected'
            """,
            (user_id, course_id, lesson, homework_id),
        )
        count = cursor.fetchone()[0]
        return count > 0
    except sqlite3.Error as e:
        logger.error(f"Database error while checking rejections for homework {homework_id}: {e}")
        return False


async def send_homework_to_admin(update: Update, context: CallbackContext, user_id: int, course_id: str, lesson: int, homework_id: int):
    """Отправляет ДЗ админу с клавиатурой."""
    # Получаем file_id из базы данных
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        cursor.execute(
            """
            SELECT file_id
            FROM homeworks
            WHERE user_id = ? AND course_id = ? AND lesson = ? AND id = ?
            """,
            (user_id, course_id, lesson, homework_id),
        )
        file_id = cursor.fetchone()[0]

        # Создаем клавиатуру с кнопками "Одобрить" и "Отклонить"
        has_rejections = await check_if_homework_has_rejections(user_id, course_id, lesson, homework_id)
        keyboard = build_homework_review_keyboard(user_id, course_id, lesson, has_rejections, homework_id)

        # Отправляем фото админу с клавиатурой
        if file_id: # Если есть file_id
            if file_id.startswith('Ag'):  # Проверяем, является ли file_id идентификатором фотографии
                await context.bot.send_photo(chat_id=ADMIN_GROUP_ID, photo=file_id, reply_markup=keyboard)
            else: # Если нет, считаем, что это file_id документа
                await context.bot.send_document(chat_id=ADMIN_GROUP_ID, document=file_id, reply_markup=keyboard) # Используем send_document для документов

        else:
            await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text="Нет файла ДЗ.", reply_markup=keyboard)

    except sqlite3.Error as e:
        logger.error(f"Database error while sending homework: {e}")
        await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text="Ошибка при получении ДЗ.")



async def send_homework_history_to_admin(update: Update, context: CallbackContext, user_id: int, course_id: str, lesson: int, homework_id: int):
    """Отправляет админу историю сдачи одного ДЗ."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        # Получаем все попытки сдачи этого ДЗ
        cursor.execute(
            """
            SELECT file_id, rejection_reason
            FROM homeworks
            WHERE user_id = ? AND course_id = ? AND lesson = ? AND id = ?
            ORDER BY submission_time ASC
            """,
            (user_id, course_id, lesson, homework_id),
        )
        attempts = cursor.fetchall()

        media = []
        for file_id, rejection_reason in attempts:
            if file_id: # Если есть file_id
                if file_id.startswith('Ag'):  # Проверяем, является ли file_id идентификатором фотографии
                    media.append(InputMediaPhoto(media=file_id, caption=rejection_reason or "Прислано"))
                else: # Если нет, считаем, что это file_id документа
                    media.append(InputMediaDocument(media=file_id, caption=rejection_reason or "Прислано")) # Используем InputMediaDocument для документов

        # Отправляем историю админу
        if media:
            await context.bot.send_media_group(chat_id=ADMIN_GROUP_ID, media=media)

            # Создаем клавиатуру с кнопками "Одобрить" и "Отклонить"
            has_rejections = True  # История уже есть, поэтому has_rejections = True
            keyboard = build_homework_review_keyboard(user_id, course_id, lesson, has_rejections, homework_id)
            await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text="Оцените работу", reply_markup=keyboard)
        else:
            await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text="Нет истории сдачи этого ДЗ.")

    except sqlite3.Error as e:
        logger.error(f"Database error while sending homework history: {e}")
        await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text="Ошибка при получении истории ДЗ.")


# клавиатурка админская TODO скрестить её со старой клавой с + к коинам
def build_homework_review_keyboard(user_id: int, course_id: str, lesson: int, has_rejections: bool, homework_id: int = None):
    """Создает клавиатуру для одобрения или отклонения домашнего задания."""
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Одобрить",
                callback_data=f"approve_{user_id}_{course_id}_{lesson}_{homework_id if homework_id else 'all'}"
            ),
            InlineKeyboardButton(
                "❌ Отклонить",
                callback_data=f"reject_{user_id}_{course_id}_{lesson}_{homework_id if homework_id else 'all'}"
            ),
        ]
    ]

    if has_rejections:
        keyboard.append([
            InlineKeyboardButton(
                "📜 История отказов",
                callback_data=f"history_{user_id}_{course_id}_{lesson}"
            )
        ])

    return InlineKeyboardMarkup(keyboard)


async def show_homework_details(update: Update, context: CallbackContext, user_id: int, course_id: str, lesson: int):
    """Отображает детали домашнего задания и историю отказов."""
    logger.info(f"444  show_homework_details {user_id=}  {course_id=}  {lesson=}")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    # Получаем историю отказов для текущего урока
    cursor.execute(
        """
        SELECT reason, rejected_at
        FROM homework_rejections
        WHERE user_id = ? AND course_id = ? AND lesson = ?
        ORDER BY rejected_at DESC
        """,
        (user_id, course_id, lesson),
    )
    rejections = cursor.fetchall()

    # Формируем текст истории
    if rejections:
        history_text = "7776 История отказов по этому уроку:\n\n"
        for reason, rejected_at in rejections:
            history_text += f"Причина: {reason}\nДата: {rejected_at}\n\n"
    else:
        history_text = "777 История отказов по этому уроку отсутствует."

    # Создаем клавиатуру для админа
    reply_markup = create_admin_keyboard(user_id, course_id, lesson)

    # Отправляем сообщение админу
    await safe_reply(update=Update.de_json({"message": {"chat": {"id": ADMIN_GROUP_ID}}}, context.bot),
                     context=context,
                     text=f"Пользователь {user_id} отправил домашнее задание по курсу {course_id}, урок {lesson}.\n\n{history_text}",
                     reply_markup=reply_markup)





# Получение следующего времени урока
async def calculate_time_to_next_lesson( user_id, active_course_id_full):
    """Вычисляет, сколько времени осталось до следующего урока."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    logger.info(f"calculate_time_to_next_lesson")
    # Получаем время последнего урока
    cursor.execute(
        """
        SELECT submission_time FROM homeworks
        WHERE user_id = ? AND course_id = ?
        ORDER BY submission_time DESC
        LIMIT 1
    """,
        (user_id, active_course_id_full),
    )
    last_submission_data = cursor.fetchone()

    if last_submission_data:
        last_submission_time = datetime.strptime(last_submission_data[0], "%Y-%m-%d %H:%M:%S")
        next_lesson_time = last_submission_time + timedelta(hours=DEFAULT_LESSON_INTERVAL)
    else:
        next_lesson_time = datetime.now() + timedelta(hours=DEFAULT_LESSON_INTERVAL)

    time_left = next_lesson_time - datetime.now()
    return time_left if time_left.total_seconds() > 0 else timedelta(seconds=0)


async def save_admin_comment( update: Update, context: CallbackContext):
    """  Сохраняет комментарий админа и обновляет статус ДЗ.  """
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f" save_admin_comment {user_id} ")
    cursor.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (user_id,))
    if not cursor.fetchone():
        logger.info(f" this admin? NO! {cursor.fetchone()} ")
        await update.message.reply_text("⛔ Команда только для админов")
        return  # Прекращаем выполнение функции для не-админов
    hw_id = context.user_data.get("awaiting_comment")
    approval_status = context.user_data.pop("approval_status", None)

    logger.info(f" this admin? yep {cursor.fetchone()}  {hw_id} {approval_status=}")

    if not hw_id or not approval_status:
        # Убираем reply_text для обычных пользователей
        if update.message.chat.type != "private":
            await update.message.reply_text("Команда доступна только админам")
        return

    if hw_id and approval_status:
        comment = update.message.text
        try:
            cursor.execute(
                """
                UPDATE homeworks 
                SET status = ?, feedback = ?, approval_time = DATETIME('now'), admin_comment = ?
                WHERE hw_id = ?
            """,
                (approval_status, comment, comment, hw_id),
            )  # Сохраняем комментарий
            conn.commit()
            await update.message.reply_text(f"Комментарий сохранен. Статус ДЗ обновлен: {approval_status}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении комментария и статуса ДЗ: {e}")
            await update.message.reply_text("Произошла ошибка при сохранении комментария.")
    else:
        await update.message.reply_text("Не найден hw_id или статус. Повторите действие.")


# отказ * всё хуйня - переделывай
async def handle_admin_rejection( update: Update, context: CallbackContext):
    """Обрабатывает отклонение ДЗ администратором."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    await safe_reply(update, context, "ДЗ отклонено администратором.")

    try:
        # Получаем hw_id из callback_data
        hw_id = update.callback_query.data.split("_")[2]  # was '|' and [1]

        # Обновляем статус ДЗ в базе данных
        cursor.execute(
            """
            UPDATE homeworks
            SET status = 'rejected'
            WHERE hw_id = ?
        """,
            (hw_id,),
        )
        conn.commit()

        # Получаем user_id и lesson из homeworks
        cursor.execute(
            """
            SELECT user_id, course_id, lesson
            FROM homeworks
            WHERE hw_id = ?
        """,
            (hw_id,),
        )
        homework_data = cursor.fetchone()

        if not homework_data:
            await safe_reply(update, context, "Ошибка: ДЗ не найдено.")
            return

        user_id, course_id, lesson = homework_data

        # Отправляем уведомление пользователю
        await context.bot.send_message(
            chat_id=user_id,
            text=f"К сожалению, Ваше домашнее задание по уроку {lesson} курса {course_id} отклонено администратором. Попробуйте еще раз.",
        )

        # Редактируем сообщение в админ-группе
        await context.bot.edit_message_reply_markup(
            chat_id=update.callback_query.message.chat_id,
            message_id=update.callback_query.message.message_id,
            reply_markup=None,  # Убираем кнопки
        )
        await context.bot.edit_message_caption(
            chat_id=update.callback_query.message.chat_id,
            message_id=update.callback_query.message.message_id,
            caption=update.callback_query.message.caption + "\n\n❌ Отклонено!",
        )

        logger.info(f"ДЗ {hw_id} отклонено администратором")

    except Exception as e:
        logger.error(f"Ошибка при отклонении ДЗ: {e}")
        await safe_reply(update, context, "Произошла ошибка при отклонении ДЗ. Попробуйте позже.")


# Обрабатывает выбор тарифа
async def change_tariff( update: Update, context: CallbackContext):
    """Обрабатывает выбор тарифа."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f"change_tariff  {user_id} 777 555")
    try:
        # Получаем active_course_id из базы данных
        cursor.execute(
            """
            SELECT active_course_id
            FROM users
            WHERE user_id = ?
        """,
            (user_id,),
        )
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await safe_reply(update, context, "У вас не активирован ни один курс.")
            return

        active_course_id = active_course_data[0]

        # Создаем кнопки с вариантами тарифов
        keyboard = [
            [
                InlineKeyboardButton(
                    "Self-Check",
                    callback_data=f"set_tariff|{active_course_id}|self_check",
                )
            ],
            [
                InlineKeyboardButton(
                    "Admin-Check",
                    callback_data=f"set_tariff|{active_course_id}|admin_check",
                )
            ],
            [InlineKeyboardButton("Premium", callback_data=f"set_tariff|{active_course_id}|premium")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_reply(update, context, "Выберите новый тариф:", reply_markup=reply_markup)


    except Exception as e:
        logger.error(f"Ошибка при отображении вариантов тарифов: {e}")
        await safe_reply(update, context, "Произошла ошибка при отображении вариантов тарифов. Попробуйте позже.")


# Отображает список курсов пользователя
async def my_courses( update: Update, context: CallbackContext):
    """Отображает список курсов пользователя."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f"my_courses  {user_id}")
    try:
        # Получаем список курсов пользователя из базы данных
        cursor.execute(
            """
            SELECT course_id, course_type
            FROM user_courses
            WHERE user_id = ?
        """,
            (user_id,),
        )
        courses_data = cursor.fetchall()

        if not courses_data:
            await safe_reply(update, context, "У вас нет активных курсов.")
            return

        # Формируем текстовое сообщение со списком курсов
        message_text = "Ваши курсы:\n"
        for course_id, course_type in courses_data:
            message_text += f"- {course_id} ({course_type})\n"

        await safe_reply(update, context, message_text)
        return



    except Exception as e:
        logger.error(f"Ошибка при отображении списка курсов: {e}")
        await safe_reply(update, context, "Произошла ошибка при отображении списка курсов. Попробуйте позже.")
        return


# статистика домашек *
async def show_statistics( update: Update, context: CallbackContext):
    """Shows statistics for lessons and homework, considering all users, deviations, and course completion."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f" Show stat: {user_id=}")

    try:
        # Get active_course_id from user
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await update.message.reply_text("Activate course first .")
            return

        active_course_id_full = active_course_data[0]
        active_course_id = active_course_id_full.split("_")[0]

        # Get all users who have completed homework for this course
        cursor.execute(
            """
            SELECT user_id, AVG((JULIANDAY(final_approval_time) - JULIANDAY(lesson_sent_time)) * 24 * 60 * 60)
            FROM homeworks
            WHERE course_id = ? AND final_approval_time IS NOT NULL
            GROUP BY user_id
        """,
            (active_course_id_full,),
        )
        all_user_stats = cursor.fetchall()

        if not all_user_stats:
            await update.message.reply_text("No available  data.")
            return

        # Calculate average completion time across all users
        total_times = [time for user, time in all_user_stats if time is not None]
        average_time_all = sum(total_times) / len(total_times) if total_times else 0

        # Get user's average completion time
        cursor.execute(
            """
            SELECT AVG((JULIANDAY(final_approval_time) - JULIANDAY(lesson_sent_time)) * 24 * 60 * 60)
            FROM homeworks
            WHERE course_id = ? AND user_id = ? AND final_approval_time IS NOT NULL
        """,
            (active_course_id_full, user_id),
        )
        user_average_time = cursor.fetchone()[0] or 0

        # Calculate deviation from the average
        diff_percentage = ((user_average_time - average_time_all) / average_time_all) * 100 if average_time_all else 0
        deviation_text = f"{diff_percentage:.2f}%"
        logger.info(f"Checking {user_id=} {average_time_all=} {user_average_time=} {diff_percentage=}")

        if diff_percentage < 0:
            deviation_text = f"Faster {abs(diff_percentage):.2f}%."
        else:
            deviation_text = f"Slower {abs(diff_percentage):.2f}%."

        # Get average homework completion time
        average_homework_time = get_average_homework_time(user_id)

        # Build statistics message
        stats_message = f"Statistics for {active_course_id_full}:\n"
        stats_message += f"Average time all users : {timedelta(seconds=average_time_all) if average_time_all else 'No data'}\n"
        stats_message += f"Time: {timedelta(seconds=user_average_time) if user_average_time else 'No data'} ({deviation_text})\n"
        stats_message += f"Average homework completion: {average_homework_time}\n"

        await update.message.reply_text(stats_message)

    except Exception as e:
        logger.error(f"Cannot display stats: {e}")
        await update.message.reply_text("Error - unable to display stats try later")


# Getting info about lesson.*
async def format_progress( user_id, course_id):
    """Getting info about lesson."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    # Get progress of course
    cursor.execute(
        """
        SELECT progress
        FROM user_courses
        WHERE user_id = ? AND course_id = ?
    """,
        (user_id, course_id),
    )
    progress_data = cursor.fetchone()
    logger.info(f"format_progress  {progress_data}")
    # Check value
    if not progress_data:
        return "No Progress"

    progress = progress_data[0] if progress_data else 0


    # Get total amount
    cursor.execute(
        """
        SELECT DISTINCT lesson FROM homeworks
        WHERE course_id = ?
        ORDER BY lesson ASC
    """,
        (course_id,),
    )
    lessons_available = [row[0] for row in cursor.fetchall()]
    lessons_available = [x for x in lessons_available if isinstance(x, int)]  # Remove from list
    lessons_available.sort()

    # Find what lesson was
    lessons_completed = []
    cursor.execute(
        """
        SELECT DISTINCT lesson FROM homeworks
        WHERE course_id = ? and user_id = ?
        ORDER BY lesson ASC
    """,
        (
            course_id,
            user_id,
        ),
    )
    lessons_completed = [row[0] for row in cursor.fetchall()]
    lessons_completed = [x for x in lessons_completed if isinstance(x, int)]  # Remove from list
    lessons_completed.sort()

    # Make report
    skipped_lessons = sorted(list(set(lessons_available) - set(lessons_completed)))

    # Make short log
    skipped_ranges = []
    start = None
    end = None

    for i in range(len(skipped_lessons)):
        if start is None:
            start = skipped_lessons[i]
            end = skipped_lessons[i]
        elif skipped_lessons[i] == end + 1:
            end = skipped_lessons[i]
        else:
            if start == end:
                skipped_ranges.append(str(start))
            else:
                skipped_ranges.append(f"{start}..{end}")
            start = skipped_lessons[i]
            end = skipped_lessons[i]

    if start is not None:
        if start == end:
            skipped_ranges.append(str(start))
        else:
            skipped_ranges.append(f"{start}..{end}")

    skipped_text = f'({", ".join(skipped_ranges)} - skipped)' if skipped_ranges else ""
    # Return full value
    return f"Lesson {progress} {skipped_text}"


# "Отображает историю домашних заданий пользователя
async def hw_history( update: Update, context: CallbackContext):
    """Отображает историю домашних заданий пользователя."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f"hw_history  {user_id}")
    try:
        # Получаем историю домашних заданий пользователя из базы данных
        cursor.execute(
            """
            SELECT course_id, lesson, status, submission_time
            FROM homeworks
            WHERE user_id = ?
            ORDER BY submission_time DESC
        """,
            (user_id,),
        )
        homeworks_data = cursor.fetchall()

        if not homeworks_data:
            await safe_reply(update, context, "У вас нет истории домашних заданий.")
            return

        # Формируем текстовое сообщение с историей ДЗ
        message_text = "История ваших домашних заданий:\n"
        for course_id, lesson, status, submission_time in homeworks_data:
            message_text += f" Курс: {course_id}, Урок: {lesson}, Статус: {status}, Дата отправки: {submission_time}\n"

        # await update.callback_query.message.reply_text(message_text)
        await safe_reply(update, context, message_text)

    except Exception as e:
        logger.error(f"Ошибка при отображении истории ДЗ: {e}")
        await safe_reply(update, context,
                         "Произошла ошибка при отображении истории домашних заданий. Попробуйте позже.")
        # await update.callback_query.message.reply_text("Произошла ошибка при отображении истории домашних заданий. Попробуйте позже.")


async def handle_check_payment(update: Update, context: CallbackContext, tariff_id: str):
    """Handles the "I Paid" button."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id

    logger.info(f"handle_check_payment: tariff_id={tariff_id}, user_id={user_id}")

    if not tariff_id:
        logger.error("handle_check_payment: tariff_id is empty.")
        await safe_reply(update, context, "Произошла ошибка: tariff_id не может быть пустым.")
        return

    logger.info(f"handle_check_payment: Извлеченный tariff_id: {tariff_id}")

    try:
        # Load tariffs from file
        try:
            with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
                tariffs = json.load(f)
            logger.info(f"handle_check_payment: Tariffs data loaded: {len(tariffs)}")
        except FileNotFoundError:
            logger.error(f"Tariff file not found: {TARIFFS_FILE}")
            await safe_reply(update, context, "Tariff file not found. Please try again later.")
            return
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from file: {TARIFFS_FILE}")
            await safe_reply(update, context, "Error decoding tariff data. Please try again later.")
            return

        # Find selected tariff
        selected_tariff = next((tariff for tariff in tariffs if tariff["id"] == tariff_id), None)

        if selected_tariff:
            logger.info(f"Handling check payment for tariff: {selected_tariff}")

            # Send notification to admins
            message = (f"Пользователь {user_id} запросил проверку оплаты тарифа {selected_tariff['title']}.\n"
                       f"Необходимо проверить оплату и активировать тариф для пользователя.")
            # Send notification to all admin IDs
            for admin_id in ADMIN_IDS:  # Ensure ADMIN_IDS is a list of strings
                try:
                    await context.bot.send_message(chat_id=admin_id, text=message)
                    logger.info(f"Sent payment verification request to admin {admin_id}")
                except TelegramError as e:
                    logger.error(f"Failed to send message to admin {admin_id}: {e}")

            await safe_reply(update, context,
                             "Ваш запрос на проверку оплаты отправлен всем администраторам в личку. Ожидайте подтверждения.")

        else:
            logger.warning(f"Tariff with id {tariff_id} not found.")
            await safe_reply(update, context, "Tariff not found. Please select again.")

    except Exception as e:
        logger.exception(f"Error handling check payment: {e}")
        await safe_reply(update, context, "Error processing payment verification. Please try again later.")


# Устанавливает выбранный тариф для пользователя
async def set_tariff( update: Update, context: CallbackContext):
    """Устанавливает выбранный тариф для пользователя."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    logger.info(f"  set_tariff ")
    query = update.callback_query
    try:
        # Извлекаем данные из callback_data
        _, course_id, tariff = query.data.split("|")

        # Обновляем тариф в базе данных
        cursor.execute(
            """
            UPDATE user_courses
            SET tariff = ?
            WHERE user_id = ? AND course_id = ?
        """,
            (tariff, query.from_user.id, course_id),
        )
        conn.commit()

        # Обновляем информацию о тарифе в таблице users
        cursor.execute(
            """
            UPDATE users
            SET tariff = ?
            WHERE user_id = ?
        """,
            (tariff, query.from_user.id),
        )
        conn.commit()

        # Отправляем подтверждение пользователю
        await safe_reply(update, context, f"Тариф для курса {course_id} изменен на {tariff}.")

    except Exception as e:
        logger.error(f"Ошибка при установке тарифа: {e}")
        await safe_reply(update, context, "Произошла ошибка при установке тарифа. Попробуйте позже.")


async def show_support( update: Update, context: CallbackContext):
    """Отображает информацию о поддержке."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    logger.info(f" show_support  ")
    await update.message.reply_text("Здесь будет информация о поддержке.")


# самопроверка на базовом тарифчике пт 14 марта 17:15
async def self_approve_homework( update: Update, context: CallbackContext):
    """Обрабатывает самопроверку домашнего задания."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    try:
        # Извлекаем hw_id из текста сообщения
        hw_id = int(context.args[0])

        # Обновляем статус домашнего задания в базе данных
        cursor.execute(
            """
            UPDATE homeworks
            SET status = 'approved', approval_time = (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
            WHERE hw_id = ? AND user_id = ?
        """,
            (hw_id, user_id),
        )
        conn.commit()

        # Отправляем сообщение об успешной самопроверке
        await update.message.reply_text("Домашнее задание подтверждено вами.")

        # и добавляем бонусы токены
        bonus_amount = bonuses_config.get("homework_bonus", 3)
        add_coins(user_id, bonus_amount)
        # Отправка подтверждения пользователю
        await context.bot.send_message(chat_id=user_id, text=f"✅ Домашка принята! Вам начислено {bonus_amount} коинов.")

    except (IndexError, ValueError):
        # Обрабатываем ошибки, если не удалось извлечь hw_id
        await update.message.reply_text("Неверный формат команды. Используйте /self_approve<hw_id>.")
    except Exception as e:
        # Обрабатываем другие возможные ошибки
        logger.error(f"Ошибка при самопроверке домашнего задания: {e}")
        await update.message.reply_text("Произошла ошибка при самопроверке домашнего задания. Попробуйте позже.")


async def old_approve_homework( update: Update, context: CallbackContext):
    """Подтверждает домашнее задание администратором."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    # Проверяем, является ли update CallbackQuery
    if update.callback_query:
        query = update.callback_query
        await query.answer()  # Отправляем подтверждение, только если это CallbackQuery

        data = query.data.split("_")
        user_id = int(data[1])
        lesson = int(data[2])

        try:
            # Обновляем статус домашнего задания на "approved"
            cursor.execute(
                """
                UPDATE homeworks
                SET status = 'approved'
                WHERE user_id = ? AND lesson = ?
            """,
                (user_id, lesson),
            )
            conn.commit()

            # Уведомляем пользователя
            await context.bot.send_message(chat_id=user_id, text=f"Домашнее задание по уроку {lesson} принято!")
            await safe_reply(update, context, text="Домашнее задание подтверждено администратором.")
        except Exception as e:
            logger.error(f"Ошибка при подтверждении домашнего задания: {e}")
            await safe_reply(update, context, "Произошла ошибка при подтверждении домашнего задания.")
    else:
        logger.warning("Получен update не типа CallbackQuery. Обработка прервана.")
        # Можно добавить обработку для других типов update, если необходимо
        await safe_reply(update, context, "Эта команда работает только через CallbackQuery.")


async def handle_approve_payment(update: Update, context: CallbackContext, user_id: str, tariff_id: str):
    """Handles the "Approve Payment" button."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    # Проверяем, является ли update CallbackQuery
    if update.callback_query:
        query = update.callback_query
        admin_id = update.effective_user.id

        try:
            # Load tariffs from file
            with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
                tariffs = json.load(f)

            # Find selected tariff
            selected_tariff = next((tariff for tariff in tariffs if tariff["id"] == tariff_id), None)

            if selected_tariff:
                logger.info(f"Handling approve payment for tariff: {selected_tariff}")

                # Add logic for activating the tariff for the user here
                # This could involve updating the user's subscription status,
                # adding the user to a course, etc.

                await safe_reply(update, context,
                                 f"Оплата тарифа {selected_tariff['title']} для пользователя {user_id} одобрена администратором {admin_id}."
                                 )
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Ваша оплата тарифа {selected_tariff['title']} подтверждена. Теперь вам доступны все материалы курса.",
                )

            else:
                logger.warning(f"Tariff with id {tariff_id} not found.")
                await safe_reply(update, context, "Выбранный тариф не найден.")
        except Exception as e:
            logger.error(f"Error handling approve payment: {e}")
            await safe_reply(update, context, "Произошла ошибка при одобрении оплаты. Попробуйте позже.")
    else:
        logger.warning("Получен update не типа CallbackQuery. Обработка прервана.")
        # Можно добавить обработку для других типов update, если необходимо
        await safe_reply(update, context, "Эта команда работает только через CallbackQuery.")


async def handle_decline_payment(update: Update, context: CallbackContext, user_id: str,tariff_id: str):
    """Handles the "Decline Payment" button."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    # Проверяем, является ли update CallbackQuery
    if update.callback_query:
        query = update.callback_query
        admin_id = update.effective_user.id

        try:
            # Load tariffs from file
            with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
                tariffs = json.load(f)

            # Find selected tariff
            selected_tariff = next((tariff for tariff in tariffs if tariff["id"] == tariff_id), None)

            if selected_tariff:
                logger.info(f"Handling decline payment for tariff: {selected_tariff}")

                # Add logic for declining the payment for the user here
                # This could involve sending the user a refund,
                # notifying the user that their payment has been declined, etc.

                await safe_reply(update, context,
                                 f"Оплата тарифа {selected_tariff['title']} для пользователя {user_id} отклонена администратором {admin_id}."
                                 )
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Ваша оплата тарифа {selected_tariff['title']} отклонена. Обратитесь в службу поддержки.",
                )

            else:
                logger.warning(f"Tariff with id {tariff_id} not found.")
                await safe_reply(update, context, "Выбранный тариф не найден.")
        except Exception as e:
            logger.error(f"Error handling decline payment: {e}")
            await safe_reply(update, context, "Произошла ошибка при отклонении оплаты. Попробуйте позже.")
    else:
        logger.warning("Получен update не типа CallbackQuery. Обработка прервана.")
        # Можно добавить обработку для других типов update, если необходимо
        await safe_reply(update, context, "Эта команда работает только через CallbackQuery.")


# Отображает настройки курса *
async def show_course_settings( update: Update, context: CallbackContext):
    """Отображает настройки курса."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.error(f"show_course_settings {user_id}")
    try:
        # Получаем времена уведомлений из базы данных
        cursor.execute(
            "SELECT morning_notification, evening_notification FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        settings = cursor.fetchone()
        morning_time = settings[0] if settings else "Не установлено"
        evening_time = settings[1] if settings else "Не установлено"

        # Формируем сообщение с настройками
        text = (
            f"Ваши текущие настройки:\n\n"
            f"⏰ Утреннее напоминание: {morning_time}\n"
            f"🌙 Вечернее напоминание: {evening_time}\n\n"
            f"Вы можете изменить эти настройки через соответствующие команды."
        )

        await safe_reply(update, context, text)

    except Exception as e:
        logger.error(f"Ошибка при отображении настроек курса для пользователя {user_id}: {e}")
        await safe_reply(update, context, "Произошла ошибка при загрузке настроек. Попробуйте позже.")


# Отображает тарифы и акции. *
async def show_tariffs( update: Update, context: CallbackContext):
    """Отображает доступные тарифы и бонусы."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f"show_tariffs --------------------- 222")

    try:
        # Проверяем, является ли update CallbackQuery
        if update.callback_query:
            query = update.callback_query
            await query.answer()
        else:
            logger.warning("Получен update не типа CallbackQuery. Обработка прервана.")
            await safe_reply(update, context, "Эта команда работает только через CallbackQuery.")
            return

        # Загружаем тарифы из файла
        try:
            with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
                tariffs_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Ошибка при загрузке тарифов: {e}")
            await safe_reply(update, context, "Невозможно отобразить тарифы. Попробуйте позже.")
            return

        # Формируем кнопки для каждого тарифа
        keyboard = []
        logger.info(f"show_tariffs3 ------------------- 333")
        for tariff in tariffs_data:
            if "title" not in tariff:
                logger.error(f"Tariff missing 'title' key: {tariff.get('id', 'Unknown')}")
                continue
            callback_data = f"tariff_{tariff['id']}"
            keyboard.append([InlineKeyboardButton(tariff["title"], callback_data=callback_data)])

        keyboard.append([InlineKeyboardButton("Назад", callback_data="menu_back")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        logger.info(f"show_tariffs4  готово ------------------- 333")

        await safe_reply(update, context, "Вот доступные тарифы и бонусы:", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error during show tariffs: {e}")
        await safe_reply(update, context, "Something went wrong.")


# "Показывает текст урока по запросу."*
async def show_lesson( update: Update, context: CallbackContext):
    """Отправляет все материалы текущего урока, включая текст и файлы, а также напоминает о ДЗ."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f"show_lesson {user_id} - Current state")

    try:
        # Получаем active_course_id из users
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await safe_reply(update, context, "Активируйте курс через кодовое слово.")
            return

        active_course_id_full = active_course_data[0]
        active_course_id = active_course_id_full.split("_")[0]
        logger.info(f"active_course_id {active_course_id} +")

        # Получаем progress (номер урока) из user_courses
        cursor.execute(
            "SELECT progress FROM user_courses WHERE user_id = ? AND course_id = ?",
            (user_id, active_course_id_full),
        )
        progress_data = cursor.fetchone()

        lesson = progress_data[0] if progress_data else 1
        if not progress_data:
            await safe_reply(update, context, "Начинаем с первого урока.")

        # 1. Отправляем текст урока
        lesson_data = get_lesson_text(lesson, active_course_id)
        if lesson_data and lesson_data[0]:  # Проверяем оба элемента кортежа
            lesson_text, parse_mode = lesson_data
            await safe_reply(update, context, lesson_text, parse_mode=parse_mode)
        else:
            await safe_reply(update, context, "Текст урока не найден.")
            return  # Выходим из функции, если текст урока не найден

        # 2. Отправляем файлы урока (аудио, видео, изображения)
        lesson_files = get_lesson_files(user_id, lesson, active_course_id)
        if lesson_files:
            for file_info in lesson_files:
                file_path = file_info["path"]
                delay = file_info["delay"]
                file_type = file_info["type"]

                if delay > 0:
                    logger.info(f"на  {file_path} задержка {delay}  asyncio.sleep ===============================")
                    await asyncio.sleep(delay)

                try:
                    with open(file_path, "rb") as file:
                        if file_type == "photo":
                            await context.bot.send_photo(chat_id=user_id, photo=file, caption=f"Фото к уроку {lesson}")
                        elif file_type == "audio":
                            await context.bot.send_audio(chat_id=user_id, audio=file, caption=f"Аудио к уроку {lesson}")
                        elif file_type == "video":
                            await context.bot.send_video(chat_id=user_id, video=file, caption=f"Видео к уроку {lesson}")
                        elif file_type == "document":
                            await context.bot.send_document(chat_id=user_id, document=file,
                                                            caption=f"Документ к уроку {lesson}")
                        else:
                            logger.warning(f"Неизвестный тип файла: {file_type}, {file_path}")

                except FileNotFoundError as e:
                    logger.error(f"Файл не найден: {file_path} - {e}")
                    await safe_reply(update, context, f"Файл {os.path.basename(file_path)} не найден.")
                except TelegramError as e:
                    logger.error(f"Ошибка при отправке файла {file_path}: {e}")
                    await safe_reply(update, context,
                                     f"Произошла ошибка при отправке файла {os.path.basename(file_path)}.")
                except Exception as e:
                    logger.error(f"Неожиданная ошибка при отправке файла {file_path}: {e}")
                    await safe_reply(update, context,
                                     f"Произошла непредвиденная ошибка при отправке файла {os.path.basename(file_path)}.")

        else:
            await safe_reply(update, context, "Файлы к этому уроку не найдены.")

        await show_main_menu (update, context)  # Показываем меню, даже если файлов нет
        homework_status = await get_homework_status_text(user_id, active_course_id_full)
        await safe_reply(update, context, f"Напоминаем: {homework_status}")

    except Exception as e:  # это часть show_lesson
        logger.error(f"Ошибка при получении материалов урока: {e}")
        await safe_reply(update, context, "Ошибка при получении материалов урока. Попробуйте позже.")


# 28-03 Функция для получения файлов урока =
async def get_lesson_files(user_id=1, lesson_number=1, active_course_id="femininity_premium"):
    """Получает список файлов для урока."""
    logger.info(f"01819 начало  get_lesson_files  {user_id=}, {lesson_number=}, {active_course_id=} ")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    lesson_files = []
    course_directory = active_course_id
    logger.info(f"1819 get_lesson_files {course_directory=}")

    # Проверка существования директории курса
    if not os.path.exists(course_directory):
        logger.error(f"Директория курса не найдена: {course_directory}")
        return lesson_files

    try:
        # Перебираем все файлы в директории
        all_files = os.listdir(course_directory)
        logger.info(f"1820 внутри трая считываем всё из {all_files[:3]}")

        # Фильтруем файлы, которые соответствуют текущему уроку
        lesson_files_names = [f for f in all_files if f.startswith(f"lesson{lesson_number}")]
        logger.info(f"1821  get_lesson_files {user_id=} - {lesson_number=} lesson_files_names {lesson_files_names}")

        # Добавляем информацию о каждом файле в список
        lesson_files = []
        for file_name in lesson_files_names:
            file_path = os.path.join(course_directory, file_name)

            # Проверяем, является ли элемент файлом
            if os.path.isfile(file_path):
                # Определяем MIME-тип файла
                mime_type = mimetypes.guess_type(file_path)[0]
                if mime_type is None:
                    # Если MIME-тип не определен, проверяем по расширению
                    if file_path.endswith((".txt", ".md", ".html")):
                        file_type = "text"
                    else:
                        file_type = "document"
                elif mime_type.startswith("image/"):
                    file_type = "photo"
                elif mime_type.startswith("video/"):
                    file_type = "video"
                elif mime_type.startswith("audio/"):
                    file_type = "audio"
                else:
                    file_type = "document"
                # Ищем задержку в имени файла
                match = DELAY_PATTERN.search(file_name)
                delay = 0
                if match:
                    delay_value, delay_unit = int(match.group(1)), match.group(2)
                    if delay_unit in ("hour", "h"):
                        delay = delay_value * 3600
                    elif delay_unit in ("min", "m"):
                        delay = delay_value * 60
                lesson_files.append({"path": file_path, "type": file_type, "delay": delay})

        logger.info(f"33 lesson_files={lesson_files[:2]}")
        return lesson_files

    except Exception as e:
        logger.error(f"Ошибка при получении списка файлов урока: {e}")
        return []


# предварительные задания
async def send_preliminary_material( update: Update, context: CallbackContext):
    """Отправляет предварительные материалы для следующего урока."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f"send_preliminary_material for user_id {user_id}")

    try:
        if update.callback_query:
            query = update.callback_query
            await query.answer()  # Отвечаем на CallbackQuery
        else:
            logger.warning("Это не CallbackQuery")
            await safe_reply(update, context, "Эта функция работает только через CallbackQuery.")
            return

        # Получаем active_course_id из users
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await safe_reply(update, context, "Для начала активируйте кодовое слово курса.")
            return

        active_course_id_full = active_course_data[0]
        active_course_id = active_course_id_full.split("_")[0]

        # Получаем progress (номер урока) из user_courses
        cursor.execute(
            "SELECT progress FROM user_courses WHERE user_id = ? AND course_id = ?",
            (user_id, active_course_id_full),
        )
        progress_data = cursor.fetchone()

        if not progress_data:
            await safe_reply(update, context, "Прогресс курса не найден. Пожалуйста, начните курс сначала.")
            return

        lesson = progress_data[0]
        next_lesson = lesson + 1

        # Получаем список предварительных материалов
        materials = get_preliminary_materials(active_course_id, next_lesson)

        if not materials:
            await safe_reply(update, context, "Предварительные материалы для следующего урока отсутствуют.")
            return

        # Отправляем материалы
        for material_file in materials:
            material_path = f"courses/{active_course_id}/{material_file}"

            try:
                with open(material_path, "rb") as file:
                    if material_file.endswith((".jpg", ".jpeg", ".png", ".gif")):
                        await context.bot.send_photo(chat_id=user_id, photo=file,
                                                     caption=f"Предварительный материал к уроку {next_lesson}")
                    elif material_file.endswith((".mp4", ".avi", ".mov")):
                        await context.bot.send_video(chat_id=user_id, video=file,
                                                     caption=f"Предварительный материал к уроку {next_lesson}")
                    elif material_file.endswith((".mp3", ".wav", ".ogg")):
                        await context.bot.send_audio(chat_id=user_id, audio=file,
                                                     caption=f"Предварительный материал к уроку {next_lesson}")
                    else:
                        await context.bot.send_document(chat_id=user_id, document=file,
                                                        caption=f"Предварительный материал к уроку {next_lesson}")

            except FileNotFoundError:
                logger.error(f"Файл не найден: {material_path}")
                await safe_reply(update, context, f"Файл {material_file} не найден.")
            except TelegramError as e:
                logger.error(f"Ошибка при отправке файла {material_file}: {e}")
                await safe_reply(update, context, f"Произошла ошибка при отправке файла {material_file}.")
            except Exception as e:
                logger.error(f"Неожиданная ошибка при отправке файла {material_file}: {e}")
                await safe_reply(update, context,
                                 f"Произошла непредвиденная ошибка при отправке файла {material_file}.")

        await safe_reply(update, context, "Все предварительные материалы для следующего урока отправлены.")
        logger.info(' 227 Все предварительные материалы для следующего урока отправлены.')

    except Exception as e:
        logger.error(f"Общая ошибка при отправке предварительных материалов: {e}")
        await safe_reply(update, context, "Произошла ошибка при отправке предварительных материалов. Попробуйте позже.")


async def handle_go_to_payment(update: Update, context: CallbackContext, tariff_id: str):
    """Handles the "Go to Payment" button."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f"handle_go_to_payment for user_id {user_id}")

    try:
        # Load tariffs from file
        with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
            tariffs = json.load(f)

        # Find selected tariff
        selected_tariff = next((tariff for tariff in tariffs if tariff["id"] == tariff_id), None)

        if not selected_tariff:
            logger.warning(f"Tariff with id {tariff_id} not found.")
            await safe_reply(update, context, "Выбранный тариф не найден.")
            return

        logger.info(f"Handling go to payment for tariff: {selected_tariff}")

        # Get payment information
        phone_number = PAYMENT_INFO.get("phone_number")
        name = PAYMENT_INFO.get("name")
        payment_message = PAYMENT_INFO.get("payment_message")
        amount = selected_tariff.get("price")

        if not all([phone_number, name, payment_message, amount]):
            logger.error("Missing payment information.")
            await safe_reply(update, context, "Произошла ошибка. Не удалось получить информацию об оплате.")
            return

        # Format payment message
        formatted_message = payment_message.format(amount=amount)

        # Create keyboard
        keyboard = [
            [InlineKeyboardButton("Я оплатил", callback_data=f"check_payment_{tariff_id}")],
            [InlineKeyboardButton("Назад к тарифам", callback_data="tariffs")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send message with payment information
        await safe_reply(
            update,
            context,
            f"{formatted_message}\nНомер телефона: {phone_number}\nИмя: {name}",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Error handling go to payment: {e}")
        await safe_reply(update, context, "Произошла ошибка при переходе к оплате. Попробуйте позже.")


async def handle_buy_tariff(update: Update, context: CallbackContext, tariff_id: str):
    """Handles the 'Buy' button click."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f"handle_buy_tariff: tariff_id={tariff_id}, user_id={user_id}")

    try:
        # Load tariffs from file
        try:
            with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
                tariffs = json.load(f)
            logger.info(f"handle_buy_tariff: Tariffs data loaded from {TARIFFS_FILE}")
        except FileNotFoundError:
            logger.error(f"handle_buy_tariff: File {TARIFFS_FILE} not found.")
            await safe_reply(update, context, "Произошла ошибка: файл с тарифами не найден.")
            return
        except json.JSONDecodeError as e:
            logger.error(f"handle_buy_tariff: Error reading JSON from {TARIFFS_FILE}: {e}")
            await safe_reply(update, context, "Произошла ошибка: не удалось прочитать данные о тарифах.")
            return
        except Exception as e:
            logger.error(f"handle_buy_tariff: Unexpected error loading tariffs: {e}")
            await safe_reply(update, context, "Произошла непредвиденная ошибка. Попробуйте позже.")
            return

        # Find selected tariff
        selected_tariff = next((tariff for tariff in tariffs if tariff["id"] == tariff_id), None)

        if not selected_tariff:
            logger.warning(f"handle_buy_tariff: Tariff with id '{tariff_id}' not found.")
            await safe_reply(update, context, "Выбранный тариф не найден. Пожалуйста, выберите тариф снова.")
            return

        logger.info(f"handle_buy_tariff: Found tariff: {selected_tariff}")

        # Load payment information
        payment_info = load_payment_info(PAYMENT_INFO_FILE)

        if not payment_info:
            logger.error("handle_buy_tariff: Failed to load payment information.")
            await safe_reply(update, context, "Произошла ошибка: не удалось получить информацию об оплате.")
            return

        phone_number = payment_info.get("phone_number")
        name = payment_info.get("name")
        payment_message = payment_info.get("payment_message")
        amount = selected_tariff.get("price")

        if not all([phone_number, name, payment_message, amount]):
            logger.error("handle_buy_tariff: Missing required payment information.")
            await safe_reply(update, context, "Произошла ошибка: отсутствует необходимая информация для оплаты.")
            return

        # Format payment message
        formatted_message = payment_message.format(amount=amount)

        # Create keyboard
        keyboard = [
            [InlineKeyboardButton("Я оплатил", callback_data=f"check_payment_{tariff_id}")],
            [InlineKeyboardButton("Назад к тарифам", callback_data="tariffs")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send message with payment information
        payment_info_message = (
            f"Для оплаты тарифа '{selected_tariff['title']}' выполните следующие действия:\n\n"
            f"{formatted_message}\n"
            f"Номер телефона: {phone_number}\n"
            f"Имя получателя: {name}\n\n"
            f"После оплаты нажмите кнопку 'Я оплатил'."
        )

        await safe_reply(update, context, payment_info_message, reply_markup=reply_markup)
        logger.info(f"handle_buy_tariff: Payment message sent to user {user_id}")

    except Exception as e:
        logger.exception(f"handle_buy_tariff: Unexpected error processing purchase: {e}")
        await safe_reply(update, context, "Произошла непредвиденная ошибка при обработке покупки. Попробуйте позже.")


async def get_gallery_count(conn: sqlite3.Connection, cursor: sqlite3.Cursor):
    """ Считает количество работ в галерее (реализация зависит от способа хранения галереи). """
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    cursor.execute('SELECT COUNT(*) FROM homeworks WHERE status = "approved"')
    logger.info(f"get_gallery_count -------------<")
    return cursor.fetchone()[0]


# галерея
async def show_gallery( update: Update, context: CallbackContext):
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    logger.info(f"show_gallery -------------< и сразу ныряем в get_random_homework")
    await get_random_homework (update, context)


# галерейка
async def old_get_random_homework( update: Update,  context: CallbackContext):
    """Отображает случайную одобренную работу из галереи."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f"get_random_homework -------------< for user_id {user_id}")

    try:
        if update.callback_query:
            query = update.callback_query
            await query.answer()
        else:
            query = None  # Устанавливаем query в None, чтобы избежать ошибок
            logger.warning("Эта функция работает только через CallbackQuery.")
            await safe_reply(update, context, "Эта функция работает только через CallbackQuery.")
            return

        # Получаем случайную одобренную работу
        cursor.execute(
            """
            SELECT hw_id, user_id, course_type, lesson, file_id
            FROM homeworks
            WHERE status = 'approved'
            ORDER BY RANDOM()
            LIMIT 1
        """
        )
        hw = cursor.fetchone()

        if not hw:
            # Если работ нет, показываем сообщение и возвращаем в основное меню
            message = "В галерее пока нет работ 😞\nХотите стать первым?"
            await safe_reply(update, context, message)
            await show_main_menu (update, context)  # Возвращаем в основное меню
            return

        hw_id, author_id, course_type, lesson, file_id = hw

        # Получаем информацию об авторе
        cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (author_id,))
        author_data = cursor.fetchone()
        author_name = author_data[0] if author_data and author_data[0] else "Аноним"

        # Формируем текст сообщения
        text = (
            f"📚 Курс: {course_type}\n"
            f"📖 Урок: {lesson}\n"
            f"👩🎨 Автор: {author_name}\n\n"
            "➖➖➖➖➖➖➖➖➖➖\n"
            "Чтобы увидеть другую работу - нажмите «Следующая»"
        )

        # Создаем клавиатуру
        keyboard = [
            [InlineKeyboardButton("Следующая работа ➡️", callback_data="gallery_next")],
            [InlineKeyboardButton("Вернуться в меню ↩️", callback_data="menu_back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            # Отправляем файл с клавиатурой
            if file_id.startswith('http'):
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=file_id,
                    caption=text,
                    reply_markup=reply_markup,
                )
            else:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=file_id,
                    caption=text,
                    reply_markup=reply_markup,
                )
        except Exception as e:
            logger.error(f"Ошибка отправки работы: {e}")
            await safe_reply(update, context, "Не удалось загрузить работу 😞", reply_markup=reply_markup)


    except Exception as e:
        logger.error(f"Ошибка при получении случайной работы: {e}")
        await safe_reply(update, context, "Произошла ошибка при загрузке работы. Попробуйте позже.")

# *
# Get Random Homework
# 18-03 17-00 Perplexity
async def get_random_homework(update: Update, context: CallbackContext):
    """Get a random homework."""
    logger.info(f" get_random_homework -------------< for user_id {update.effective_user.id}")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        logger.error("Could not get user ID - effective_user is None")
        return

    try:
        # 1. Get the course_id associated with the user
        cursor.execute(
            """
            SELECT uc.course_id
            FROM user_courses uc
            WHERE uc.user_id = ?
            """,
            (user_id,),
        )
        user_course_data = cursor.fetchone()
        if user_course_data:
            course_id = user_course_data[0]  # Only fetch course_id
        else:
            logger.warning("Пользователь не имеет активного курса.")
            await safe_reply(update, context, "У вас нет активного курса. Активируйте курс через кодовое слово.")
            return

        # 2. Get a random homework submission for the course, with images.
        cursor.execute(
            """
            SELECT hw_id,file_id,file_type  -- Only the file_id and hw_id, file_type are necessary
            FROM homeworks
            WHERE course_id = ? AND file_type in ('photo','document')
            ORDER BY RANDOM()
            LIMIT 1
            """,
            (course_id,),
        )

        homework = cursor.fetchone()

        if homework:
            hw_id, file_id, file_type = homework  # Unpack the values
            logger.info(f"file_id={file_id}  and hw_id {hw_id}")

            # Send the file
            if file_type == "photo":
                try:
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id, photo=file_id, caption=f"Домашняя работа - hw_id {hw_id}"
                    )
                except Exception as e:
                    logger.error(f" Ошибка при отправке фото: {e}")
                    await safe_reply(update, context, "Произошла ошибка при загрузке работы. Попробуйте позже.")
            elif file_type == "document":
                try:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=file_id,
                        caption=f"Домашняя работа - hw_id {hw_id}",
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке документа: {e}")
                    await safe_reply(update, context, "Произошла ошибка при загрузке работы. Попробуйте позже.")
        else:
            await safe_reply(update, context, "К сожалению, работы пока не загружены. Будьте первым!")
            return

        logger.info(f"  351 После ответа")
    except Exception as e:
        logger.exception(f" Ошибка при получении случайной работы")
        await safe_reply(update, context, "Произошла ошибка при загрузке работы. Попробуйте позже.")


async def unknown_command(update: Update, context: CallbackContext):
    """Обработчик для неизвестных команд."""
    await update.message.reply_text("Извините, я не знаю такой команды. Пожалуйста, введите /help, чтобы увидеть список доступных команд.")


async def button_handler(update: Update, context: CallbackContext):
    """Handles button presses."""
    logger.info(f"1532 button_handler ")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id if update.effective_user else None  # Safe get user_id
    logger.info(f" 1518 button_handler для  {user_id} - {data=}")
    await query.answer()

    # Обрабатывает нажатия на кнопки все
    button_handlers = {
        'get_current_lesson': get_current_lesson,
        'gallery': show_gallery,
        'gallery_next': lambda update, context: get_random_homework(update, context),
        'menu_back': show_main_menu,
        'support': show_support,
        'tariffs': show_tariffs,
        'course_settings': show_course_settings,
        'statistics': show_statistics,
        'preliminary_tasks': send_preliminary_material,
    }

    try:
        # Admin commands
        if str(user_id) in ADMIN_IDS:
            if data.startswith("approve_payment_"):
                logger.info(f" 1560 approve_payment_ ")
                payment_id = data.split("_")[-1]
                await handle_approve_payment(update, context, payment_id)
                return

            elif data.startswith("decline_payment_"):
                logger.info(f" 1561 decline_payment_ ")
                payment_id = data.split("_")[-1]
                await handle_decline_payment(update, context, payment_id)
                return

            elif data.startswith("approve_homework_"):
                logger.warning(f"666 approve_homework_ откуда то вылез, а ведь мы его убивали в среду!")

            elif data.startswith("approve_admin_check_"):
                try:
                    parts = data.split("_")
                    logger.info(f" 1562 approve_admin_check_ {data=} parts {parts=}")
                    if len(parts) == 5:
                        action, user_id_to_approve, course_id, lesson = parts[1:]  # Пропускаем "approve"
                        user_id_to_approve = int(user_id_to_approve)
                        lesson = int(lesson)
                        logger.info(f"1553 approve_admin_check_ {user_id_to_approve=}")
                        await approve_homework(update, context, course_id, user_id_to_approve, lesson)
                        return
                    else:
                        logger.warning(f"668 Неверный формат callback_data: {data}")
                        await safe_reply(update, context, "Неверный формат данных.")

                except ValueError as e:
                    logger.error(f"667 Ошибка при обработке callback_data: {e}")
                    await safe_reply(update, context, "Ошибка: Неверный формат данных.")

            elif data.startswith("approve_self_check_"):
                try:
                    parts = data.split("_")
                    logger.info(f" 1564 approve_self_check_ {data=} parts {parts=}")
                    if len(parts) == 5:
                        action, user_id_to_approve, course_id, lesson = parts[1:]  # Пропускаем "approve"
                        user_id_to_approve = int(user_id_to_approve)
                        lesson = int(lesson)
                        logger.info(f"1558 approve_homework_ {user_id_to_approve=}")
                        await approve_homework(update, context, course_id, user_id_to_approve, lesson)
                        return
                    else:
                        logger.warning(f"Неверный формат callback_data: {data}")
                        await safe_reply(update, context, "Неверный формат данных.")

                except ValueError as e:
                    logger.error(f"Ошибка при обработке callback_data: {e}")
                    await safe_reply(update, context, "Ошибка: Неверный формат данных.")


            elif data.startswith("decline_homework_"):
                try:
                    parts = data.split("_")
                    logger.info(f" 1566 decline_homework_ {data=} parts {parts=}")
                    if len(parts) == 5:
                        action, user_id_to_approve, course_id, lesson = parts[1:]  # Пропускаем "decline_"
                        user_id_to_approve = int(user_id_to_approve)
                        lesson = int(lesson)
                        logger.info(f"1555 decline_homework_ {user_id_to_approve=}")

                        # Запрос причины отказа у админа
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text="Введите причину отказа для пользователя:",
                        )

                        # Сохраняем данные о домашке в user_data для дальнейшей обработки
                        context.user_data["decline_homework"] = {
                            "user_id": user_id_to_approve,
                            "course_id": course_id,
                            "lesson": lesson,
                        }
                    else:
                        logger.warning(f"200 Неверный формат callback_data: {data}")
                        await safe_reply(update, context, "Неверный формат данных.")

                except ValueError as e:
                    logger.error(f"194 Ошибка при обработке callback_data: {e}")
                    await safe_reply(update, context, "Ошибка: Неверный формат данных.")


            elif data.startswith("view_rejection_history|"):
                try:
                    parts = data.split("|")
                    logger.info(f" 1568 view_rejection_history {data=} parts {parts=}")

                    if len(parts) == 3:
                        action, user_id_to_view, course_id = parts
                        user_id_to_view = int(user_id_to_view)

                        # Получаем историю отказов
                        db = DatabaseConnection()
                        conn = db.get_connection()
                        cursor = db.get_cursor()
                        cursor.execute(
                            """
                            SELECT lesson, reason, rejected_at
                            FROM homework_rejections
                            WHERE user_id = ? AND course_id = ?
                            ORDER BY rejected_at DESC
                            """,
                            (user_id_to_view, course_id),
                        )
                        rejections = cursor.fetchall()

                        # Формируем текст истории
                        if rejections:
                            history_text = "История отказов:\n\n"
                            for lesson, reason, rejected_at in rejections:
                                history_text += f"Урок {lesson}:\nПричина: {reason}\nДата: {rejected_at}\n\n"
                        else:
                            history_text = "История отказов отсутствует."

                        # Отправляем историю админу

                        await safe_reply(
                            update=Update.de_json({"message": {"chat": {"id": update.effective_chat.id}}}, context.bot),

                            context=context,

                            text=history_text)

                    else:

                        logger.warning(f"Неверный формат callback_data: {data}")

                        await safe_reply(update, context, "Неверный формат данных.")


                except ValueError as e:

                    logger.error(f"Ошибка при обработке callback_data: {e}")

                    await safe_reply(update, context, "Ошибка: Неверный формат данных.")

        # User commands
        if data.startswith('tariff_'):
            logger.info(f" 777 данные {data} ==================")
            tariff_id = data.split('_', 1)[1]
            logger.info(f" handler для handle_tariff_selection {tariff_id}")
            await handle_tariff_selection(update, context, tariff_id)

        elif data.startswith('buy_tariff_'):
            tariff_id = data.split('_', 2)[2]
            logger.info(f" handler для handle_buy_tariff {tariff_id}")
            await handle_buy_tariff(update, context, tariff_id)

        elif data.startswith('go_to_payment_'):
            tariff_id = data.split('_', 2)[2]
            logger.info(f" handler для handle_go_to_payment {tariff_id}")
            await handle_go_to_payment(update, context, tariff_id)

        elif data.startswith('check_payment_'):
            try:
                tariff_id = data.split('_', 2)[1]  # Извлекаем tariff_id правильно
                logger.info(f" handler для handle_check_payment {tariff_id}")
            except IndexError:
                logger.error(f"Не удалось извлечь tariff_id из data: {data} ====== 8888")
                await safe_reply(update, context, "Произошла ошибка. Попробуйте позже.")
                return
            await handle_check_payment(update, context, tariff_id)

        elif data in button_handlers:
            handler = button_handlers[data]
            await handler(update, context)
        else:
            await safe_reply(update, context, "Unknown command")
    except Exception as e:
        logger.error(f"Error: {e}")
        await safe_reply(update, context, "Произошла ошибка. Попробуйте позже.")


async def handle_admin_comment(update: Update, context: CallbackContext):
    """Обрабатывает текст причины отказа от админа."""
    logger.info(f"1899 handle_admin_comment")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    if "awaiting_admin_comment" not in context.user_data:
        await update.message.reply_text("Нет данных о домашнем задании для отказа.")
        return

    decline_data = context.user_data.pop("awaiting_admin_comment")
    user_id = decline_data["user_id"]
    course_id = decline_data["course_id"]
    lesson = decline_data["lesson"]
    reason = update.message.text

    # в базу запишем отказик. Штоб было
    cursor.execute(
        """
        INSERT INTO homework_rejections (user_id, course_id, lesson, reason)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, course_id, lesson, reason),
    )
    conn.commit()

    # Отправляем сообщение пользователю
    await context.bot.send_message(
        chat_id=user_id,
        text=f"Ваше домашнее задание по курсу {course_id}, урок {lesson}, было отклонено.\nПричина: {reason}",
    )

    # Логируем отказ
    logger.info(f"Домашка пользователя {user_id} по курсу {course_id}, урок {lesson}, была отклонена. Причина: {reason}")

    # Обновляем статус домашки в базе данных
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        cursor.execute(
            """
            UPDATE homeworks
            SET status = 'declined', admin_comment = ?
            WHERE user_id = ? AND course_id = ? AND lesson = ?
            """,
            (reason, user_id, course_id, lesson),
        )
        conn.commit()
        logger.info(f"Статус домашки обновлен на 'declined' для пользователя {user_id}, курс {course_id}, урок {lesson}.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при обновлении статуса домашки: {e}")



async def send_course_completion_report(update: Update, context: CallbackContext, user_id: int, course_id: str):
    """Отправляет отчет о завершении курса пользователю."""
    logger.info(f"660 send_course_completion_report  {user_id=} {course_id=}")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    # Получаем количество отказов по каждому уроку
    cursor.execute(
        """
        SELECT lesson, COUNT(*) AS rejections
        FROM homework_rejections
        WHERE user_id = ? AND course_id = ?
        GROUP BY lesson
        ORDER BY lesson
        """,
        (user_id, course_id),
    )
    rejection_stats = cursor.fetchall()

    # Формируем текст отчета
    report = f"Курс {course_id} завершен! 🎉\n\nСтатистика отказов по урокам:\n"
    for lesson, rejections in rejection_stats:
        report += f"Урок {lesson}: {rejections} отказ(а/ов)\n"

    # Отправляем отчет пользователю
    await safe_reply(update=update,
                     context=context,
                     text=report)


# выбор товара в магазине *
async def handle_tariff_selection(update: Update, context: CallbackContext, tariff_id: str):
    """Handles the selection of a tariff."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    query = update.callback_query
    logger.info(f"  handle_tariff_selection --------------------------------")
    try:
        logger.info(f"333 Handling tariff selection for tariff_id: {tariff_id}")
        with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
            tariffs = json.load(f)

        # Find selected tariff
        selected_tariff = next((tariff for tariff in tariffs if tariff["id"] == tariff_id), None)

        if not selected_tariff:
            logger.warning(f"Tariff with id {tariff_id} not found.")
            await safe_reply(update, context, "Выбранный тариф не найден.")
            return

        logger.info(f"Selected tariff: {len(selected_tariff)}")

        message = f"Вы выбрали: {selected_tariff['title']}\n\n{selected_tariff['description']}"

        if selected_tariff["type"] == "discount":
            message += f"\n\nСкидка: {int((1 - selected_tariff['price']) * 100)}%"
        elif selected_tariff["type"] == "payment":
            message += f"\n\nЦена: {selected_tariff['price']} руб."

        # Create buttons for "Buy" and "Back to Tariffs"
        keyboard = [
            [InlineKeyboardButton("Купить", callback_data=f"buy_tariff_{tariff_id}")],
            [InlineKeyboardButton("Назад к тарифам", callback_data="tariffs")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        # Edit message with tariff information and buttons
        await safe_reply(update, context, message, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error handling tariff selection: {e}")
        await safe_reply(update, context, "Произошла ошибка при выборе тарифа. Попробуйте позже.")


async def handle_text_message(update: Update, context: CallbackContext):
    """Handles text messages."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    text = update.message.text.lower()  # Convert text to lowercase
    logger.info(f"Handling text message from user {user_id}: {text}")

    # Если админ пишет комментарий к домашке
    if "awaiting_admin_comment" in context.user_data:
        logger.info(f"Admin {user_id} is providing a comment for homework.")
        await handle_admin_comment(update, context)
        return

    try:
        # Check if user is waiting for a code word
        if context.user_data.get("waiting_for_code"):
            logger.info("Ignoring message as user is waiting for code.")
            return  # Ignore message if waiting for code word

        # Handle specific commands
        if "предварительные" in text or "пм" in text:
            await send_preliminary_material(update, context)
            return

        if "текущий урок" in text or "ту" in text:
            await get_current_lesson(update, context)
            return

        if "галерея дз" in text or "гдз" in text:
            await show_gallery(update, context)
            return

        if "тарифы" in text or "тб" in text:
            logger.info("Showing tariffs.")
            await show_tariffs(update, context)
            return

        if "поддержка" in text or "пд" in text:
            await start_support_request(update, context)  # Call function to start support request
            return

        # Unknown command
        await safe_reply(update, context, "Я не понимаю эту команду.")

    except Exception as e:
        logger.error(f"Error handling text message: {e}")
        await safe_reply(update, context, "Произошла ошибка при обработке сообщения. Попробуйте позже.")


# Отправляет запрос в поддержку администратору. *
async def start_support_request( update: Update,  context: CallbackContext):
    """Starts a support request."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    await safe_reply(update, context,
                     "Пожалуйста, опишите вашу проблему или вопрос. Вы также можете прикрепить фотографию.")
    return WAIT_FOR_SUPPORT_TEXT


# Отправляет запрос в поддержку администратору. *
async def get_support_text( update: Update, context: CallbackContext):
    """Gets the support request text and sends it to the admin."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f"4444 get_support_text for user {user_id} ===============---=-=-=-")

    try:
        if update.message:
            text = update.message.text
            context.user_data["support_text"] = text
        else:
            logger.warning("Эта функция работает только с текстовыми сообщениями.")
            await safe_reply(update, context, "Эта функция работает только с текстовыми сообщениями.")
            return

        # Check for photo
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            context.user_data["support_photo"] = file_id
        else:
            context.user_data["support_photo"] = None

        await send_support_request_to_admin(update, context)
        return ACTIVE

    except Exception as e:
        logger.error(f"Error in get_support_text: {e}")
        await safe_reply(update, context, "Произошла ошибка при обработке запроса. Попробуйте позже.")
        return ConversationHandler.END  # or appropriate end state


async def send_support_request_to_admin( update: Update,  context: CallbackContext):
    """Sends the support request to the administrator."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    support_text = context.user_data.get("support_text", "No text provided")
    support_photo = context.user_data.get("support_photo")
    logger.info(
        f"Sending support request to admin from user {user_id}: Text='{support_text[:50]}...', Photo={support_photo}")

    try:
        # Construct message for the admin
        caption = f"Новый запрос в поддержку!\nUser ID: {user_id}\nТекст: {support_text}"

        # Send message to the administrator
        if support_photo:
            await context.bot.send_photo(chat_id=ADMIN_GROUP_ID, photo=support_photo, caption=caption)
        else:
            await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=caption)

        # Increase the support request counter
        cursor.execute(
            "UPDATE users SET support_requests = support_requests + 1 WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()

        await safe_reply(update, context, "Ваш запрос в поддержку отправлен. Ожидайте ответа.")

    except Exception as e:
        logger.error(f"Error sending support request to admin: {e}")
        await safe_reply(update, context, "Произошла ошибка при отправке запроса. Попробуйте позже.")


async def add_tokens( user_id: int, amount: int, reason: str, update: Update, context: CallbackContext):
    """Начисляет жетоны пользователю, включая различные бонусы."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        global bonuses_config  # Используем глобальную переменную
        bonuses_config = load_bonuses()  # Обновляем бонусы перед каждым начислением
        with conn:
            today = date.today()

            # Получаем информацию о пользователе (дата рождения, дата регистрации, количество рефералов)
            cursor.execute(
                """
                SELECT birthday, registration_date, referral_count FROM users WHERE user_id = ?
            """,
                (user_id,),
            )
            user_data = cursor.fetchone()

            if not user_data:
                logger.warning(f"Не найден пользователь {user_id} при попытке начисления бонусов.")
                await safe_reply(update, context, "Пользователь не найден.")  # reply to admin
                return  # Прерываем выполнение, если пользователь не найден

            birthday_str, registration_date_str, referral_count = user_data
            birthday = (
                datetime.strptime(birthday_str, "%Y-%m-%d").date() if birthday_str else None
            )
            registration_date = (
                datetime.strptime(registration_date_str, "%Y-%m-%d").date()
                if registration_date_str
                else None
            )
            referral_count = referral_count if referral_count else 0  # Устанавливаем значение по умолчанию, если None

            # Ежемесячный бонус
            monthly_bonus_amount = bonuses_config.get("monthly_bonus", 1)
            last_bonus_date = get_last_bonus_date(cursor, user_id)
            if not last_bonus_date or (
                    last_bonus_date.year != today.year or last_bonus_date.month != today.month
            ):
                amount += monthly_bonus_amount
                reason += f" + Ежемесячный бонус ({monthly_bonus_amount})"
                set_last_bonus_date(cursor, user_id, today)
                logger.info(f"Начислен ежемесячный бонус пользователю {user_id}")

            # Бонус на день рождения (если указана дата рождения)
            birthday_bonus_amount = bonuses_config.get("birthday_bonus", 5)
            if birthday and birthday.month == today.month and birthday.day == today.day:
                amount += birthday_bonus_amount
                reason += f" + Бонус на день рождения ({birthday_bonus_amount})"
                logger.info(f"Начислен бонус на день рождения пользователю {user_id}")

            # Бонус за реферала (если есть рефералы)
            referral_bonus_amount = bonuses_config.get("referral_bonus", 2)
            if referral_count > 0:
                amount += referral_bonus_amount * referral_count
                reason += f" + Бонус за рефералов ({referral_bonus_amount * referral_count})"
                logger.info(f"Начислен бонус за рефералов пользователю {user_id}")

            # Обновляем количество жетонов
            cursor.execute(
                """
                INSERT INTO user_tokens (user_id, tokens)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET tokens = tokens + ?
            """,
                (user_id, amount, amount),
            )

            # Логируем транзакцию
            cursor.execute(
                """
                INSERT INTO transactions (user_id, action, amount, reason)
                VALUES (?, ?, ?, ?)
            """,
                (user_id, "earn", amount, reason),
            )
        conn.commit()
        logger.info(f"Начислено {amount} жетонов пользователю {user_id} по причине: {reason}")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при начислении жетонов пользователю {user_id}: {e}")
        await safe_reply(update, context,
                         f"Произошла ошибка при начислении жетонов пользователю {user_id}: {e}")  # Alert the Admin
        conn.rollback()  # Откатываем транзакцию в случае ошибки
        raise


def get_last_bonus_date(cursor: sqlite3.Cursor, user_id: int) -> date or None:
    """Получает дату последнего начисления ежемесячного бонуса."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    cursor.execute(
        """
        SELECT last_bonus_date FROM users WHERE user_id = ?
    """,
        (user_id,),
    )
    result = cursor.fetchone()
    last_bonus_date_str = result[0] if result else None
    if last_bonus_date_str:
        return datetime.strptime(last_bonus_date_str, "%Y-%m-%d").date()
    return None


def set_last_bonus_date(cursor: sqlite3.Cursor, user_id: int, date: date):
    """Устанавливает дату последнего начисления ежемесячного бонуса."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    cursor.execute(
        """
        UPDATE users SET last_bonus_date = ? WHERE user_id = ?
    """,
        (date.strftime("%Y-%m-%d"), user_id),
    )


#  вспомогательные функции для работы с датами
def get_date(date_string: str) -> date or None:
    """Converts a date string from the format %Y-%m-%d to a date object."""

    try:
        return datetime.strptime(date_string, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def format_date(date: date) -> str:
    """Formats a date object to a string in the format %Y-%m-%d."""
    return date.strftime("%Y-%m-%d")


def get_ad_message() -> str:
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


# "Показывает текст урока по запросу."*
# async def show_lesson( update: Update, context: CallbackContext):
#     """Отправляет все материалы текущего урока, включая текст и файлы, а также напоминает о ДЗ."""
#     user_id = update.effective_user.id
#     logger.info(f"show_lesson {user_id} - Current state")
#
#     try:
#         if update.callback_query:
#             await update.callback_query.answer()
#             query = update.callback_query
#         else:
#             query = None
#
#         # Получаем active_course_id из users
#         cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
#         active_course_data = cursor.fetchone()
#
#         if not active_course_data or not active_course_data[0]:
#             await safe_reply(update, context, "Активируйте курс через кодовое слово.")
#             return
#
#         active_course_id_full = active_course_data[0]
#         # Обрезаем название курса до первого символа "_"
#         active_course_id = active_course_id_full.split("_")[0]
#         logger.info(f"active_course_id {active_course_id} +")
#
#         # Получаем progress (номер урока) из user_courses
#         cursor.execute(
#             """
#             SELECT progress
#             FROM user_courses
#             WHERE user_id = ? AND course_id = ?
#         """,
#             (user_id, active_course_id_full),
#         )
#         progress_data = cursor.fetchone()
#
#         # Если progress не найден, отдаем первый урок
#         if not progress_data:
#             lesson = 1
#             await safe_reply(update, context, "Начинаем с первого урока.")
#         else:
#             lesson = progress_data[0]
#
#         # 1. Отправляем текст урока
#         lesson_data = get_lesson_text(lesson, active_course_id)
#         if lesson_data:
#             lesson_text, parse_mode = lesson_data
#             await safe_reply(update, context, lesson_text, parse_mode=parse_mode)
#         else:
#             await safe_reply(update, context, "Текст урока не найден.")
#             return  # Exit if lesson text is not found
#
#         # 2. Send lesson files (audio, video, images)
#         lesson_files = get_lesson_files(user_id, lesson, active_course_id)
#         ad_config = load_ad_config()
#         if lesson_files:
#             total_files = len(lesson_files)  # Total number of files
#             logger.info(f"lesson_files {total_files} items ===============================")
#             for i, file_info in enumerate(lesson_files):
#                 file_path = file_info["path"]
#                 delay = file_info["delay"]
#                 file_type = file_info["type"]
#
#                 if delay > 0:
#                     messages = load_delay_messages(DELAY_MESSAGES_FILE)
#                     if random.random() < ad_config["ad_percentage"]:
#                         ad_message = get_ad_message()
#                         if ad_message:
#                             messages.append(ad_message)
#                     if messages:
#                         message = random.choice(messages)
#                         await safe_reply(update, context, message)
#                         logger.info(f"Showed delay message: {message}")
#                     logger.info(
#                         f"on {file_path} delay {delay} asincio.sleep ==============================="
#                     )
#                     await asyncio.sleep(delay)
#
#                 try:
#                     with open(file_path, "rb") as file:
#                         if file_type == "photo":
#                             await context.bot.send_photo(
#                                 chat_id=user_id, photo=file, caption=f"Фото к уроку {lesson}"
#                             )
#                         elif file_type == "audio":
#                             await context.bot.send_audio(
#                                 chat_id=user_id, audio=file, caption=f"Аудио к уроку {lesson}"
#                             )
#                         elif file_type == "video":
#                             await context.bot.send_video(
#                                 chat_id=user_id, video=file, caption=f"Видео к уроку {lesson}"
#                             )
#                         elif file_type == "document":
#                             await context.bot.send_document(
#                                 chat_id=user_id, document=file, caption=f"Документ к уроку {lesson}"
#                             )
#                         else:
#                             logger.warning(f"Неизвестный тип файла: {file_type}, {file_path}")
#
#                 except FileNotFoundError as e:
#                     logger.error(f"Файл не найден: {file_path} - {e}")
#                     await safe_reply(update, context, f"Файл {os.path.basename(file_path)} не найден.")
#                 except TelegramError as e:
#                     logger.error(f"Ошибка при отправке файла {file_path}: {e}")
#                     await safe_reply(
#                         f"Произошла ошибка при отправке файла {os.path.basename(file_path)}."
#                     )
#                 except Exception as e:
#                     logger.error(f"Неожиданная ошибка при отправке файла {file_path}: {e}")
#                     await safe_reply(
#                         update,
#                         context,
#                         f"Произошла непредвиденная ошибка при отправке файла {os.path.basename(file_path)}.",
#                     )
#             # After sending the last file, show the menu and remind about homework
#             await show_main_menu (update, context)
#             # Add homework reminder
#             homework_status = await get_homework_status_text(
#                 conn, cursor, user_id, active_course_id_full
#             )
#             await safe_reply(update, context, f"Напоминаем: {homework_status}")
#         else:
#             await safe_reply(update, context, "Файлы к этому уроку не найдены.")
#             await show_main_menu (update, context)  # Show menu even if no files are found
#             homework_status = await get_homework_status_text(
#                 conn, cursor, user_id, active_course_id_full
#             )
#             await safe_reply(update, context, f"Напоминаем: {homework_status}")
#
#     except Exception as e:  # is part of show_lesson
#         logger.error(f"Ошибка при получении материалов урока: {e}")
#         await safe_reply(update, context, "Ошибка при получении материалов урока. Попробуйте позже.")
#

def get_balance_info( user_id: int):
    """  Retrieves user's token balance, trust credit, and monthly trust increase.
    Returns:
        Tuple: (tokens, trust_credit, monthly_trust_increase)    """
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
    tokens_data = cursor.fetchone()
    tokens = tokens_data[0] if tokens_data else 0

    cursor.execute("SELECT trust_credit FROM users WHERE user_id = ?", (user_id,))
    credit_data = cursor.fetchone()
    trust_credit = credit_data[0] if credit_data else 0

    #  Set monthly_trust_increase
    monthly_trust_increase = 2

    return tokens, trust_credit, monthly_trust_increase


def can_afford(tokens: int, trust_credit: int, price_tokens: int) -> bool:
    """
    Checks if the user can afford the course, considering tokens and trust credit.

    Args:
        tokens (int): The number of tokens the user has.
        trust_credit (int): The user's trust credit.
        price_tokens (int): The price of the course in tokens.

    Returns:
        bool: True if the user can afford the course, False otherwise.
    """
    return tokens + trust_credit >= price_tokens


def deduct_payment( user_id: int, price_tokens: int) -> bool:
    """ Deducts the course price from the user's balance, utilizing trust credit if necessary.
    Args:
        conn: SQLite connection object.
        cursor: SQLite cursor object.
        user_id (int): The ID of the user.
        price_tokens (int): The price of the course in tokens.
    Returns:
        bool: True if payment was successful, False otherwise.    """

    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    tokens, trust_credit, _ = get_balance_info( user_id)
    logger.info(f"check 877 user tokens {tokens}, trustcredit {trust_credit}, to pay {price_tokens}  ==============")

    try:
        with conn:
            # Списываем токены
            if tokens >= price_tokens:
                new_tokens = tokens - price_tokens
                new_trust_credit = trust_credit
                spent_tokens = price_tokens
                spent_credit = 0
                cursor.execute(
                    "UPDATE user_tokens SET tokens = ? WHERE user_id = ?",
                    (new_tokens, user_id),
                )
                logger.info(f"883 Успешно списано {price_tokens} жетонов у пользователя {user_id}")
            elif tokens + trust_credit >= price_tokens:
                # Списываем все токены и остаток с trust_credit
                new_tokens = 0
                new_trust_credit = tokens + trust_credit - price_tokens  # Может стать отрицательным
                spent_tokens = tokens
                spent_credit = price_tokens - tokens  # Сколько было списано с кредита
                cursor.execute("UPDATE user_tokens SET tokens = 0 WHERE user_id = ?", (user_id,))  # обнуляем токены
                cursor.execute(
                    "UPDATE users SET trust_credit = ? WHERE user_id = ?",
                    (new_trust_credit, user_id),
                )  # обновляем кредит
                logger.info(
                    f"849 Успешно списаны жетоны и {spent_credit} кредита у пользователя {user_id}"
                )  # а сколько credit
            else:
                logger.warning("892 Недостаточно средств для списания.")
                return False  # Not enough funds

            # Логируем транзакцию
            cursor.execute(
                """
                INSERT INTO transactions (user_id, action, amount, reason)
                VALUES (?, ?, ?, ?)
            """,
                (user_id, "purchase", -price_tokens, f"Покупка курса (токены: {spent_tokens}, кредит: {spent_credit})"),
            )
            conn.commit()  # Apply changes to the database
        logger.info(f"897 Транзакция пользователя {user_id} успешно завершена")
        return True  # Payment successful

    except sqlite3.Error as e:
        logger.error(f"Ошибка при списании жетонов у пользователя {user_id}: {e}")
        conn.rollback()  # Rollback in case of error
        return False


def recalculate_trust( user_id: int):
    """    Recalculates the user's trust credit, applying the monthly increase, and update the trust credit in the users table.
    Args:
        conn (sqlite3.Connection): SQLite database connection.
        cursor (sqlite3.Cursor): SQLite database cursor.
        user_id (int): The ID of the user.    """
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        tokens, trust_credit, monthly_trust_increase = get_balance_info( user_id)

        # Update trust credit with monthly increase
        new_trust_credit = trust_credit + monthly_trust_increase
        cursor.execute("UPDATE users SET trust_credit = ? WHERE user_id = ?", (new_trust_credit, user_id))
        conn.commit()
        logger.info(f"Trust credit рекалькулирован для пользователя {user_id}. Новый кредит: {new_trust_credit}")

    except sqlite3.Error as e:
        logger.error(f"Ошибка при рекалькуляции trust credit для пользователя {user_id}: {e}")
        conn.rollback()  # Rollback


# TODO: 1. Implement a function to check user balance.
# TODO 2. Create a new handler (e.g., `handle_buy_course_with_tokens`).
# TODO 3. Modify your main menu and `courses.json` to include the bonus purchase option.
# TODO 4. You can extend function `recalculate_trust` to call it via schedule

#  New helper functions for homework approval
def build_admin_homework_keyboard(hw_id: int):
    """    Создает клавиатуру для админа для проверки домашних заданий.    """
    keyboard = [
        [
            InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_hw_{hw_id}"),
        ],
        [
            InlineKeyboardButton(f"✅ +1 {BRONZE_COIN}", callback_data=f"approve_hw_{hw_id}_reward_1"),
            InlineKeyboardButton(f"✅ +2 {BRONZE_COIN}", callback_data=f"approve_hw_{hw_id}_reward_2"),
            InlineKeyboardButton(f"✅ +3 {BRONZE_COIN}", callback_data=f"approve_hw_{hw_id}_reward_3")
        ],
        [
            InlineKeyboardButton(f"✅ +10 {SILVER_COIN}", callback_data=f"approve_hw_{hw_id}_reward_10"),
        ],
        [
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_hw_{hw_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def handle_homework_actions( update: Update, context: CallbackContext):
    """    Обрабатывает действия администратора с домашними заданиями (одобрение, отклонение, начисление жетонов).    """
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    query = update.callback_query
    logger.info(f"885  handle_homework_actions query: {query}")
    await query.answer()  # Acknowledge the callback
    data = query.data

    if data.startswith("approve_hw_") or data.startswith("reject_hw_"):
        parts = data.split("_")
        hw_id = int(parts[2])
        reward_amount = 0

        if len(parts) > 3 and parts[3] == "reward":  # check if we have a reward specified
            reward_amount = int(parts[4])

        #  Check approval and rejection
        if data.startswith("approve_hw_"):
            await approve_homework(conn, cursor, hw_id, reward_amount)
        elif data.startswith("reject_hw_"):
            await reject_homework(conn, cursor, hw_id)
    else:
        await safe_reply(update, context, "Unknown command.")


#18-03 15-53
@handle_telegram_errors
async def oooold_approve_homework(update: Update, context: CallbackContext, user_id_to_approve: str):
    """Обрабатывает принятие домашнего задания администратором."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        #  Get last homework id
        cursor.execute("""
               SELECT hw_id
                FROM homeworks
                WHERE user_id = ?
                ORDER BY submission_date DESC
                LIMIT 1
        """, (user_id_to_approve,))

        homework_id = cursor.fetchone()[0] if cursor.fetchone() else None
        logger.info(f"  админ принял - домашка = {homework_id}")
        if homework_id is None:
            await safe_reply(update, context, "У этого пользователя нет домашки на проверке.")
            return

        # Обновляем статус домашнего задания
        cursor.execute("UPDATE homeworks SET status = 'выполнено' WHERE id = ?", (homework_id,))
        conn.commit()

        await safe_reply(update, context, f"Домашнее задание пользователя {user_id_to_approve} принято.")

        # Отправляем уведомление пользователю
        await context.bot.send_message(chat_id=user_id_to_approve, text="Ваше домашнее задание принято администратором!")

    except sqlite3.Error as e:
        logger.error(f"Ошибка при принятии домашнего задания: {e}")
        await safe_reply(update, context, "Произошла ошибка при принятии домашнего задания. Попробуйте позже.")

#18-03 16-49 Perplexity
@handle_telegram_errors
async def ooollldddddd_approve_homework(update: Update, context: CallbackContext, user_id_to_approve: str):
     # """Обрабатывает принятие домашнего задания администратором."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
     # Get the homework id, course_id, and lesson
     cursor.execute(
         """
         SELECT hw_id, course_id, lesson
         FROM homeworks
         WHERE user_id = ?
         ORDER BY submission_time DESC
         LIMIT 1
     """,
         (user_id_to_approve,),
     )

     result = cursor.fetchone()
     if result:
         hw_id, course_id, lesson = result
         logger.info(f" 664 улов есть  {hw_id=} {course_id=} {lesson=}")
     else:
         hw_id = None

     logger.info(f"admin accepted - homework = {hw_id}")

     if hw_id is None:
         await safe_reply(update, context, "This user has no homework to approve.")
         return

     # Update the homework status
     cursor.execute(
         """
         UPDATE homeworks
         SET status = 'approved'
         WHERE hw_id = ?
     """, (hw_id,), )
     conn.commit()

     await safe_reply(update, context, f"Homework from user {user_id_to_approve} (hw_id {hw_id}, lesson {lesson}) is approved.", )

     # Notify the user about the approval
     await context.bot.send_message(
         chat_id=user_id_to_approve,
         text=f"Your homework for lesson {lesson} has been approved!",
     )
     logger.info(f"Админ одобряэ! 667 "  )

    except sqlite3.Error as e:
     logger.error(f"Error while approving homework: {e}")
     await safe_reply( update, context, "An error occurred while approving the homework. Please try again later." )



async def get_homework_rejection_history(user_id: int, course_id: str, lesson: int) -> list:
    """Получает историю отклонений домашних заданий для конкретного урока."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    try:
        cursor.execute(
            """
            SELECT rejection_date, rejection_reason
            FROM homeworks
            WHERE user_id = ? AND course_id = ? AND lesson = ? AND status = 'rejected'
            ORDER BY rejection_date DESC
            """,
            (user_id, course_id, lesson),
        )
        history = cursor.fetchall()
        return history
    except sqlite3.Error as e:
        logger.error(f"Database error while fetching rejection history for user {user_id}, course {course_id}, lesson {lesson}: {e}")
        return []

# домашка
async def approve_homework(update: Update, context: CallbackContext):
    """Обрабатывает одобрение домашнего задания администратором."""
    query = update.callback_query
    logger.info(f"\n 663  approve_homework query: {query.data}")
    await query.answer()  # Отправляем подтверждение
    logger.info(f" 6633 после    await query.answer()")

    # Разбираем callback_data
    data = query.data.split('|')  # Формат: "approve_admin_check|{user_id}|{course_id}|{lesson}"
    logger.info(f" 66333 {data=}")
    if len(data) != 4:
        await query.edit_message_text("Ошибка: некорректные данные.")
        return

    action = data[0]  # "approve_admin_check"
    user_id_to_approve = int(data[1])  # Telegram ID пользователя
    course_id = data[2]  # Course ID
    lesson = int(data[3])  # Номер урока
    logger.info(f" 666888 {action=} {user_id_to_approve=} {course_id=} {lesson=}")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        # Получаем текущее время
        approval_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Обновляем статус домашнего задания на "approved"
        cursor.execute(
            """
            UPDATE homeworks
            SET status = 'approved',
                approval_time = ?,
                final_approval_time = ?
            WHERE user_id = ? AND lesson = ? AND course_id = ? AND status = 'pending'
            """,
            (approval_time, approval_time, user_id_to_approve, lesson, course_id),
        )
        conn.commit()
        logger.info(f" 663333  {cursor.rowcount=}")
        # Проверяем успешность обновления
        if cursor.rowcount == 0:
            await query.edit_message_text("Не удалось обновить статус задания или задание уже было принято.")
            logger.info(f" 6633332221   cursor.rowcount == 0 ")
            return

            # У админа - редактируем сообщение, чтобы убрать кнопки
        await query.edit_message_text(f"Домашнее задание по уроку {lesson} пользователя {user_id_to_approve} одобрено.")

        # Уведомляем пользователя
        await context.bot.send_message(chat_id=user_id_to_approve, text=f"Домашнее задание по уроку {lesson} принято!")
        await query.edit_message_text("Домашнее задание подтверждено администратором.")

        # Начисляем коины
        bonus_amount = bonuses_config.get("homework_bonus", 3)
        add_coins(user_id_to_approve, bonus_amount)
        await context.bot.send_message(
            chat_id=user_id_to_approve,
            text=f"✅ Домашка принята! Вам начислено {bonus_amount} коинов.",
        )

        # Перерисовываем меню для пользователя

        user = await context.bot.get_chat(user_id_to_approve)  # Получаем объект пользователя
        logger.info(f" 212 перед show_main_menu {user=} {context=}")

        # Перерисовываем меню для пользователя - вызываем функцию с правильным update
        user_chat_data = {
            "id": user_id_to_approve,
            "type": "private",  # Важно!  Тип должен быть строкой
            "first_name": "Имя пользователя",  # Укажите имя пользователя
            "username": "username",  # Укажите имя пользователя
        }

        fake_update_data = {
            "update_id": int(time.time()),  # Добавляем update_id
            "message": {
                "chat": user_chat_data,
                "from": user_chat_data,
                "date": datetime.now().timestamp(),
                "chat_id": user_id_to_approve,
                "text": "Показать меню",  # Добавил текст сообщения
                "message_id": 1,
            }
        }
        fake_update = Update.de_json(fake_update_data, context.bot)
        logger.info(f" 2121212 перед show_main_menu {fake_update=} {context=}")
        await show_main_menu(fake_update, context)

    except Exception as e:
        logger.error(f"Ошибка при подтверждении домашнего задания: {e}")
        await query.edit_message_text("Произошла ошибка при подтверждении домашнего задания.")





async def reject_homework(update: Update, context: CallbackContext):
    """Обрабатывает отклонение домашнего задания."""
    query = update.callback_query
    await query.answer()

    # Разбираем callback_data
    data = query.data.split('|')  # Формат: "decline_homework|{user_id}|{course_id}|{lesson}"
    if len(data) != 4:
        await query.edit_message_text("99999675 Ошибка: некорректные данные.")
        return

    action = data[0]  # "decline_homework"
    user_id_to_reject = int(data[1])  # Telegram ID пользователя
    course_id = data[2]
    lesson = int(data[3])  # Номер урока

    context.user_data['reject_user_id'] = user_id_to_reject
    context.user_data['reject_course_id'] = course_id
    context.user_data['reject_lesson'] = lesson

    # Запрашиваем причину отклонения у администратора
    await query.edit_message_text(text="Пожалуйста, укажите причину отклонения домашнего задания:")

    # Устанавливаем таймер для автоматического выхода из состояния
    job_name = f"timeout_rejection_reason_{update.effective_user.id}"
    if context.job_queue.get_jobs(job_name):
        context.job_queue.remove_jobs(job_name)  # Удаляем старый Job если он есть
    context.job_queue.run_once(
        timeout_rejection_reason,
        WAIT_FOR_REJECTION_REASON_TIMEOUT,
        chat_id=update.effective_chat.id,  # Передаём chat_id а не user_id
        name=job_name,  # Уникальное имя для работы
        data={'user_id': update.effective_user.id},  # Передаём ID пользователя
    )
    logger.info(f"User {update.effective_user.id} transitioning to WAIT_FOR_REJECTION_REASON state")
    return WAIT_FOR_REJECTION_REASON  # Переходим в состояние ожидания причины


async def save_rejection_reason(update: Update, context: CallbackContext):
    """Сохраняет причину отклонения и отклоняет домашнее задание."""
    rejection_reason = update.message.text
    user_id_to_reject = context.user_data.get('reject_user_id')
    course_id = context.user_data.get('reject_course_id')
    lesson = context.user_data.get('reject_lesson')

    if not user_id_to_reject or not course_id or not lesson:
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте отклонить домашнее задание снова.")
        logger.info(f"User {user_id_to_reject=} transitioning to  ConversationHandler.END state")
        return ConversationHandler.END

    # Отменяем таймер
    job_name = f"timeout_rejection_reason_{update.effective_user.id}"
    current_jobs = context.job_queue.get_jobs()

    for job in current_jobs:
        if job.name == job_name:
            job.schedule_removal()  # Удаляем Job
            break

    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        # Обновляем статус домашнего задания на "rejected" и сохраняем причину отклонения
        cursor.execute(
            """
            UPDATE homeworks
            SET status = 'rejected',
                rejection_reason = ?
            WHERE user_id = ? AND lesson = ? AND course_id = ?
            """,
            (rejection_reason, user_id_to_reject, lesson, course_id),
        )
        conn.commit()

        # Проверяем успешность обновления
        if cursor.rowcount == 0:
            await safe_reply(update, context, "Не удалось отклонить задание или задание уже было обработано.")
            logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
            return ConversationHandler.END

        # Уведомляем пользователя
        await context.bot.send_message(chat_id=user_id_to_reject, text=f"Домашнее задание по уроку {lesson} отклонено: {rejection_reason}")
        await safe_reply(update, context, text="Домашнее задание отклонено администратором.")

    except Exception as e:
        logger.error(f"1112 Ошибка при отклонении домашнего задания: {e}")
        await safe_reply(update, context, "Произошла ошибка при отклонении домашнего задания.")
    finally:
        if conn:
            conn.close()
    logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
    return ConversationHandler.END





    # Отправляем сообщение админу о том, что время ожидания истекло
    await context.bot.send_message(
        chat_id=chat_id,
        text="Время ожидания причины отклонения истекло. Вы возвращены в обычный режим.",
    )

    # Возвращаем админа в состояние ACTIVE
    context.user_data.clear()  # Очищаем данные пользователя

    return ConversationHandler.END  # Завершаем текущий ConversationHandler


async def timeout_rejection_reason(context: CallbackContext):
    """Автоматически возвращает пользователя в состояние ACTIVE после таймаута."""
    job = context.job
    chat_id = job.chat_id
    user_id = job.data['user_id']  # Вытаскиваем user_id
    logger.info(f"33221100 Таймаут ожидания причины отклонения для user_id={user_id}")

    # Отправляем сообщение админу о том, что время ожидания истекло
    await context.bot.send_message(
        chat_id=chat_id,
        text="Время ожидания причины отклонения истекло. Вы возвращены в обычный режим.",
    )

    # Возвращаем админа в состояние ACTIVE
    context.user_data.clear()  # Очищаем данные пользователя

    # Нужно создать новый Update объект для возврата в ACTIVE
    # Создаем фейковые данные для Update
    fake_data = {
        "message": {
            "chat": {
                "id": chat_id,  # Важно использовать chat_id админа
                "type": "private",
            },
            "text": "/start",  # Можно использовать команду, которая переводит в ACTIVE
        }
    }
    try:
        new_update = Update.de_json(fake_data, context.bot)
        logger.info( f"!!! меню после таймаута {new_update=} {context=}")
        await show_main_menu(new_update, context)  # Возвращаемся в главное меню
    except Exception as e:
        logger.error(f"Error while generating Update or returning: {e}")
    return ConversationHandler.END  # Завершаем текущий ConversationHandler


#18-03 16-50 Perplexity
@handle_telegram_errors
async def decline_homework(update: Update, context: CallbackContext, user_id_to_decline: str):
    """Handles homework declining by an admin."""
    logger.info(f" 671  decline_homework update: {update}")
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        #  Get last homework id
        cursor.execute("""
               SELECT hw_id
                FROM homeworks
                WHERE user_id = ?
                ORDER BY submission_time DESC
                LIMIT 1
        """, (user_id_to_decline,))
        result = cursor.fetchone()
        homework_id = result[0] if result else None
        logger.info(f"558  админ реджектнул - домашка = {homework_id}")
        if homework_id is None:
            await safe_reply(update, context, "У этого пользователя нет домашки на реджект.")
            return

        # Обновляем статус домашнего задания
        cursor.execute("UPDATE homeworks SET status = 'отклонено' WHERE hw_id = ?", (homework_id,))
        conn.commit()

        await safe_reply(update, context, f"Домашнее задание пользователя {user_id_to_decline} реджектнуто.")

        # Отправляем уведомление пользователю
        await context.bot.send_message(chat_id=user_id_to_decline, text="Ваше домашнее задание реджектнуто администратором!")

    except sqlite3.Error as e:
        logger.error(f"Ошибка при реджекте домашнего задания: {e}")
        await safe_reply(update, context, "Произошла ошибка при реджекте домашнего задания. Попробуйте позже.")



# TODO: 1. Implement a function to check user balance.
# TODO: 2. Create a new handler (e.g., `handle_buy_course_with_tokens`).
# TODO: 3. Modify your main menu and `courses.json` to include the bonus purchase option.
# TODO: 4. You can extend function `recalculate_trust` to call it via schedule

@handle_telegram_errors
def spend_tokens( user_id: int, amount: int, reason: str):
    """Списывает жетоны у пользователя."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    try:
        with conn:
            # Проверяем баланс
            cursor = conn.cursor()
            cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
            balance_data = cursor.fetchone()
            if not balance_data or balance_data[0] < amount:
                raise ValueError("Недостаточно жетонов")

            # Списываем жетоны
            cursor.execute(
                "UPDATE user_tokens SET tokens = tokens - ? WHERE user_id = ?",
                (amount, user_id),
            )

            # Логируем транзакцию
            cursor.execute(
                """
                INSERT INTO transactions (user_id, action, amount, reason)
                VALUES (?, ?, ?, ?)
            """,
                (user_id, "spend", amount, reason),
            )
        logger.info(f"Списано {amount} жетонов у пользователя {user_id} по причине: {reason}")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при списании жетонов у пользователя {user_id}: {e}")
        raise

@handle_telegram_errors
def get_token_balance( user_id: int):
    """Возвращает текущий баланс жетонов пользователя."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
        balance_data = cursor.fetchone()
        return balance_data[0] if balance_data else 0
    except sqlite3.Error as e:
        logger.error(f"Ошибка при получении баланса пользователя {user_id}: {e}")
        return 0

@handle_telegram_errors
async def show_token_balance( update: Update, context: CallbackContext):
    """Показывает баланс жетонов пользователя."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    user_id = update.effective_user.id
    balance = get_token_balance(user_id)
    await update.message.reply_text(f"У вас {balance} АнтКоинов.")

@handle_telegram_errors
async def buy_lootbox( update: Update, context: CallbackContext):
    """Обрабатывает покупку лутбокса."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id

    try:
        # Проверяем тип лутбокса
        box_type = context.args[0].lower()  # Например, 'light' или 'full'

        # Стоимость лутбокса
        cost = 1 if box_type == "light" else 3

        # Списываем жетоны
        spend_tokens(user_id, cost, f"purchase_{box_type}_lootbox")

        # Получаем награду
        reward = roll_lootbox(conn, box_type)

        # Отправляем сообщение с результатом
        await update.message.reply_text(f"Вы открыли лутбокс '{box_type}' и получили: {reward}")
        logger.info(f"Пользователь {user_id} купил лутбокс '{box_type}' и получил: {reward}")

    except IndexError:
        await update.message.reply_text("Использование: /buy_lootbox [light/full]")
    except ValueError as e:
        await update.message.reply_text(str(e))
    except sqlite3.Error as e:
        logger.error(f"Ошибка при покупке лутбокса пользователем {user_id}: {e}")
        await update.message.reply_text("Произошла ошибка при покупке лутбокса. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Необработанная ошибка при покупке лутбокса пользователем {user_id}: {e}")
        await update.message.reply_text("Произошла необработанная ошибка. Попробуйте позже.")

@handle_telegram_errors
def roll_lootbox(conn: sqlite3.Connection, box_type: str):
    """Определяет награду из лутбокса."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT reward, probability FROM lootboxes WHERE box_type = ?", (box_type,))
        rewards = cursor.fetchall()

        # Генерируем случайное число
        rand = random.random()

        cumulative_probability = 0.0
        for reward, probability in rewards:
            cumulative_probability += probability
            if rand <= cumulative_probability:
                logger.info(f"Выпала награда {reward} из лутбокса {box_type}")
                return reward
        return "ничего"  # Если ничего не выпало
    except sqlite3.Error as e:
        logger.error(f"Ошибка при определении награды из лутбокса {box_type}: {e}")
        return "ошибка"

@handle_telegram_errors
async def reminders( update: Update, context: CallbackContext):
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    cursor.execute(
        "SELECT morning_notification, evening_notification FROM user_settings WHERE user_id = ?",
        (user_id,),
    )
    settings = cursor.fetchone()
    if not settings:
        cursor.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
        conn.commit()
        settings = (None, None)

    morning, evening = settings
    text = "⏰ Настройка напоминаний:\n"
    text += f"🌅 Утреннее напоминание: {morning or 'не установлено'}\n"
    text += f"🌇 Вечернее напоминание: {evening or 'не установлено'}\n\n"
    text += "Чтобы установить или изменить время, используйте команды:\n"
    text += "/set_morning HH:MM — установить утреннее напоминание\n"
    text += "/set_evening HH:MM — установить вечернее напоминание\n"
    text += "/disable_reminders — отключить все напоминания"

    await update.message.reply_text(text)


@handle_telegram_errors
async def set_morning( update: Update, context: CallbackContext):
    """Устанавливает утреннее напоминание."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    try:
        time1 = context.args[0]
        if not re.match(r"^\d{2}:\d{2}$", time1):
            raise ValueError
        cursor.execute(
            """
            UPDATE user_settings
            SET morning_notification = ?
            WHERE user_id = ?
        """,
            (time1, user_id),
        )
        conn.commit()
        # Проверяем, откуда пришел запрос (сообщение или callback query)
        if update.message:
            await update.message.reply_text(f"Утреннее напоминание установлено на {time1}.")
        elif update.callback_query:
            await update.callback_query.message.reply_text(f"Утреннее напоминание установлено на {time1}.")
        else:
            logger.warning("Не удалось определить тип update.")

    except (IndexError, ValueError):
        if update.message:
            await update.message.reply_text("Неверный формат времени. Используйте формат HH:MM.")
        elif update.callback_query:
            await update.callback_query.message.reply_text("Неверный формат времени. Используйте формат HH:MM.")
        else:
            logger.warning("Не удалось определить тип update.")


async def disable_reminders( update: Update, context: CallbackContext):
    """Отключает все напоминания."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user_id = update.effective_user.id
    logger.info(f"disable_reminders ")
    cursor.execute(
        """
        UPDATE user_settings
        SET morning_notification = NULL, evening_notification = NULL
        WHERE user_id = ?
        """,
        (user_id,),
    )
    conn.commit()
    # Проверяем, откуда пришел запрос (сообщение или callback query)
    if update.message:
        await update.message.reply_text("Напоминания отключены.")
    elif update.callback_query:
        await update.callback_query.message.reply_text("Напоминания отключены.")
    else:
        logger.warning("Не удалось определить тип update.")


async def send_reminders( context: CallbackContext):
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    now = datetime.now().strftime("%H:%M")
    logger.info(f" send_reminders {now} ")
    cursor.execute("SELECT user_id, morning_notification, evening_notification FROM user_settings")
    for user_id, morning, evening in cursor.fetchall():
        if morning and now == morning:
            await context.bot.send_message(
                chat_id=user_id,
                text="🌅 Доброе утро! Посмотрите материалы курса.",
            )
        if evening and now == evening:
            await context.bot.send_message(
                chat_id=user_id,
                text="🌇 Добрый вечер! Выполните домашнее задание.",
            )


@handle_telegram_errors
def add_user_to_scheduler( user_id: int, time2: datetime,  context: CallbackContext, scheduler: AsyncIOScheduler):
    """Add user to send_lesson_by_timer with specific time."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    logger.info(f" added id {user_id} time {time2.hour}-------------<")
    # Schedule the daily message
    try:
        scheduler.add_job(
            send_lesson_by_timer,
            trigger="cron",
            hour=time2.hour,
            minute=time2.minute,
            start_date=datetime.now(),  # Начало выполнения задачи
            kwargs={"user_id": user_id, "context": context},
            id=f"lesson_{user_id}",  # Уникальный ID для задачи
        )
    except Exception as e:
        logger.error(f"send_lesson_by_timer failed. {e}------------<<")



async def stats( update: Update, context: CallbackContext):
    # Активные пользователи за последние 3 дня
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    active_users = cursor.execute(
        """
        SELECT COUNT(DISTINCT user_id) 
        FROM homeworks 
        WHERE submission_time >= DATETIME('now', '-3 days')
    """
    ).fetchone()[0]
    logger.info(f"statsactive_users={active_users} uuuserzz ")
    # Домашние задания за последние сутки
    recent_homeworks = cursor.execute(
        """
        SELECT COUNT(*) 
        FROM homeworks 
        WHERE submission_time >= DATETIME('now', '-1 day')
    """
    ).fetchone()[0]

    # Общее количество пользователей
    total_users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    text = "📊 Статистика:\n"
    text += f"👥 Активных пользователей за последние 3 дня: {active_users}\n"
    text += f"📚 Домашних заданий за последние сутки: {recent_homeworks}\n"
    text += f"👤 Пользователей всего: {total_users}"

    await update.message.reply_text(text)


async def set_evening( update: Update, context: CallbackContext):
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    user_id = update.effective_user.id
    try:
        time = context.args[0]
        if not re.match(r"^\d{2}:\d{2}$", time):
            raise ValueError
        cursor.execute(
            "UPDATE user_settings SET evening_notification = ? WHERE user_id = ?",
            (time, user_id),
        )
        conn.commit()
        await update.message.reply_text(f"🌇 Вечернее напоминание установлено на {time}.")
    except (IndexError, ValueError):
        await update.message.reply_text("Неверный формат времени. Используйте формат HH:MM.")


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


@handle_telegram_errors
async def send_file(user_id: int, file_path: str, file_type: str, delay: int, delay_message: str, context: CallbackContext):
    """Отправляет файл пользователю с задержкой и сообщением."""
    logger.info(f"825 send_file {user_id=} {file_path=} {file_type=} {delay=} {delay_message=}")
    if delay > 0:
        logger.info(f"Ожидание {delay} секунд перед отправкой файла {file_path}. Сообщение: {delay_message}")
        await asyncio.sleep(delay)

    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Файл не найден: {file_path}")

        # Send content as text
        if file_type == "text":
            with open(file_path, "r", encoding="utf-8") as file:
                lesson_text = file.read()
            await context.bot.send_message(chat_id=user_id, text=lesson_text, parse_mode=ParseMode.MARKDOWN)  # Send as text
        # Send image
        elif file_type == "photo":
            with open(file_path, 'rb') as file:
                await context.bot.send_photo(chat_id=user_id, photo=file)  # Send as photo
        # Send video
        elif file_type == "video":
            with open(file_path, 'rb') as file:
                await context.bot.send_video(chat_id=user_id, video=file)  # Send as video
        # Send document as fallback
        else:
            with open(file_path, 'rb') as file:
                await context.bot.send_document(chat_id=user_id, document=file)  # Send as document
    except FileNotFoundError:
        logger.error(f"Файл не найден: {file_path}")
        await context.bot.send_message(chat_id=user_id, text="Файл не найден. Пожалуйста, обратитесь в поддержку.")
    except Exception as e:
        logger.error(f"Ошибка при отправке файла {file_path}: {e}")
        await context.bot.send_message(chat_id=user_id, text="Произошла ошибка при отправке файла. Пожалуйста, обратитесь в поддержку.")

# Добавляем новую функцию для отправки нового файла и сохранения file_id в базе данных
async def send_as_new_file(bot, chat_id: int, course_id: str, lesson_number: int, file_path: str, file_name: str):
    """Отправляет файл как новый, получает его file_id и сохраняет в базе данных."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    logger.info(f"267 send_as_new_file Начинаем отправку файла: {file_name} ({file_path}) в чат {chat_id}")
    try:
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
                msg = await bot.send_photo(chat_id=chat_id, photo=file)
            elif mime_type.startswith('video/'):
                logger.info(f"Отправляем файл как видео.")
                msg = await bot.send_video(chat_id=chat_id, video=file)
            elif mime_type.startswith('audio/'):
                logger.info(f"Отправляем файл как аудио.")
                msg = await bot.send_audio(chat_id=chat_id, audio=file)
            else:
                logger.info(f"Отправляем файл как документ.")
                msg = await bot.send_document(chat_id=chat_id, document=file, filename=file_name)
        # Сохраняем file_id в базу данных
        file_id = msg.document.file_id if msg.document else msg.photo[
            -1].file_id if msg.photo else msg.video.file_id if msg.video else msg.audio.file_id if msg.audio else None  # Берем нужный file_id
        if file_id:
            logger.info(f"Получен file_id: {file_id}")
            cursor.execute(
                """
                UPDATE lessons
                SET video_file_id = ?
                WHERE course_id = ? AND lesson = ?
                """,
                (file_id, course_id, lesson_number),
            )
            conn.commit()
            logger.info(f"File_id {file_id} сохранен в базе данных для файла {file_name}.")
        else:
            logger.error(f"Не удалось получить file_id для {file_name}!")

    except Exception as e:
        # Обрабатываем любые исключения, которые могут возникнуть
        logger.exception(
            f"Ошибка при отправке файла {file_name} в чат {chat_id}: {e}")  # Используем logger.exception для трассировки стека
        await bot.send_message(
            chat_id=chat_id,
            text="Произошла ошибка при отправке файла. Пожалуйста, попробуйте позже или обратитесь в поддержку."
        )


# 25-03 решили заапдейтить
async def old_send_file(bot, chat_id, file_path, file_name):
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
    logger.info(f"224 send_file Начинаем отправку файла: {file_name} ({file_path}) в чат {chat_id}")

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

# это если с жсона слать, но постараюсь скомбинировать с send_file просто
async def send_lesson_content(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_data):
    chat_id = update.effective_chat.id
    logger.info(f" 228  send_lesson_content Начинаем отправку файла: {lesson_data=}")
    for item in lesson_data['content']:
        if item['type'] == 'video':
            await context.bot.send_video(chat_id=chat_id, video=item['file_id'], caption=item['caption'])
        elif item['type'] == 'photo':
            await context.bot.send_photo(chat_id=chat_id, photo=item['file_id'], caption=item['caption'])



# Qwen 15 марта Замена get_lesson_after_code
async def get_lesson_after_code(update: Update, context: CallbackContext, course_type: str):
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    user = update.effective_user
    cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user.id,))
    active_course_data = cursor.fetchone()

    if not active_course_data or not active_course_data[0]:
        await update.message.reply_text("Пожалуйста, активируйте курс.")
        return

    active_course_id_full = active_course_data[0]
    cursor.execute(
        """
        SELECT progress
        FROM user_courses
        WHERE user_id = ? AND course_id = ?
    """,
        (user.id, active_course_id_full),
    )
    progress_data = cursor.fetchone()

    lesson_number = 1 if not progress_data else progress_data[0]
    await process_lesson(user.id, lesson_number, active_course_id_full.split("_")[0], context)


#  Qwen 15  Замена send_lesson_by_timer
async def send_lesson_by_timer( user_id: int, context: CallbackContext):
    """Send lesson to users by timer."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    logger.info(f"Sending lesson to user {user_id} at {datetime.now()}")

    # Get active_course_id and progress
    cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
    active_course_data = cursor.fetchone()

    if not active_course_data or not active_course_data[0]:
        await context.bot.send_message(chat_id=user_id, text="Пожалуйста, активируйте курс.")
        return

    active_course_id_full = active_course_data[0]
    cursor.execute(
        """
        SELECT progress
        FROM user_courses
        WHERE user_id = ? AND course_id = ?
    """,
        (user_id, active_course_id_full),
    )
    progress_data = cursor.fetchone()

    if not progress_data:
        await context.bot.send_message(chat_id=user_id, text="Не найден прогресс курса.")
        return

    lesson = progress_data[0]

    # Update lesson_sent_time in the database
    lesson_sent_time = datetime.now()
    cursor.execute(
        """
        INSERT INTO homeworks (user_id, course_id, lesson, lesson_sent_time)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, course_id, lesson) DO UPDATE SET lesson_sent_time = excluded.lesson_sent_time
    """,
        (user_id, active_course_id_full, lesson, lesson_sent_time),
    )
    conn.commit()

    # Process the lesson
    await process_lesson(user_id, lesson, active_course_id_full.split("_")[0], context)


async def show_homework( update: Update, context: CallbackContext):
    """Показывает галерею ДЗ по выбранному уроку."""
    try:
        query = update.callback_query
        await query.answer()
        lesson_number = query.data.split("_")[1]
        await safe_reply(update, context, f"Здесь будет галерея ДЗ по {lesson_number} уроку")

    except Exception as e:
        logger.error(f"Ошибка при показе домашнего задания: {e}")
        await safe_reply(update, context, "Произошла ошибка при обработке запроса.")


# Функция для получения предварительных материалов строго ненадо
def get_preliminary_materials(course_id, lesson):
    """
    Возвращает список всех предварительных материалов для урока.
    """
    lesson_dir = f"courses/{course_id}/"
    materials = []
    logger.info(f"553 get_preliminary_materials {lesson_dir=} ")
    for filename in os.listdir(lesson_dir):
        if filename.startswith(f"lesson{lesson}_p") and os.path.isfile(os.path.join(lesson_dir, filename)):
            materials.append(filename)
    materials.sort()  # Сортируем по порядку (p1, p2, ...)
    return materials


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
                        "Перейти в чат болтать", url="https://t.me/+-KUbE8NM7t40ZDky"
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


async def old_send_preliminary_material( update: Update,  context: CallbackContext):
    """Sends preliminary materials for the next lesson."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    user_id = update.effective_user.id

    try:
        if update.callback_query:
            query = update.callback_query
            await query.answer()
        else:
            query = None
            logger.warning("send_preliminary_material: This function should be called from a callback query.")
            await safe_reply(update, context, "This function can only be used via button press.")
            return

        # Get active_course_id from users
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await safe_reply(update, context, "Активируйте курс через кодовое слово.")
            return

        active_course_id_full = active_course_data[0]
        # Trim the course name to the first "_"
        active_course_id = active_course_id_full.split("_")[0]

        # Get progress (lesson number) from user_courses
        cursor.execute(
            """
            SELECT progress
            FROM user_courses
            WHERE user_id = ? AND course_id = ?
        """,
            (user_id, active_course_id_full),
        )
        progress_data = cursor.fetchone()

        if not progress_data:
            await safe_reply(update, context, "Не найден прогресс курса. Пожалуйста, начните курс сначала.")
            return

        lesson = progress_data[0]
        next_lesson = lesson + 1

        # Get the list of preliminary materials
        materials = get_preliminary_materials(active_course_id, next_lesson)

        if not materials:
            await safe_reply(update, context, "Предварительные материалы для следующего урока отсутствуют.")
            return

        # Send materials
        for material_file in materials:
            material_path = f"courses/{active_course_id}/{material_file}"

            # Determine the file type
            try:
                with open(material_path, "rb") as file:
                    if material_file.endswith((".jpg", ".jpeg", ".png", ".gif")):
                        await context.bot.send_photo(chat_id=user_id, photo=file)
                    elif material_file.endswith((".mp4", ".avi", ".mov")):
                        await context.bot.send_video(chat_id=user_id, video=file)
                    elif material_file.endswith((".mp3", ".wav", ".ogg")):
                        await context.bot.send_audio(chat_id=user_id, audio=file)
                    else:
                        await context.bot.send_document(chat_id=user_id, document=file)
            except FileNotFoundError:
                logger.error(f"Файл не найден: {material_path}")
                await safe_reply(update, context, f"Файл {material_file} не найден.")
            except TelegramError as e:
                logger.error(f"Ошибка при отправке файла {material_file}: {e}")
                await safe_reply(update, context, f"Произошла ошибка при отправке файла {material_file}.")
            except Exception as e:
                logger.error(f"Неожиданная ошибка при отправке файла {material_file}: {e}")
                await safe_reply(update, context,
                                 f"Произошла непредвиденная ошибка при отправке файла {material_file}.")

        await safe_reply(update, context, "Все предварительные материалы для следующего урока отправлены.")

    except Exception as e:
        logger.error(f"Ошибка при отправке предварительных материалов: {e}")
        await safe_reply(update, context, "Произошла ошибка при отправке предварительных материалов. Попробуйте позже.")


# Функция для добавления кнопки "Получить предварительные материалы"
async def add_preliminary_button( user_id, course_type):
    # Извлекаем префикс курса (main/auxiliary)
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    course_prefix = course_type.split("_")[0]  # Получаем "main" или "auxiliary"

    # Получаем текущий урок
    cursor.execute(
        f"SELECT {course_prefix}_current_lesson FROM users WHERE user_id = ?",
        (user_id,),
    )
    current_lesson = cursor.fetchone()[0]
    next_lesson = current_lesson + 1

    # Получаем название курса
    cursor.execute(f"SELECT {course_prefix}_course FROM users WHERE user_id = ?", (user_id,))
    course = cursor.fetchone()[0]

    materials = get_preliminary_materials(course, next_lesson)
    if not materials:
        return None

    cursor.execute("SELECT preliminary_material_index FROM users WHERE user_id = ?", (user_id,))
    material_index = cursor.fetchone()[0] or 0

    remaining_materials = len(materials) - material_index
    if remaining_materials > 0:
        return InlineKeyboardButton(
            f"Получить предварительные материалы к след. уроку({remaining_materials} осталось)",
            callback_data=f"preliminary_{course_type}",
        )
    return None


def get_average_homework_time( user_id):
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    cursor.execute(
        """
        SELECT AVG((JULIANDAY(approval_time) - JULIANDAY(submission_time)) * 24 * 60 * 60)
        FROM homeworks
        WHERE user_id = ? AND status = 'approved'
    """,
        (user_id,),
    )
    result = cursor.fetchone()[0]

    logger.info(f"{result} - get_average_homework_time")

    if result:
        average_time_seconds = int(result)
        hours, remainder = divmod(average_time_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours} часов {minutes} минут"
    else:
        return "Нет данных"


async def handle_admin_approval( update: Update,   context: CallbackContext):
    """Handles admin approval actions (approve or reject) and requests a comment."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    try:
        if update.callback_query:
            query = update.callback_query
            await query.answer()  # Acknowledge the callback
        else:
            logger.warning("handle_admin_approval: This function should be called from a callback query.")
            await safe_reply(update, context, "This function can only be used via button press.")
            return

        data = query.data.split("_")
        action = data[1]
        hw_id = data[2]

        if action == "approve":
            # Request a comment from the admin
            await safe_reply(update, context, "Введите комментарий к домашней работе:")
            context.user_data["awaiting_comment"] = hw_id
            context.user_data["approval_status"] = "approved"  # Save the status
        elif action == "reject":
            # Request a comment from the admin
            await safe_reply(update, context, "Введите комментарий к домашней работе:")
            context.user_data["awaiting_comment"] = hw_id
            context.user_data["approval_status"] = "rejected"  # Save the status
        else:
            await safe_reply(update, context, "Неизвестное действие.")

    except Exception as e:
        logger.error(f"handle_admin_approval: An error occurred: {e}")
        await safe_reply(update, context, "Произошла ошибка при обработке запроса.")


# Загружает тарифы из файла.*
def load_tariffs():
    """Загружает тарифы из файла."""

    logger.info(f"load_tariffs  333333 2")
    try:
        with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
            k = json.load(f)
            logger.info(f"load_tariffs  k={k} 333333 3")
            return k
    except FileNotFoundError:
        logger.error(f"Файл {TARIFFS_FILE} не найден.")
        return []
    except json.JSONDecodeError:
        logger.error(f"Ошибка декодирования JSON в файле {TARIFFS_FILE}.")
        return []


# Обрабатывает выбор тарифа. *
async def tariff_callback( update: Update, context: CallbackContext):
    """Обрабатывает выбор тарифа."""
    query = update.callback_query
    await query.answer()
    tariff_id = query.data.split("_")[1]
    tariffs = load_tariffs()

    logger.info(f"tariff_callback  555555 666 tariffS={tariffs} 333333 ------ >")

    tariff = next((t for t in tariffs if t["id"] == tariff_id), None)

    if not tariff:
        await query.message.reply_text("Акция не найдена.")
        return

    context.user_data["tariff"] = tariff  # Сохраняем данные о тарифе

    # Добавляем кнопки "Купить" и "В подарок"
    keyboard = [
        [InlineKeyboardButton("Купить", callback_data=f"buy_{tariff_id}")],
        [InlineKeyboardButton("В подарок", callback_data=f"gift_{tariff_id}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if tariff["type"] == "payment":
        text = f"<b>{tariff['title']}</b>\n\n{tariff['description']}\n\nЦена: {tariff['price']} рублей"  # Укажите валюту, если нужно
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif tariff["type"] == "discount":
        text = f"<b>{tariff['title']}</b>\n\n{tariff['description']}"
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def buy_tariff( update: Update, context: CallbackContext):
    """Handles the "Buy" button press."""
    user_id = update.effective_user.id

    try:
        if update.callback_query:
            query = update.callback_query
            await query.answer()  # Acknowledge the callback
        else:
            logger.warning("buy_tariff: This function should be called from a callback query.")
            await safe_reply(update, context, "Эта функция работает только через CallbackQuery.")
            return

        tariff = context.user_data.get("tariff")
        if not tariff:
            await safe_reply(update, context, "Тариф не найден. Пожалуйста, выберите тариф заново.")
            logger.warning(f"buy_tariff: Tariff not found in user_data for user {user_id}.")
            return

        logger.info(f"buy_tariff: User {user_id} attempting to buy tariff {tariff['id']}")
        context.user_data["tariff_id"] = tariff["id"]  # Save tariff_id

        if tariff["type"] == "discount":
            await safe_reply(update, context,
                             "Для получения скидки отправьте селфи и короткое описание, почему вы хотите получить эту скидку:"
                             )
            logger.info(f"User {update.effective_user.id} transitioning to  WAIT_FOR_SELFIE state")
            return WAIT_FOR_SELFIE

        # Payment instructions
        text = f"Для приобретения акции, пожалуйста, переведите {tariff['price']} рублей на номер [номер] и загрузите чек сюда в этот диалог."  # Replace [amount] and [number]
        await safe_reply(update, context, text)
        await safe_reply(update, context,
                         "Пожалуйста, поделитесь своим номером телефона:",
                         reply_markup=ReplyKeyboardMarkup(
                             [[KeyboardButton("Поделиться номером телефона", request_contact=True)]],
                             resize_keyboard=True,
                             one_time_keyboard=True,
                         ),
                         )
        logger.info(f"User {update.effective_user.id} transitioning to  WAIT_FOR_PHONE_NUMBER state")
        return WAIT_FOR_PHONE_NUMBER

    except Exception as e:
        logger.error(f"buy_tariff: An error occurred for user {user_id}: {e}")
        await safe_reply(update, context, "Произошла ошибка при обработке запроса. Попробуйте позже.")


async def gift_tariff( update: Update, context: CallbackContext):
    """Handles the "Gift" button press."""
    user_id = update.effective_user.id
    try:
        if update.callback_query:
            query = update.callback_query
            await query.answer()
        else:
            logger.warning("gift_tariff: This function should be called from a callback query.")
            await safe_reply(update, context, "Эта функция работает только через CallbackQuery.")
            logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
            return ConversationHandler.END

        tariff = context.user_data.get("tariff")
        if not tariff:
            await safe_reply(update, context, "Тариф не найден. Пожалуйста, выберите тариф заново.")
            logger.warning(f"gift_tariff: Tariff not found in user_data for user {user_id}.")
            logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
            return ConversationHandler.END  # End conversation

        logger.info(f"gift_tariff: User {user_id} attempting to gift tariff {tariff['id']}")

        if tariff["type"] == "discount":
            await safe_reply(update, context, "Подарочные сертификаты со скидками недоступны. Выберите другой тариф.")
            logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
            return ConversationHandler.END

        context.user_data["tariff_id"] = tariff["id"]  # Save tariff_id

        await safe_reply(update, context, "Введите user ID получателя подарка:")
        logger.info(f"User {update.effective_user.id} transitioning to  WAIT_FOR_GIFT_USER_ID state")
        return WAIT_FOR_GIFT_USER_ID

    except Exception as e:
        logger.error(f"gift_tariff: An error occurred for user {user_id}: {e}")
        await safe_reply(update, context, "Произошла ошибка при обработке запроса. Попробуйте позже.")
        logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
        return ConversationHandler.END


async def add_purchased_course( user_id: int, tariff_id: str,  context: CallbackContext):
    """Adds a purchased course to the user's profile."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    update = context.update
    logger.info(f"add_purchased_course: User {user_id} attempting to add course {tariff_id}")
    try:
# Check if the course already exists for the user
        cursor.execute(
            """
            SELECT * FROM user_courses
            WHERE user_id = ? AND course_id = ?
        """,
            (user_id, tariff_id),
        )
        existing_course = cursor.fetchone()

        if existing_course:
            await safe_reply(update, context, "Этот курс уже есть в вашем профиле.")
            logger.info(f"add_purchased_course: Course {tariff_id} already exists for user {user_id}.")
            return  # Course already exists

        # Load tariff data from tariffs.json
        tariffs = load_tariffs()
        tariff = next((t for t in tariffs if t["id"] == tariff_id), None)

        if not tariff:
            logger.error(f"add_purchased_course: Tariff with id {tariff_id} not found in tariffs.json")
            await safe_reply(update, context, "Произошла ошибка при добавлении курса. Попробуйте позже.")
            return  # Tariff not found

        course_type = tariff.get("course_type", "main")  # Get course type from tariff
        tariff_name = tariff_id.split("_")[1] if len(tariff_id.split("_")) > 1 else "default"

        # Add the course to user_courses
        cursor.execute(
            """
            INSERT INTO user_courses (user_id, course_id, course_type, progress, tariff)
            VALUES (?, ?, ?, ?, ?)
        """,
            (user_id, tariff_id, course_type, 1, tariff_name),
        )  # Start with progress = 1
        conn.commit()

        # Update active_course_id in users
        cursor.execute(
            """
            UPDATE users
            SET active_course_id = ?
            WHERE user_id = ?
        """,
            (tariff_id, user_id),
        )
        conn.commit()

        logger.info(f"add_purchased_course: Course {tariff_id} added to user {user_id}")
        await safe_reply(update, context, "Новый курс был добавлен вам в профиль.")

    except Exception as e:
        logger.error(f"add_purchased_course: An error occurred for user {user_id}: {e}")
        await safe_reply(update, context, "Произошла ошибка при добавлении курса. Попробуйте позже.")


async def show_stats( update: Update, context: CallbackContext):
    """Показывает статистику для администратора."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    admin_id = update.effective_user.id

    # Check if the user is an admin
    if str(admin_id) not in ADMIN_IDS:
        await safe_reply(update, context, "У вас нет прав для выполнения этой команды.")
        return

    try:
        # Получаем общее количество пользователей
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        # Получаем количество активных курсов
        cursor.execute("SELECT COUNT(DISTINCT course_id) FROM user_courses")
        total_courses = cursor.fetchone()[0]

        # Формируем сообщение со статистикой
        stats_message = (
            f"📊 Статистика:\n\n"
            f"👥 Пользователей: {total_users}\n"
            f"📚 Активных курсов: {total_courses}"
        )

        # Отправляем статистику администратору
        await safe_reply(update, context, stats_message)

    except Exception as e:
        # Логируем и сообщаем об ошибке
        logger.error(f"Ошибка при получении статистики: {e}")
        await safe_reply(update, context, "Произошла ошибка при получении статистики.")


# Отклоняет скидку администратором.*
async def admin_approve_discount( update: Update, context: CallbackContext):
    """Подтверждает скидку администратором."""
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    user_id = int(data[3])
    tariff_id = data[4]
    try:
        # Добавляем логику уведомления пользователя
        await context.bot.send_message(user_id, f"🎉 Ваша заявка на скидку для тарифа {tariff_id} одобрена!")
        await query.message.reply_text(f"Скидка для пользователя {user_id} одобрена.")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")
        await query.message.reply_text("Скидка одобрена, но не удалось уведомить пользователя.")


# Отклоняет скидку администратором.*
async def admin_reject_discount( update: Update, context: CallbackContext):
    """Отклоняет скидку администратором."""
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    user_id = int(data[3])
    tariff_id = data[4]
    try:
        # Добавляем логику уведомления пользователя
        await context.bot.send_message(user_id, "К сожалению, ваша заявка на скидку отклонена.")
        await query.message.reply_text(f"Скидка для пользователя {user_id} отклонена.")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")
        await query.message.reply_text("Скидка отклонена, но не удалось уведомить пользователя.")


# Подтверждает покупку админом. *
async def admin_approve_purchase( update: Update,  context: CallbackContext):
    """Подтверждает покупку админом."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    buyer_user_id = int(data[3])  # Индекс 3, а не 2, чтобы получить user_id
    tariff_id = data[4]
    try:
        # Добавляем купленный курс пользователю
        await add_purchased_course(buyer_user_id, tariff_id, context)
        await query.message.reply_text(f"Покупка для пользователя {buyer_user_id} подтверждена!")
        await context.bot.send_message(
            chat_id=buyer_user_id,
            text="Ваш чек был подтверждён, приятного пользования курсом",
        )
    except Exception as e:
        logger.error(f"Ошибка при подтверждении покупки: {e}")
        await query.message.reply_text("Произошла ошибка при подтверждении покупки.")


# Отклоняет покупку админом.*
async def admin_reject_purchase( update: Update,    context: CallbackContext):
    """Отклоняет покупку админом."""
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    buyer_user_id = int(data[3])
    tariff_id = data[4]
    await query.message.reply_text("Покупка отклонена.")
    await context.bot.send_message(
        chat_id=buyer_user_id,
        text="Ваш чек не был подтверждён. Пожалуйста, свяжитесь с администратором",
    )


# Обрабатывает селфи для получения скидки. *
async def process_selfie( update: Update, context: CallbackContext):
    """Обрабатывает селфи для получения скидки."""
    # Get user ID safely with error handling
    user_id = update.effective_user.id if update and update.effective_user else None
    if not user_id:
        logger.error("Could not get user ID from update")
        return
    tariff = context.user_data.get("tariff")

    photo = update.message.photo[-1]
    file_id = photo.file_id
    context.user_data["selfie_file_id"] = file_id

    await update.message.reply_text("Теперь отправьте описание, почему вы хотите получить эту скидку:")
    logger.info(f"User {update.effective_user.id} transitioning to  WAIT_FOR_DESCRIPTION state")
    return WAIT_FOR_DESCRIPTION


# Обрабатывает описание для получения скидки.*
async def process_description( update: Update,  context: CallbackContext):
    """Обрабатывает описание для получения скидки."""
    user_id = update.effective_user.id
    tariff = context.user_data.get("tariff")
    description = update.message.text
    context.user_data["description"] = description
    logger.info(f"process_description  {description} 33333333 -------------<")

    photo = context.user_data.get("selfie_file_id")

    # Формируем сообщение для администратора
    caption = f"Запрос на скидку!\nUser ID: {user_id}\nТариф: {tariff['title']}\nОписание: {description}"
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Подтвердить скидку",
                callback_data=f'admin_approve_discount_{user_id}_{tariff["id"]}',
            ),
            InlineKeyboardButton(
                "❌ Отклонить скидку",
                callback_data=f'admin_reject_discount_{user_id}_{tariff["id"]}',
            ),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_photo(chat_id=ADMIN_GROUP_ID, photo=photo, caption=caption, reply_markup=reply_markup)
    await update.message.reply_text("Ваш запрос отправлен на рассмотрение администраторам.")
    logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
    return ConversationHandler.END


async def process_check( update: Update, context: CallbackContext):
    """Обрабатывает загруженный чек."""
    logger.info(f"13131313 process_check  -====---=---------<")
    try:
        user_id = update.effective_user.id
        tariff = context.user_data.get("tariff")
        photo = update.message.photo[-1]
        file_id = photo.file_id
        logger.info(f"process_check  {file_id} -------------<")

        # Отправляем админам фото чека и информацию о покупке
        caption = f"Новый запрос на покупку!\nUser ID: {user_id}\nТариф: {tariff['title']}"
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Подтвердить покупку",
                    callback_data=f'admin_approve_purchase_{user_id}_{tariff["id"]}',
                ),
                InlineKeyboardButton(
                    "❌ Отклонить покупку",
                    callback_data=f'admin_reject_purchase_{user_id}_{tariff["id"]}',
                ),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_photo(
            chat_id=ADMIN_GROUP_ID,
            photo=file_id,
            caption=caption,
            reply_markup=reply_markup,
        )

        await safe_reply(update, context, "Чек отправлен на проверку администраторам. Ожидайте подтверждения.")
        context.user_data.clear()  # Очищаем context.user_data
        logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"process_check error {e} -------------<")
        await safe_reply(update, context, "Ошибка при обработке чека. Попробуйте позже.")
        logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
        return ConversationHandler.END


async def process_gift_user_id( update: Update,  context: CallbackContext):
    """Обрабатывает User ID получателя подарка."""
    try:
        gift_user_id = update.message.text
        logger.info(f"process_gift_user_id  {gift_user_id} -------------<")

        if not gift_user_id or not gift_user_id.isdigit():
            await safe_reply(update, context, "Пожалуйста, введите корректный User ID, состоящий только из цифр.")
            logger.info(f"User {update.effective_user.id} transitioning to  WAIT_FOR_GIFT_USER_ID state")
            return WAIT_FOR_GIFT_USER_ID

        context.user_data["gift_user_id"] = gift_user_id
        # Remove unused user_id assignment
        tariff = context.user_data.get("tariff")
        # Инструкция по оплате
        text = f"Для оформления подарка, пожалуйста, переведите {tariff['price']} рублей на номер [номер] и загрузите чек сюда в этот диалог."  # Замените [сумма] и [номер]
        await safe_reply(update, context, text)
        logger.info(f"User {update.effective_user.id} transitioning to  WAIT_FOR_CHECK state")
        return WAIT_FOR_CHECK

    except Exception as e:
        logger.error(f"process_gift_user_id error {e} -------------<")
        await safe_reply(update, context, "Пожалуйста, введите корректный User ID, состоящий только из цифр.")
        logger.info(f"User {update.effective_user.id} transitioning to  WAIT_FOR_GIFT_USER_ID state")
        return WAIT_FOR_GIFT_USER_ID


# просим номерок *
async def process_phone_number( update: Update, context: CallbackContext):
    contact = update.message.contact
    phone_number = contact.phone_number
    logger.info(f"process_phone_number -------------<")
    context.user_data["phone_number"] = phone_number

    user_id = update.effective_user.id
    tariff = context.user_data.get("tariff")
    # Формируем сообщение для администратора
    caption = f"Новый запрос на покупку!\nUser ID: {user_id}\nТариф: {tariff['title']}\nНомер телефона: {phone_number}"
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Подтвердить покупку",
                callback_data=f'admin_approve_purchase_{user_id}_{tariff["id"]}',
            ),
            InlineKeyboardButton(
                "❌ Отклонить покупку",
                callback_data=f'admin_reject_purchase_{user_id}_{tariff["id"]}',
            ),
        ]
    ]
    photo = context.user_data.get("selfie_file_id")
    reply_markup = InlineKeyboardMarkup(keyboard)
    if photo:
        await context.bot.send_photo(
            chat_id=ADMIN_GROUP_ID,
            photo=photo,
            caption=caption,
            reply_markup=reply_markup,
        )
    else:
        await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=caption, reply_markup=reply_markup)

    await update.message.reply_text("Ваш запрос отправлен на рассмотрение администраторам.")
    # Clear user data dictionary
    if context.user_data:
        context.user_data.clear()  # Clear if exists
    else:
        context.user_data = {}  # Initialize if None
    logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
    return ConversationHandler.END


async def get_next_lesson_time( user_id):
    """Получает время следующего урока из базы данных."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    try:
        cursor.execute(
            """
            SELECT next_lesson_time, submission_time FROM users WHERE user_id = ?
        """,
            (user_id,),
        )
        result = cursor.fetchone()

        if result and result[0]:
            next_lesson_time_str = result[0]
            try:
                next_lesson_time = datetime.strptime(next_lesson_time_str, "%Y-%m-%d %H:%M:%S")
                return next_lesson_time.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError as e:
                logger.error(f"Ошибка при парсинге времени: {e}, строка: {next_lesson_time_str}")
                return "время указано в неверном формате"
        else:
            # Если время не определено, устанавливаем его на 3 часа после submission_time
            cursor.execute(
                """
                SELECT submission_time FROM homeworks 
                WHERE user_id = ? AND status = 'pending'
                ORDER BY submission_time DESC LIMIT 1
            """,
                (user_id,),
            )
            submission_result = cursor.fetchone()

            if submission_result and submission_result[0]:
                submission_time_str = submission_result[0]
                submission_time = datetime.strptime(submission_time_str, "%Y-%m-%d %H:%M:%S")
                next_lesson_time = submission_time + timedelta(hours=DEFAULT_LESSON_DELAY_HOURS)
                next_lesson_time_str = next_lesson_time.strftime("%Y-%m-%d %H:%M:%S")

                # Обновляем время в базе данных
                cursor.execute(
                    """
                    UPDATE users SET next_lesson_time = ? WHERE user_id = ?
                """,
                    (next_lesson_time_str, user_id),
                )
                conn.commit()

                return next_lesson_time_str
            else:
                return "время пока не определено"
    except Exception as e:
        logger.error(f"Ошибка при получении времени следующего урока: {e}")
        return "время пока не определено"


def setup_admin_commands(application, conn: sqlite3.Connection, cursor: sqlite3.Cursor):
    """Sets up admin commands."""
    application.add_handler(CommandHandler("stats", show_stats))
    application.add_handler(CallbackQueryHandler(admin_approve_purchase,pattern="^admin_approve_purchase_"))
    application.add_handler(CallbackQueryHandler(admin_reject_purchase, pattern="^admin_reject_purchase_"))
    application.add_handler(CallbackQueryHandler(admin_approve_discount, pattern="^admin_approve_discount_"))
    application.add_handler(CallbackQueryHandler(admin_reject_discount, pattern="^admin_reject_discount_"))


def setup_user_commands(application, conn: sqlite3.Connection, cursor: sqlite3.Cursor):
    """Sets up user commands."""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_main_menu))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_text_message))
    application.add_handler(CallbackQueryHandler(tariff_callback, pattern="^tariff_"))

    # lootboxes
    application.add_handler(CommandHandler("tokens", show_token_balance))
    application.add_handler(CommandHandler("buy_lootbox", buy_lootbox))


def init_lootboxes(conn: sqlite3.Connection, cursor: sqlite3.Cursor):
    try:
        cursor.execute("SELECT COUNT(*) FROM lootboxes")
        count = cursor.fetchone()[0]
        if count == 0:
            cursor.execute(
                """
                INSERT INTO lootboxes (box_type, reward, probability) VALUES
                ('light', 'скидка', 0.8),
                ('light', 'товар', 0.2);
                """
            )
            conn.commit()
            logger.info("Таблица lootboxes инициализирована.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при инициализации таблицы lootboxes: {e}")


def create_all_tables(conn: sqlite3.Connection, cursor: sqlite3.Cursor):
    logger.info("Таблицы SQL  создавайтес!!!!!!!!!!!!!!!!")

    try:
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL DEFAULT 'ЧЕБУРАШКА',
                birthday TEXT,
                registration_date TEXT,
                referral_count INTEGER DEFAULT 0,
                penalty_task TEXT,
                preliminary_material_index INTEGER DEFAULT 0,
                tariff TEXT,
                continuous_flow BOOLEAN DEFAULT 0,
                next_lesson_time DATETIME,
                active_course_id TEXT,
                user_code TEXT,
                last_bonus_date TEXT,
                trust_credit INTEGER DEFAULT 0,
                support_requests INTEGER DEFAULT 0,
                morning_time TEXT,   
                evening_time TEXT    
            );

            CREATE TABLE IF NOT EXISTS homeworks (
                hw_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                course_id TEXT,  
                lesson INTEGER,
                file_id TEXT,
                file_type TEXT,
                message_id INTEGER,
                status TEXT DEFAULT 'pending',
                feedback TEXT,
                timestamp TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                lesson_sent_time DATETIME,
                first_submission_time DATETIME,
                submission_time DATETIME,
                approval_time DATETIME,
                final_approval_time DATETIME,
                admin_comment TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            
            CREATE TABLE IF NOT EXISTS homework_rejections (
                rejection_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                course_id TEXT NOT NULL,
                lesson INTEGER NOT NULL,
                reason TEXT NOT NULL,
                rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );


            CREATE TABLE IF NOT EXISTS user_tokens (
                user_id INTEGER PRIMARY KEY,
                tokens INTEGER DEFAULT 3
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT, 
                amount INTEGER,
                reason TEXT, 
                timestamp TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS lootboxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                box_type TEXT, 
                reward TEXT, 
                probability REAL 
            );

            CREATE TABLE IF NOT EXISTS admins (
                admin_id INTEGER PRIMARY KEY,
                level INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS admin_codes (
                code_id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                code TEXT,
                created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                used BOOLEAN DEFAULT FALSE,
                FOREIGN KEY(admin_id) REFERENCES admins(admin_id)
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                morning_notification TIME,
                evening_notification TIME,
                show_example_homework BOOLEAN DEFAULT 1,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY,
                product_name TEXT NOT NULL,
                price INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_courses (
                user_id INTEGER,
                course_id TEXT,
                course_type TEXT CHECK(course_type IN ('main', 'auxiliary')),
                progress INTEGER DEFAULT 0,
                purchase_date TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                tariff TEXT,
                PRIMARY KEY (user_id, course_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS courses (
                course_id TEXT PRIMARY KEY,
                course_name TEXT,
                course_type TEXT CHECK(course_type IN ('main', 'auxiliary')),
                code_word TEXT,
                price_rub INTEGER
            );

            CREATE TABLE IF NOT EXISTS lessons (
                lesson_id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id TEXT,
                lesson INTEGER,
                lesson_name TEXT,
                description TEXT,
                video_url TEXT,
                video_file_id TEXT,
                FOREIGN KEY (course_id) REFERENCES courses(course_id)
            );
             -- Создание индексов
            CREATE INDEX IF NOT EXISTS idx_user_courses ON user_courses(user_id, course_id);
            CREATE INDEX IF NOT EXISTS idx_homeworks ON homeworks(user_id, course_id, lesson);
            """
        )
        conn.commit()
        logger.info("База данных успешно создана/сохранена.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при создании базы данных: {e}")

# черновик - не используем
def populate_courses_table(conn, cursor, filename=COURSE_DATA_FILE):
    """Загружает данные о курсах из JSON файла и заполняет таблицу courses."""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            courses_data = json.load(f)

            for course_data in courses_data:
                course_id = course_data.get("course_id")
                course_name = course_data.get("course_name")
                course_type = course_data.get("course_type")
                code_word = course_data.get("code_word")
                price_rub = course_data.get("price_rub")

                cursor.execute(
                    """
                    INSERT OR IGNORE INTO courses (course_id, course_name, course_type, code_word, price_rub)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (course_id, course_name, course_type, code_word, price_rub),
                )
            conn.commit()
            logger.info(f"Таблица courses успешно заполнена данными из {filename}")
    except FileNotFoundError:
        logger.error(f"Файл {filename} не найден.")
    except json.JSONDecodeError:
        logger.error(f"Ошибка при чтении JSON из файла {filename}.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при заполнении таблицы courses: {e}")


def validate_json_structure(data):
    """Проверяет структуру JSON данных."""
    required_keys = {"lesson", "lesson_name", "description", "video_url"}
    for item in data:
        if not all(key in item for key in required_keys):
            return False
    return True


def convert_to_utf8(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            f.read()  # Проверяем возможность чтения
        print(f"{file_path} уже в utf-8.")
    except UnicodeDecodeError:
        try:
            with open(file_path, "r", encoding="ISO-8859-1") as f:
                content = f.read()
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"{file_path} переконвертирован в utf-8.")
        except Exception as e:
            print(f"Не удалось обработать {file_path}: {e}")

# Проверяем все файлы lessons.json
courses_dir = "courses"
for course_dir in os.listdir(courses_dir):
    course_path = os.path.join(courses_dir, course_dir)
    lessons_file = os.path.join(course_path, "lessons.json")
    if os.path.isfile(lessons_file):
        convert_to_utf8(lessons_file)


def populate_lessons_table(conn, cursor, course_directory):
    """Загружает данные об уроках из JSON файла в папке курса и заполняет таблицу lessons."""
    logger.info(f"300 populate_lessons_table Загружаем уроки из {course_directory}")
    lessons_file = os.path.join(course_directory, "lessons.json")

    try:
        with open(lessons_file, "r", encoding="utf-8") as f:
            logger.info(f"301 Попытка открыть файл с кодировкой utf-8")
            lessons_data = json.load(f)
            logger.info(f"302 после попытки utf-8 {lessons_data[:2]}")

            for lesson_data in lessons_data:
                lesson_number = lesson_data.get("lesson")
                lesson_name = lesson_data.get("lesson_name")
                description = lesson_data.get("description")
                video_url = lesson_data.get("video_url")
                course_id = os.path.basename(course_directory) # Получаем course_id из названия папки
                logger.info (f" 578 Загружаем для {course_id=} {lesson_number=} {lesson_name=}")

                cursor.execute(
                    """
                    INSERT OR IGNORE INTO lessons (course_id, lesson, lesson_name, description, video_url)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (course_id, lesson_number, lesson_name, description, video_url),
                )
            conn.commit()
            logger.info(f"Таблица lessons успешно заполнена данными из {lessons_file}")
    except FileNotFoundError:
        logger.warning(f"Файл {lessons_file} не найден. Пропускаем загрузку уроков.")
    except UnicodeDecodeError as e:
        # Обработка ошибки кодировки
        logger.error(f"Ошибка кодировки при чтении файла {lessons_file}: {e}")
        logger.error(f"Сохраните файл {lessons_file} в кодировке utf-8 и попробуйте снова.")
        convert_to_utf8(lessons_file)  # вот сюда
    except json.JSONDecodeError:
        logger.error(f"Ошибка при чтении JSON из файла {lessons_file}.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при заполнении таблицы lessons: {e}")
        # Попытка открыть файл с кодировкой ISO-8859-1 (или другой подходящей)
        try:
            with open(lessons_file, "r", encoding="ISO-8859-1") as f:
                logger.info(f" 308 Попытка открыть файл с кодировкой ISO-8859-1")
                lessons_data = json.load(f)
                logger.info(f"309 после попытки {lessons_data}")

                for lesson_data in lessons_data:
                    lesson_number = lesson_data.get("lesson")
                    lesson_name = lesson_data.get("lesson_name")
                    description = lesson_data.get("description")
                    video_url = lesson_data.get("video_url")
                    course_id = os.path.basename(course_directory)

                    logger.info(f"Загружаем для {course_id=} {lesson_number=} {lesson_name=}")

                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO lessons (course_id, lesson, lesson_name, description, video_url)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (course_id, lesson_number, lesson_name, description, video_url),
                    )
                conn.commit()
                logger.info(f"Таблица lessons успешно заполнена данными из {lessons_file}")
        except Exception as e:
            logger.error(f"Не удалось обработать файл {lessons_file} даже с другой кодировкой: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка при чтении JSON из файла {lessons_file}: {e}. Пропускаем загрузку уроков.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при заполнении таблицы lessons: {e}")


async def cancel (update, context):
    await update.message.reply_text("Разговор завершён.")
    logger.info(f"User {update.effective_user.id} transitioning to  ConversationHandler.END state")
    return ConversationHandler.END


def create_connection(db_file=DATABASE_FILE):
    """Creates a database connection to the SQLite database specified by db_file."""
    conn = None
    cursor = None  # Инициализируем cursor
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()  # Создаем курсор
        logger.info(f"create_connection {db_file}")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при подключении к базе данных: {e}")
    return conn, cursor  # Всегда возвращаем кортеж (conn, cursor)

async def schedule_birthday_checks(application: Application):
    """Запускает проверку дней рождения и начисление бонусов."""
    scheduler = application.bot_data.get('scheduler')
    if scheduler is None:
        logger.error("Scheduler не найден в context.bot_data!")
        return

    scheduler.add_job(
        check_and_award_birthday_bonus,
        trigger='cron',
        hour=0,
        minute=0,
        start_date=datetime.now(),
        kwargs={'context': CallbackContext(application.bot, application.bot_data)}
    )




def main():
    # Database connection
    # Использование:
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    #conn, cursor = create_connection() старый вариант - переехали на Синглтон

    if conn and cursor:
        create_all_tables(conn, cursor)
        #populate_courses_table(conn, cursor)  # Заполняем таблицу courses ЧЕРНОВИК - ЕСТЬ ЛУЧШЕ populate_lessons_table

        populate_courses_table(conn, cursor)  # Заполняем таблицу courses
        # Загружаем данные об уроках из JSON файлов в папках курсов
        courses_dir = "courses"  # Папка с курсами
        for course_dir in os.listdir(courses_dir):
            course_path = os.path.join(courses_dir, course_dir)
            if os.path.isdir(course_path):
                populate_lessons_table(conn, cursor, course_path)

        # Проверка существующих индексов
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = cursor.fetchall()

        if indexes:
            logger.info("0 Существующие индексы в базе данных:")
            for index in indexes:
                logger.info(f" - {index[0]}")
        else:
            logger.info("Индексы в базе данных отсутствуют.")
    else:
        logger.error("Бяда 2 Database connection failed - cannot create tables")



    # Check if TOKEN is None before building application
    if TOKEN is None:
        raise ValueError("Bot token not found. Please set the TOKEN environment variable.")

    application = ApplicationBuilder().token(TOKEN).persistence(persistence).build()

    # Подключение middleware - ненадо. он всё ломает с гарантией
    # application.add_handler(MessageHandler(filters.ALL, logging_middleware))


    # ConversationHandler
    conv_handler = ConversationHandler( # скобка
        entry_points=[CommandHandler("start", start)],
        states={
            WAIT_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_info)],
            WAIT_FOR_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code_words)],
            ACTIVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message),
                CallbackQueryHandler(button_handler),
                MessageHandler(filters.PHOTO, handle_homework_submission),
                MessageHandler(filters.Document.IMAGE, handle_homework_submission ),  ],
            WAIT_FOR_SUPPORT_TEXT: [MessageHandler((filters.TEXT & ~filters.COMMAND) | filters.PHOTO, get_support_text)],
            WAIT_FOR_SELFIE: [MessageHandler(filters.PHOTO,  process_selfie ) ],
            WAIT_FOR_DESCRIPTION: [MessageHandler(filters.TEXT,  process_description ) ],
            WAIT_FOR_CHECK: [ MessageHandler(filters.PHOTO,  process_check )  ],
            WAIT_FOR_GIFT_USER_ID: [
                MessageHandler(filters.TEXT,  process_gift_user_id )
            ],
            WAIT_FOR_PHONE_NUMBER: [
                MessageHandler(filters.CONTACT, process_phone_number)
            ],
        },
        fallbacks = [CommandHandler("cancel",  cancel )],
        name = "my_conversation",
        allow_reentry = True,
        )

    application.add_handler(CallbackQueryHandler(approve_homework, pattern='^approve_admin_check'))
    #application.add_handler(CallbackQueryHandler(reject_homework, pattern='^reject_homework'))
    application.add_handler(CallbackQueryHandler(reject_homework, pattern='^decline_homework'))
    application.add_handler(CallbackQueryHandler(handle_history_callback, pattern='^history_callback'))


    application.add_handler(conv_handler)

    # Команды вне ConversationHandler (с передачей conn и cursor)
    application.add_handler(CommandHandler("start",  start ))
    application.add_handler(CommandHandler("menu",  show_main_menu ))
    application.add_handler(CommandHandler("reminders",  reminders ))
    application.add_handler(CommandHandler("set_morning",  set_morning ))
    application.add_handler(CommandHandler("set_evening",  set_evening ))
    application.add_handler(CommandHandler("disable_reminders",  disable_reminders ))
    application.add_handler(CommandHandler("stats",  stats ))

    # неизвестные команды
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Обработчик CallbackQuery
    application.add_handler(CallbackQueryHandler(button_handler))

    # Обработчик ошибок
    application.add_error_handler(handle_error)

    # Запуск планировщика задач
    scheduler = AsyncIOScheduler()
    application.bot_data['scheduler'] = scheduler  # Сохраняем scheduler в bot_data

    # Добавляем задачу для проверки и начисления бонусов за день рождения каждый день в 00:00
    scheduler.add_job(
        check_and_award_birthday_bonus,
        trigger='cron',
        hour=0,
        minute=2,
        start_date=datetime.now(),
        kwargs={'context': CallbackContext(application.bot, application.bot_data)}
    )

    scheduler.start()

    # Start the bot
    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

    # Не забудьте закрыть соединение при завершении работы бота:
    db.close()

if __name__ == "__main__":
    main()



    # TODO добавлять коинов по завершении курса

    # # Пример (замените на ваш реальный код)
    # async def process_course_completion(user_id: int, course_id: str):
    #     """Обрабатывает завершение курса."""
    #     # ... ваш код обработки завершения курса ...
    #     bonus_amount = bonuses_config.get("course_completion_bonus", 10)
    #     add_coins(user_id, bonus_amount)
    #     # Отправка подтверждения пользователю
    #     await context.bot.send_message(chat_id=user_id,
    #                                    text=f"🎉 Поздравляем с завершением курса! Вам начислено {bonus_amount} коинов.")

