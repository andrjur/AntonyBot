# main.py

import logging
import mimetypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import PicklePersistence
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaDocument,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
)
import sqlite3
from datetime import datetime, timedelta
import time
from dotenv import load_dotenv
import os
import re
import asyncio
from telegram.error import TelegramError
import json
import random


class Course:
    def __init__(self, course_id, course_name, course_type, tariff, code_word):
        self.course_id = course_id
        self.course_name = course_name
        self.course_type = course_type
        self.tariff = tariff
        self.code_word = code_word

    def __str__(self):
        return f"Course(id={self.course_id}, name={self.course_name}, type={self.course_type}, tariff={self.tariff}, code={self.code_word})"


# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

COURSE_DATA_FILE = "courses.json"

TARIFFS_FILE = "tariffs.json"

# Add a custom error handler decorator
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

def load_course_data(filename):
    """Загружает данные о курсах из JSON файла."""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            courses = [Course(**course_info) for course_info in data]
            logger.info(f"Файл с данными о курсах: {filename}")
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
def load_delay_messages(file_path="delay_messages.txt"):
    """Загружает список фраз из текстового файла."""
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            messages = [line.strip() for line in file if line.strip()]
        return messages
    except FileNotFoundError:
        logger.error(f"Файл c фразами не найден: {file_path}")
        return ["Ещё материал идёт, домашнее задание - можно уже делать"]
    except Exception as e:
        logger.error(f"Ошибка при загрузке фраз из файла: {e}")
        return ["Ещё материал идёт, домашнее задание - можно уже делать"]


# Загрузка фраз в начале программы
DELAY_MESSAGES = load_delay_messages()


load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
ADMIN_IDS = os.getenv("ADMIN_IDS").split(",")

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
) = range(10)


# Регулярное выражение для извлечения времени задержки из имени файла
# DELAY_PATTERN = re.compile(r"_(\d+)([mh])$") эта регулярка min не поддерживает
# DELAY_PATTERN = re.compile(r"_(\d+)(hour|min|m|h)$") расширение сраное забыли
DELAY_PATTERN = re.compile(r"_(\d+)(hour|min|m|h)(?:\.|$)")

# Интервал между уроками по умолчанию (в часах)
DEFAULT_LESSON_INTERVAL = 0.1  # интервал уроков 72 часа а не 6 минут!!!

DEFAULT_LESSON_DELAY_HOURS = 3

logger.info(f"{DEFAULT_LESSON_DELAY_HOURS=} {DEFAULT_LESSON_INTERVAL=} время старта {time.strftime('%d/%m/%Y %H:%M:%S')}")

PAYMENT_INFO_FILE = "payment_info.json"


# Словарь для кэширования данных
USER_CACHE = {}


def get_user_data(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id: int):  # Добавил conn и cursor
    """Получает данные пользователя из кэша или базы данных."""
    if user_id in USER_CACHE:
        return USER_CACHE[user_id]

    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    data = cursor.fetchone()

    if data:
        USER_CACHE[user_id] = data
        return data

    return None


def clear_user_cache(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id: int):  # Добавил conn и cursor
    """Очищает кэш для указанного пользователя."""
    logger.info(f" clear_user_cache {user_id} очистили")
    if user_id in USER_CACHE:
        del USER_CACHE[user_id]


# кому платить строго ненадо    conn: sqlite3.Connection, cursor: sqlite3.Cursor,
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


async def handle_error(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext, error: Exception):
    """Handles errors that occur in the bot."""
    logger.error(f"Error: {error}")
    await update.message.reply_text("Произошла ошибка. Попробуйте позже.")


# получение имени и проверка *
async def handle_user_info(
    conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext
):  # Добавил conn и cursor
    user_id = update.effective_user.id
    full_name = update.effective_message.text.strip()

    # Логирование текущего состояния пользователя
    logger.info(f" handle_user_info {user_id} - Current state")

    # Проверка на пустое имя
    if not full_name:
        await update.effective_message.reply_text("Имя не может быть пустым. Введите ваше полное имя:")
        return WAIT_FOR_NAME

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
        conn.commit()

        # Подтверждение записи
        user_data = get_user_data(conn, cursor, user_id)  # Добавил conn и cursor
        if user_data:
            saved_name = user_data["full_name"]
        else:
            saved_name = None

        if saved_name != full_name:
            logger.error(f"Имя не совпадает с сохраненным {saved_name} != {full_name}")
            print(f"Имя не совпадает с сохраненным {saved_name} != {full_name}")

        # Успешное сохранение, переход к следующему шагу
        await update.effective_message.reply_text(f"Отлично, {full_name}! Теперь введите кодовое слово для активации курса.")
        return WAIT_FOR_CODE

    except Exception as e:
        # Обработка ошибок при сохранении имени
        logger.error(f"Ошибка при сохранении имени: {e}")
        logger.error(f"Ошибка SQL при сохранении пользователя {user_id}: {e}")
        await update.effective_message.reply_text("Произошла ошибка при сохранении данных. Попробуйте снова.")
        return WAIT_FOR_NAME


# проверка оплаты через кодовые слова *
@handle_telegram_errors
async def handle_code_words(
    conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext
):  # Добавил conn и cursor
    user_id = update.message.from_user.id
    user_code = update.message.text.strip()

    # Логирование текущего состояния пользователя
    logger.info(f" handle_code_words {user_id} - Current state")

    if user_code in COURSE_DATA:
        # Активируем курс
        await activate_course(conn, cursor, update, context, user_id, user_code)
        logger.info(f" активирован {user_id}  return ACTIVE ")

        # Отправляем текущий урок
        await get_current_lesson(update, context)

        # Отправляем сообщение
        await update.message.reply_text("Курс активирован! Вы переходите в главное меню.")

        # Сбрасываем состояние ожидания кодового слова
        context.user_data["waiting_for_code"] = False

        return ACTIVE  # Переходим в состояние ACTIVE
    else:
        # Неверное кодовое слово
        logger.info(f" Неверное кодовое слово.   return WAIT_FOR_CODE")
        await update.message.reply_text("Неверное кодовое слово. Попробуйте еще раз.")
        return WAIT_FOR_CODE


# текущий урок заново
@handle_telegram_errors
async def get_current_lesson(update: Update, context: CallbackContext):
    """Отправляет все материалы текущего урока."""
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    user_id = update.effective_user.id
    logger.info(f" 777 get_current_lesson {user_id} - Current state")

    try:
        # Получаем active_course_id из users
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            # Используем callback_query, если это callback
            if update.callback_query:
                await update.callback_query.message.reply_text("Активируйте курс через кодовое слово.")
            else:
                await update.message.reply_text("Активируйте курс через кодовое слово.")
            return

        active_course_id_full = active_course_data[0]
        # Обрезаем название курса до первого символа "_"
        active_course_id = active_course_id_full.split("_")[0]
        logger.info(f" active_course_id {active_course_id} +")

        # Получаем course_type и tariff из context.user_data
        course_type = context.user_data.get("course_type", "main")
        tariff = context.user_data.get("tariff", "self_check")

        # Получаем progress (номер урока) из user_courses
        cursor.execute(
            """
            SELECT progress
            FROM user_courses
            WHERE user_id = ? AND course_id = ?
        """,
            (user_id, active_course_id_full),
        )
        progress_data = cursor.fetchone()

        # Если progress не найден, начинаем с первого урока и создаем запись
        if not progress_data:
            lesson = 1
            cursor.execute(
                """
                INSERT INTO user_courses (user_id, course_id, course_type, progress, tariff)
                VALUES (?, ?, ?, ?, ?)
            """,
                (user_id, active_course_id_full, course_type, lesson, tariff),
            )

            conn.commit()
            logger.warning(f" get_current_lesson с 1 урока начали на нижнем тарифе (самый быстрый) {active_course_id_full=}")
            # Используем callback_query, если это callback
            if update.callback_query:
                await update.callback_query.message.reply_text("Вы начинаете курс с первого урока.")
            else:
                await update.message.reply_text("Вы начинаете курс с первого урока.")
        else:
            lesson = progress_data[0]

        lesson_text = get_lesson_text(lesson, active_course_id)  #

        # Add media in function
        lesson_files = get_lesson_files(user_id, lesson, active_course_id)
        for i, file_info in enumerate(lesson_files, start=1):
            file_path = file_info["path"]
            file_type = file_info["type"]
            delay = file_info["delay"]  # Получаем задержку
            logger.info(f" {i} файл {file_path=} {file_type=} {delay=}")  # добавить в лог

            # Задержка перед отправкой
            if delay > 0:
                logger.info(f"Ожидание {delay} секунд перед отправкой файла {file_path}")
                if update.callback_query:
                    await update.callback_query.message.reply_text("ещё материал идёт, домашнее задание – можно уже делать")
                else:
                    await update.message.reply_text("ещё материал идёт, домашнее задание – можно уже делать")
                await asyncio.sleep(delay)

            try:
                with open(file_path, "rb") as file:
                    if file_type == "photo":
                        await context.bot.send_photo(chat_id=user_id, photo=file)
                    elif file_type == "video":
                        await context.bot.send_video(chat_id=user_id, video=file)
                    elif file_type == "audio":
                        await context.bot.send_audio(chat_id=user_id, audio=file)
                    else:
                        await context.bot.send_document(chat_id=user_id, document=file)

            except FileNotFoundError:
                logger.error(f"Media file not found: {file_path}")
                if update.callback_query:
                    await update.callback_query.message.reply_text(f"Media file not found: {file_path}")
                else:
                    await update.message.reply_text(f"Media file not found: {file_path}")
            except Exception as e:
                logger.error(f"Error sending media file: {e}")
                if update.callback_query:
                    await update.callback_query.message.reply_text(f"Error sending media file. {e}")
                else:
                    await update.message.reply_text(f"Error sending media file. {e}")

        if update.callback_query:
            await update.callback_query.message.reply_text(f"послано {len(lesson_files)} файлов")
        else:
            await update.message.reply_text(f"послано {len(lesson_files)} файлов")

        # Calculate the default release time of the next lesson
        next_lesson = lesson + 1
        next_lesson_release_time = datetime.now() + timedelta(hours=DEFAULT_LESSON_INTERVAL)
        next_lesson_release_str = next_lesson_release_time.strftime("%d-%m-%Y %H:%M:%S")
        await context.bot.send_message(
            chat_id=user_id,
            text=f"След урок {next_lesson} будет в {next_lesson_release_str}",
        )
        logger.info(f" 555 След урок {next_lesson} будет в {next_lesson_release_str}")

        # и показываем меню чтоб далеко не тянуться
        await show_main_menu(conn, cursor, update, context)  # Добавил conn и cursor

    except Exception as e:
        logger.error(f"Ошибка при получении текущего урока: {e}")
        # Используем callback_query, если это callback
        if update.callback_query:
            await update.callback_query.message.reply_text("Ошибка при получении текущего урока. Попробуйте позже.")
        else:
            await update.message.reply_text("Ошибка при получении текущего урока. Попробуйте позже.")


# Qwen 15 марта утром строго без conn: sqlite3.Connection, cursor: sqlite3.Cursor,
@handle_telegram_errors
async def process_lesson(user_id, lesson_number, active_course_id, context):
    """Обрабатывает текст урока и отправляет связанные файлы."""
    try:
        # Читаем текст урока
        lesson_text = get_lesson_text(lesson_number, active_course_id)
        if lesson_text:
            await context.bot.send_message(chat_id=user_id, text=lesson_text)
        else:
            await context.bot.send_message(chat_id=user_id, text="Текст урока не найден.")

        # Получаем файлы для урока
        lesson_files = get_lesson_files(user_id, lesson_number, active_course_id)

        # Отправляем файлы
        for file_info in lesson_files:
            file_path = file_info["path"]
            file_type = file_info["type"]
            delay = file_info["delay"]

            if delay > 0:
                # Выбираем случайное сообщение из DELAY_MESSAGES
                delay_message = random.choice(DELAY_MESSAGES)
                logger.info(f"Задержка перед отправкой файла {file_path}: {delay} секунд {delay_message=}")
                await context.bot.send_message(chat_id=user_id, text=delay_message)
                await asyncio.sleep(delay)

            try:
                with open(file_path, "rb") as file:
                    if file_type == "photo":
                        await context.bot.send_photo(chat_id=user_id, photo=file)
                    elif file_type == "video":
                        await context.bot.send_video(chat_id=user_id, video=file)
                    elif file_type == "audio":
                        await context.bot.send_audio(chat_id=user_id, audio=file)
                    else:
                        await context.bot.send_document(chat_id=user_id, document=file)
            except FileNotFoundError:
                logger.error(f"Файл не найден: {file_path}")
                await context.bot.send_message(chat_id=user_id, text=f"Файл не найден: {file_path}")
            except Exception as e:
                logger.error(f"Ошибка при отправке файла {file_path}: {e}")
                await context.bot.send_message(chat_id=user_id, text=f"Ошибка при отправке файла: {e}")

    except Exception as e:
        logger.error(f"Ошибка при обработке урока: {e}")
        await context.bot.send_message(chat_id=user_id, text="Произошла ошибка при обработке урока.")


# Qwen 15 марта утром строго ненадо   conn: sqlite3.Connection, cursor: sqlite3.Cursor,
def get_lesson_text(lesson_number, active_course_id):
    """Читает текст урока из файла."""
    try:
        lesson_text_path = os.path.join("courses", active_course_id, f"lesson{lesson_number}.txt")
        with open(lesson_text_path, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        logger.error(f"Файл урока не найден: ")
        return None
    except Exception as e:
        logger.error(f"Ошибка при чтении текста урока: {e}")
        return None


# Menu *
async def show_main_menu(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    user = update.effective_user
    logger.info(f"{user} - show_main_menu")

    try:
        # Get data of course
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user.id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            # Using callback_query
            if update.callback_query:
                await update.callback_query.message.reply_text("Activate with code.")
            else:
                await update.message.reply_text("Activate with code.")
            return

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
        course_type, progress = cursor.fetchone()

        # Notifications
        cursor.execute(
            "SELECT morning_notification, evening_notification FROM user_settings WHERE user_id = ?",
            (user.id,),
        )
        settings = cursor.fetchone()
        morning_time = settings[0] if settings else "Not set"
        evening_time = settings[1] if settings else "Not set"

        # Get username
        cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user.id,))
        full_name = cursor.fetchone()[0]
        homework = await get_homework_status_text(conn, cursor, user.id, active_course_id_full)

        # Checking last homework
        lesson_files = get_lesson_files(user.id, progress, active_course_id)
        last_lesson = check_last_lesson(active_course_id)

        # Checking if end and go to action
        if int(progress) >= int(last_lesson):
            await course_completion_actions(conn, cursor, update, context)
            return
        # Debug state
        if context.user_data.get("waiting_for_code"):
            state_emoji = "🔑"  # Key emoji for 'waiting_for_code' state
        else:
            state_emoji = "✅"  # Checkmark for other states

        progress_text = f"Текущий урок: {progress}" if progress else "Прогресс отсутствует"
        greeting = f"""Приветствую, {full_name.split()[0]}! {state_emoji}
        Курс: {active_course_id} ({course_type}) {active_tariff}
        Прогресс: {progress_text}
        Домашка: {homework} введи /self_approve_{progress}"""
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
        # ADD DYNAMIC BUTTON
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
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send menu
        # Using callback_query
        if update.callback_query:
            await update.callback_query.message.reply_text(greeting, reply_markup=reply_markup)
        else:
            await update.message.reply_text(greeting, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"time {time.strftime('%H:%M:%S')} Error in show_main_menu: {str(e)}")
        # Using callback_query
        if update.callback_query:
            await update.callback_query.message.reply_text("Error display menu. Try later.")
        else:
            await update.message.reply_text("Error display menu. Try later.")


# НАЧАЛО *
async def start(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Обрабатывает команду /start."""
    user_id = update.effective_user.id

    # Логирование команды /НАЧАЛО
    logger.info(f"  start {user_id} - НАЧАЛО =================================================================")

    try:
        # Получение данных о пользователе из базы данных
        cursor.execute(
            """
            SELECT user_id
            FROM users 
            WHERE user_id = ?
            """,
            (user_id,),
        )
        user_data = cursor.fetchone()
        await context.bot.send_message(chat_id=user_id, text=f"привет {user_id}")

        # Если пользователь не найден, запрашиваем имя
        if not user_data:
            await update.effective_message.reply_text("Пожалуйста, введите ваше имя:")
            context.user_data["waiting_for_name"] = True  # Устанавливаем состояние ожидания имени
            return WAIT_FOR_NAME
        else:
            # Проверяем, есть ли активный курс
            cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
            active_course = cursor.fetchone()[0]

            # Если курсы не активированы, запрашиваем кодовое слово
            if not active_course:
                await update.effective_message.reply_text("Для начала введите кодовое слово вашего курса:")
                context.user_data["waiting_for_code"] = True  # Устанавливаем состояние ожидания кодового слова
                return WAIT_FOR_CODE
            else:
                # Если курсы активированы, показываем главное меню
                await show_main_menu(conn, cursor, update, context)
                return ACTIVE  # Переходим в состояние ACTIVE
    except Exception as e:
        logger.error(f"Ошибка в функции НАЧАЛО start: {e}")
        await update.effective_message.reply_text("Произошла ошибка. Попробуйте позже.")
        return ConversationHandler.END


async def course_completion_actions(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Actions to perform upon course completion."""
    user_id = update.effective_user.id
    logger.info(f"course_completion_actions  {user_id} 44 ")
    # Get active_course_id from user
    cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
    active_course_data = cursor.fetchone()
    active_course_id_full = active_course_data[0]
    # Inform user
    await update.message.reply_text("Congratulations, you have finished the course")

    await show_statistics(conn, cursor, update, context)

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
    available_lessons = get_available_lessons(conn, cursor, active_course_id_full)
    keyboard = generate_lesson_keyboard(conn, cursor, available_lessons)
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("All finished .", reply_markup=reply_markup)


def get_available_lessons(conn: sqlite3.Connection, cursor: sqlite3.Cursor, course_id):
    """Get all existing lessons by course."""
    lesson_dir = f"courses/{course_id}/"
    lessons = [
        int(f.replace("lesson", "").replace(".txt", ""))
        for f in os.listdir(lesson_dir)
        if f.startswith("lesson") and f.endswith(".txt")
    ]
    lessons.sort()
    logger.info(f"get_available_lessons  {lessons} 333 ")
    return lessons


def generate_lesson_keyboard(conn: sqlite3.Connection, cursor: sqlite3.Cursor, lessons, items_per_page=10):
    """Generate buttons with page"""
    keyboard = []
    logger.info(f"generate_lesson_keyboard ")
    for lesson in lessons:
        keyboard.append([InlineKeyboardButton(f"Lesson {lesson}", callback_data=f"lesson_{lesson}")])  # type: ignore
    return keyboard


# домашка ???
async def get_homework_status_text(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id, course_id):
    """Возвращает текст статуса проверки домашнего задания."""
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

    # Формируем текст в зависимости от статуса
    if status == "pending":
        return f"Домашка к {lesson} уроку на самопроверке"
    elif status == "approved":
        return f"Домашка к {lesson} уроку принята"
    else:
        return "Статус домашки неизвестен странен и загадочен"


# проверка активации курсов *
async def activate_course(
    conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext, user_id: int, user_code: str
):  # Добавил conn и cursor
    """Активирует курс для пользователя."""

    # Получаем данные о курсе из COURSE_DATA по кодовому слову
    course = COURSE_DATA[user_code]
    course_id_full = course.course_id  # Полное название курса (например, femininity_premium)
    course_id = course_id_full.split("_")[0]  # Базовое название курса (например, femininity)
    course_type = course.course_type  # 'main' или 'auxiliary'
    tariff = course_id_full.split("_")[1] if len(course_id_full.split("_")) > 1 else "default"  # Тариф (premium, self_check и т.д.)
    logger.info(f"activate_course {tariff} {course_id_full}")
    try:
        # Проверяем, есть ли уже какой-то курс с таким базовым названием у пользователя
        cursor.execute(
            """
            SELECT course_id, tariff FROM user_courses
            WHERE user_id = ? AND course_id LIKE ?
        """,
            (user_id, f"{course_id}%"),
        )
        existing_course = cursor.fetchone()

        if existing_course:
            existing_course_id = existing_course[0]
            existing_tariff = existing_course[1]

            if existing_course_id == course_id_full:
                # Полное совпадение - курс уже активирован
                await update.message.reply_text("Этот курс уже активирован для вас.")
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
                await update.message.reply_text(f"Вы перешли с тарифа {existing_tariff} на тариф {tariff}.")

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
                logger.info(f"Обновлен тариф пользователя {user_id} с {existing_tariff} на {tariff} для курса {course_id}")

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

            await update.message.reply_text(f"Курс {course_id} ({tariff}) активирован!")

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
            logger.info(f"Курс {course_id} типа {course_type} активирован для пользователя {user_id} с тарифом {tariff}")

    except Exception as e:
        logger.error(f"Ошибка при активации или обновлении курса для пользователя {user_id}: {e}")
        await update.message.reply_text("Произошла ошибка при активации курса. Попробуйте позже.")


# вычисляем время следующего урока *
async def update_next_lesson_time(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id, course_id):
    """Обновляет время следующего урока для пользователя."""
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
async def course_management(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Управление курсом."""
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


# Обрабатывает отправку домашнего задания и отправляет его администратору (если требуется *
async def handle_homework_submission(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Обрабатывает отправку домашнего задания (фото или документ)."""
    user_id = update.effective_user.id
    logger.info(f" handle_homework_submission {user_id=}")

    # Определяем, что пришло: фото или документ
    if update.message.photo:
        # Получаем file_id самого большого фото (последнего в списке)
        file_id = update.message.photo[-1].file_id
        file_type = "photo"
    elif update.message.document and update.message.document.mime_type.startswith("image/"):
        # Получаем file_id документа и проверяем, что это изображение
        file_id = update.message.document.file_id
        file_type = "document"
    else:
        await update.message.reply_text("⚠️ Отправьте, пожалуйста, картинку или фотографию.")
        return

    # Получаем active_course_id из users
    cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
    active_course_data = cursor.fetchone()

    if not active_course_data or not active_course_data[0]:
        await update.message.reply_text("Пожалуйста, активируйте курс.")
        return

    active_course_id_full = active_course_data[0]
    cursor.execute(
        """
        SELECT progress, tariff
        FROM user_courses
        WHERE user_id = ? AND course_id = ?
    """,
        (user_id, active_course_id_full),
    )
    progress_data = cursor.fetchone()

    if not progress_data:
        await update.message.reply_text("Не найден прогресс курса.")
        return

    lesson, tariff = progress_data

    try:
        # Получаем информацию о файле
        file = await context.bot.get_file(file_id)
        file_ext = ".jpg"  # Ставим расширение по умолчанию

        if file_type == "document":
            file_ext = mimetypes.guess_extension(update.message.document.mime_type) or file_ext
            if file_ext == ".jpe":
                file_ext = ".jpg"  # Преобразуем .jpe в .jpg
        file_path = f"homeworks/{user_id}_{file.file_unique_id}{file_ext}"
        await file.download_to_drive(file_path)

        # Сохраняем информацию о домашнем задании в базе данных
        cursor.execute(
            """
            INSERT INTO homeworks (user_id, course_id, lesson, file_path, status)
            VALUES (?, ?, ?, ?, ?)
        """,
            (user_id, active_course_id_full, lesson, file_path, "pending"),
        )
        conn.commit()

        # Получаем hw_id только что добавленной записи
        cursor.execute(
            """
            SELECT hw_id FROM homeworks 
            WHERE user_id = ? AND course_id = ? AND lesson = ?
            ORDER BY hw_id DESC LIMIT 1
        """,
            (user_id, active_course_id_full, lesson),
        )
        hw_id_data = cursor.fetchone()
        hw_id = hw_id_data[0] if hw_id_data else None

        if hw_id is None:
            logger.error(f"Не удалось получить hw_id для user_id={user_id}, course_id={active_course_id_full}, lesson={lesson}")
            await update.message.reply_text("Произошла ошибка при обработке домашнего задания. Попробуйте позже.")
            return

        # Если тариф с самопроверкой
        if tariff == "self_check":
            # Отправка кнопки для самопроверки пользователю
            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ Принять домашнее задание",
                        callback_data=f"self_approve_{hw_id}",
                    )
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"Домашнее задание по уроку {lesson} отправлено. Вы можете самостоятельно подтвердить выполнение.",
                reply_markup=reply_markup,
            )
        else:
            # Отправка домашнего задания админу для проверки
            keyboard = [
                [
                    InlineKeyboardButton("✅ Принять", callback_data=f"approve_homework_{hw_id}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"decline_homework_{hw_id}"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            admin_message = f"Пользователь {user_id} отправил домашнее задание по курсу {active_course_id_full}, урок {lesson}."
            try:
                with open(file_path, "rb") as photo:
                    await context.bot.send_photo(
                        chat_id=ADMIN_GROUP_ID,
                        photo=photo,
                        caption=admin_message,
                        reply_markup=reply_markup,
                    )
                    logger.info(f"Sent homework to admin group for user {user_id}, lesson {lesson}")
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения админу: {e}")
                await update.message.reply_text("Произошла ошибка при отправке сообщения админу. Попробуйте позже.")
                return

        await update.message.reply_text("Домашнее задание отправлено на проверку.")

    except Exception as e:
        logger.error(f"Ошибка при обработке домашнего задания: {e}")
        await update.message.reply_text("Произошла ошибка при обработке домашнего задания. Попробуйте позже.")


# Получение следующего времени урока
async def calculate_time_to_next_lesson(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id, active_course_id_full):
    """Вычисляет, сколько времени осталось до следующего урока."""
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

    if not last_submission_data:
        # Если ещё не было уроков, то следующий урок через DEFAULT_LESSON_INTERVAL
        next_lesson_time = datetime.now() + timedelta(hours=DEFAULT_LESSON_INTERVAL)
        return next_lesson_time - datetime.now()

    # Преобразуем время последнего урока из базы данных
    last_submission_time = datetime.strptime(last_submission_data[0], "%Y-%m-%d %H:%M:%S")

    # Рассчитываем время следующего урока
    next_lesson_time = last_submission_time + timedelta(hours=DEFAULT_LESSON_INTERVAL)

    # Возвращаем, сколько времени осталось до следующего урока
    return next_lesson_time - datetime.now()


async def save_admin_comment(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """
    Сохраняет комментарий админа и обновляет статус ДЗ.
    """
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
async def handle_admin_rejection(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Обрабатывает отклонение ДЗ администратором."""
    query = update.callback_query
    await query.answer()

    try:
        # Получаем hw_id из callback_data
        hw_id = query.data.split("_")[2]  # was '|' and [1]

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
            await query.message.reply_text("Ошибка: ДЗ не найдено.")
            return

        user_id, course_id, lesson = homework_data

        # Отправляем уведомление пользователю
        await context.bot.send_message(
            chat_id=user_id,
            text=f"К сожалению, Ваше домашнее задание по уроку {lesson} курса {course_id} отклонено администратором. Попробуйте еще раз.",
        )

        # Редактируем сообщение в админ-группе
        await context.bot.edit_message_reply_markup(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            reply_markup=None,  # Убираем кнопки
        )
        await context.bot.edit_message_caption(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            caption=query.message.caption + "\n\n❌ Отклонено!",
        )

        logger.info(f"ДЗ {hw_id} отклонено администратором")

    except Exception as e:
        logger.error(f"Ошибка при отклонении ДЗ: {e}")
        await query.message.reply_text("Произошла ошибка при отклонении ДЗ. Попробуйте позже.")


# Обрабатывает выбор тарифа
async def change_tariff(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Обрабатывает выбор тарифа."""
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
            await update.callback_query.message.reply_text("У вас не активирован ни один курс.")
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

        await update.callback_query.message.reply_text("Выберите новый тариф:", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Ошибка при отображении вариантов тарифов: {e}")
        await update.callback_query.message.reply_text("Произошла ошибка при отображении вариантов тарифов. Попробуйте позже.")


# Отображает список курсов пользователя
async def my_courses(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Отображает список курсов пользователя."""
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
            await update.callback_query.message.reply_text("У вас нет активных курсов.")
            return

        # Формируем текстовое сообщение со списком курсов
        message_text = "Ваши курсы:\n"
        for course_id, course_type in courses_data:
            message_text += f"- {course_id} ({course_type})\n"

        await update.callback_query.message.reply_text(message_text)

    except Exception as e:
        logger.error(f"Ошибка при отображении списка курсов: {e}")
        await update.callback_query.message.reply_text("Произошла ошибка при отображении списка курсов. Попробуйте позже.")


# статистика домашек *
async def show_statistics(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Shows statistics for lessons and homework, considering all users, deviations, and course completion."""
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
        average_homework_time = get_average_homework_time(conn, cursor, user_id)

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
async def format_progress(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id, course_id):
    """Getting info about lesson."""
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

    progress = progress_data[0]

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
async def hw_history(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Отображает историю домашних заданий пользователя."""
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
            await update.callback_query.message.reply_text("У вас нет истории домашних заданий.")
            return

        # Формируем текстовое сообщение с историей ДЗ
        message_text = "История ваших домашних заданий:\n"
        for course_id, lesson, status, submission_time in homeworks_data:
            message_text += f"- Курс: {course_id}, Урок: {lesson}, Статус: {status}, Дата отправки: {submission_time}\n"

        await update.callback_query.message.reply_text(message_text)

    except Exception as e:
        logger.error(f"Ошибка при отображении истории ДЗ: {e}")
        await update.callback_query.message.reply_text("Произошла ошибка при отображении истории домашних заданий. Попробуйте позже.")


async def handle_check_payment(
    conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext, tariff_id: str
):
    """Handles the "I Paid" button."""
    query = update.callback_query
    user_id = update.effective_user.id

    logger.info(f"handle_check_payment: tariff_id={tariff_id}, user_id={user_id}")

    if not tariff_id:
        logger.error("handle_check_payment: tariff_id is empty.")
        await query.message.reply_text("Произошла ошибка: tariff_id не может быть пустым.")
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
            await query.message.reply_text("Tariff file not found. Please try again later.")
            return
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from file: {TARIFFS_FILE}")
            await query.message.reply_text("Error decoding tariff data. Please try again later.")
            return

        # Find selected tariff
        selected_tariff = next((tariff for tariff in tariffs if tariff["id"] == tariff_id), None)

        if selected_tariff:
            logger.info(f"Handling check payment for tariff: {selected_tariff}")

            # Send notification to admins
            message = (
                f"Пользователь {user_id} запросил проверку оплаты тарифа {selected_tariff['title']}.\n"
                f"Необходимо проверить оплату и активировать тариф для пользователя."
            )

            # Send notification to all admin IDs
            for admin_id in ADMIN_IDS:  # Ensure ADMIN_IDS is a list of strings
                try:
                    await context.bot.send_message(chat_id=admin_id, text=message)
                    logger.info(f"Sent payment verification request to admin {admin_id}")
                except TelegramError as e:
                    logger.error(f"Failed to send message to admin {admin_id}: {e}")

            await query.message.reply_text("Ваш запрос на проверку оплаты отправлен администратору. Ожидайте подтверждения.")

        else:
            logger.warning(f"Tariff with id {tariff_id} not found.")
            await query.message.reply_text("Tariff not found. Please select again.")

    except Exception as e:
        logger.exception(f"Error handling check payment: {e}")
        await query.message.reply_text("Error processing payment verification. Please try again later.")


# Устанавливает выбранный тариф для пользователя
async def set_tariff(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Устанавливает выбранный тариф для пользователя."""
    query = update.callback_query
    await query.answer()
    logger.info(f"  set_tariff ")

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
        await query.message.reply_text(f"Тариф для курса {course_id} изменен на {tariff}.")

    except Exception as e:
        logger.error(f"Ошибка при установке тарифа: {e}")
        await query.message.reply_text("Произошла ошибка при установке тарифа. Попробуйте позже.")


async def show_support(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Отображает информацию о поддержке."""
    logger.info(f" show_support  ")
    await update.message.reply_text("Здесь будет информация о поддержке.")


# самопроверка на базовом тарифчике пт 14 марта 17:15
async def self_approve_homework(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Обрабатывает самопроверку домашнего задания."""
    user_id = update.effective_user.id
    try:
        # Извлекаем hw_id из текста сообщения
        hw_id = int(context.args[0])

        # Обновляем статус домашнего задания в базе данных
        cursor.execute(
            """
            UPDATE homeworks
            SET status = 'approved', approval_time = CURRENT_TIMESTAMP
            WHERE hw_id = ? AND user_id = ?
        """,
            (hw_id, user_id),
        )
        conn.commit()

        # Отправляем сообщение об успешной самопроверке
        await update.message.reply_text("Домашнее задание подтверждено вами.")

    except (IndexError, ValueError):
        # Обрабатываем ошибки, если не удалось извлечь hw_id
        await update.message.reply_text("Неверный формат команды. Используйте /self_approve <hw_id>.")
    except Exception as e:
        # Обрабатываем другие возможные ошибки
        logger.error(f"Ошибка при самопроверке домашнего задания: {e}")
        await update.message.reply_text("Произошла ошибка при самопроверке домашнего задания. Попробуйте позже.")


# проверка админом на базовом тарифчике пт 14 марта 17:15
async def approve_homework(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Подтверждает домашнее задание администратором."""
    query = update.callback_query
    await query.answer()

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
        await query.edit_message_text(text="Домашнее задание подтверждено администратором.")
    except Exception as e:
        logger.error(f"Ошибка при подтверждении домашнего задания: {e}")
        await query.message.reply_text("Произошла ошибка при подтверждении домашнего задания.")


async def handle_approve_payment(
    conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext, user_id: str, tariff_id: str
):
    """Handles the "Approve Payment" button."""
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

            await query.edit_message_text(
                f"Оплата тарифа {selected_tariff['title']} для пользователя {user_id} одобрена администратором {admin_id}."
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Ваша оплата тарифа {selected_tariff['title']} подтверждена. Теперь вам доступны все материалы курса.",
            )

        else:
            logger.warning(f"Tariff with id {tariff_id} not found.")
            await query.message.reply_text("Выбранный тариф не найден.")
    except Exception as e:
        logger.error(f"Error handling approve payment: {e}")
        await query.message.reply_text("Произошла ошибка при одобрении оплаты. Попробуйте позже.")


async def handle_decline_payment(
    conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext, user_id: str, tariff_id: str
):
    """Handles the "Decline Payment" button."""
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

            await query.edit_message_text(
                f"Оплата тарифа {selected_tariff['title']} для пользователя {user_id} отклонена администратором {admin_id}."
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Ваша оплата тарифа {selected_tariff['title']} отклонена. Обратитесь в службу поддержки.",
            )

        else:
            logger.warning(f"Tariff with id {tariff_id} not found.")
            await query.message.reply_text("Выбранный тариф не найден.")
    except Exception as e:
        logger.error(f"Error handling decline payment: {e}")
        await query.message.reply_text("Произошла ошибка при отклонении оплаты. Попробуйте позже.")


# Отображает настройки курса *
async def show_course_settings(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Отображает настройки курса."""
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

        # Проверяем, откуда была вызвана функция
        if update.message:
            await update.message.reply_text(text)
        elif update.callback_query:
            await update.callback_query.message.reply_text(text)
        else:
            logger.error("Не удалось определить источник вызова функции show_course_settings")
            return

    except Exception as e:
        logger.error(f"Ошибка при отображении настроек курса для пользователя {user_id}: {e}")
        # Проверяем, откуда была вызвана функция
        if update.message:
            await update.message.reply_text("Произошла ошибка при загрузке настроек. Попробуйте позже.")
        elif update.callback_query:
            await update.callback_query.message.reply_text("Произошла ошибка при загрузке настроек. Попробуйте позже.")
        else:
            logger.error("Не удалось определить источник вызова функции show_course_settings при ошибке")
            return


# Отображает тарифы и акции. *
async def show_tariffs(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Отображает доступные тарифы и бонусы."""
    user_id = update.effective_user.id
    logger.info(f"show_tariffs --------------------- 222")
    try:
        query = update.callback_query  # Получаем CallbackQuery
        await query.answer()

        # Загружаем тарифы из файла
        try:
            with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
                tariffs_data = json.load(f)

        except FileNotFoundError:
            logger.error(f"File not found: {TARIFFS_FILE}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,  # Используем query.message.chat_id
                text="Cannot display tariffs. Please try later.",
            )
            return
        except json.JSONDecodeError:
            logger.error(f"Ошибка чтения JSON файла: {TARIFFS_FILE}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,  # Используем query.message.chat_id
                text="Cannot display tariffs. Please try later.",
            )
            return

        # Формируем кнопки для каждого тарифа
        keyboard = []
        logger.info(f"show_tariffs3 ------------------- 333")
        for tariff in tariffs_data:  # Исправлено: tariffs -> tariffs_data
            if "title" not in tariff:
                logger.error(f"Tariff missing 'title' key: {tariff.get('id', 'Unknown')}")
                continue
            callback_data = f"tariff_{tariff['id']}"  # Передаем полный ID тарифа
            keyboard.append([InlineKeyboardButton(tariff["title"], callback_data=callback_data)])

        keyboard.append([InlineKeyboardButton("Назад", callback_data="menu_back")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        logger.info(f"show_tariffs4  готово ------------------- 333")

        await context.bot.send_message(
            chat_id=query.message.chat_id,  # Используем query.message.chat_id
            text="Вот доступные тарифы и бонусы:",
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error(f"Error during show tariffs: {e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Something went wrong.")


# "Показывает текст урока по запросу."*
async def show_lesson(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Отправляет все материалы текущего урока, включая текст и файлы, а также напоминает о ДЗ."""
    user_id = update.effective_user.id
    logger.info(f" show_lesson {user_id} - Current state")

    try:
        # Получаем active_course_id из users
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            if update.callback_query:
                await update.callback_query.message.reply_text("Активируйте курс через кодовое слово.")
            else:
                await update.message.reply_text("Активируйте курс через кодовое слово.")
            return

        active_course_id_full = active_course_data[0]
        # Обрезаем название курса до первого символа "_"
        active_course_id = active_course_id_full.split("_")[0]
        logger.info(f" active_course_id {active_course_id} +")

        # Получаем progress (номер урока) из user_courses
        cursor.execute(
            """
            SELECT progress
            FROM user_courses
            WHERE user_id = ? AND course_id = ?
        """,
            (user_id, active_course_id_full),
        )
        progress_data = cursor.fetchone()

        # Если progress не найден, отдаем первый урок
        if not progress_data:
            lesson = 1
            await update.callback_query.message.reply_text("Начинаем с первого урока.")
        else:
            lesson = progress_data[0]

        # 1. Отправляем текст урока
        lesson_text = get_lesson_text(lesson, active_course_id)
        if lesson_text:
            await update.callback_query.message.reply_text(lesson_text)
        else:
            await update.callback_query.message.reply_text("Текст урока не найден.")

        # 2. Отправляем файлы урока (аудио, видео, изображения)
        lesson_files = await get_lesson_files(user_id, lesson, active_course_id)
        if lesson_files:
            total_files = len(lesson_files)  # Общее количество файлов
            for i, file_info in enumerate(lesson_files):
                file_path = file_info["path"]
                delay = file_info["delay"]
                file_type = file_info["type"]

                if delay > 0:
                    await asyncio.sleep(delay)

                try:
                    if file_type == "photo":
                        with open(file_path, "rb") as photo_file:
                            if update.callback_query:
                                await context.bot.send_photo(
                                    chat_id=update.effective_chat.id,
                                    photo=photo_file,
                                    caption=f"Фото к уроку {lesson}",
                                )
                            else:
                                await context.bot.send_photo(
                                    chat_id=user_id,
                                    photo=photo_file,
                                    caption=f"Фото к уроку {lesson}",
                                )
                    elif file_type == "audio":
                        with open(file_path, "rb") as audio_file:
                            if update.callback_query:
                                await context.bot.send_audio(
                                    chat_id=update.effective_chat.id,
                                    audio=audio_file,
                                    caption=f"Аудио к уроку {lesson}",
                                )
                            else:
                                await context.bot.send_audio(
                                    chat_id=user_id,
                                    audio=audio_file,
                                    caption=f"Аудио к уроку {lesson}",
                                )
                    elif file_type == "video":
                        with open(file_path, "rb") as video_file:
                            if update.callback_query:
                                await context.bot.send_video(
                                    chat_id=update.effective_chat.id,
                                    video=video_file,
                                    caption=f"Видео к уроку {lesson}",
                                )
                            else:
                                await context.bot.send_video(
                                    chat_id=user_id,
                                    video=video_file,
                                    caption=f"Видео к уроку {lesson}",
                                )
                    elif file_type == "document":
                        with open(file_path, "rb") as doc_file:
                            if update.callback_query:
                                await context.bot.send_document(
                                    chat_id=update.effective_chat.id,
                                    document=doc_file,
                                    caption=f"Документ к уроку {lesson}",
                                )
                            else:
                                await context.bot.send_document(
                                    chat_id=user_id,
                                    document=doc_file,
                                    caption=f"Документ к уроку {lesson}",
                                )
                    else:
                        logger.warning(f"Неизвестный тип файла: {file_type}, {file_path}")

                except FileNotFoundError as e:
                    logger.error(f"Файл не найден: {file_path} - {e}")
                    await update.callback_query.message.reply_text(f"Файл {os.path.basename(file_path)} не найден.")
                except TelegramError as e:
                    logger.error(f"Ошибка при отправке файла {file_path}: {e}")
                    await update.callback_query.message.reply_text(
                        f"Произошла ошибка при отправке файла {os.path.basename(file_path)}."
                    )
                except Exception as e:
                    logger.error(f"Неожиданная ошибка при отправке файла {file_path}: {e}")
                    await update.callback_query.message.reply_text(
                        f"Произошла непредвиденная ошибка при отправке файла {os.path.basename(file_path)}."
                    )

            # После отправки последнего файла показываем меню и напоминаем о ДЗ
            await show_main_menu(conn, cursor, update, context)

            # Добавляем напоминание о ДЗ
            homework_status = await get_homework_status_text(conn, cursor, user_id, active_course_id_full)
            if update.callback_query:
                await update.callback_query.message.reply_text(f"Напоминаем: {homework_status}")
            else:
                await update.message.reply_text(f"Напоминаем: {homework_status}")

        else:
            if update.callback_query:
                await update.callback_query.message.reply_text("Файлы к этому уроку не найдены.")
            else:
                await update.message.reply_text("Файлы к этому уроку не найдены.")

            await show_main_menu(conn, cursor, update, context)  # Показываем меню, даже если файлов нет
            homework_status = await get_homework_status_text(conn, cursor, user_id, active_course_id_full)
            if update.callback_query:
                await update.callback_query.message.reply_text(f"Напоминаем: {homework_status}")
            else:
                await update.message.reply_text(f"Напоминаем: {homework_status}")

    except Exception as e:  # это часть show_lesson
        logger.error(f"Ошибка при получении материалов урока: {e}")
        if update.callback_query:
            await update.callback_query.message.reply_text("Ошибка при получении материалов урока. Попробуйте позже.")
        else:
            await update.message.reply_text("Ошибка при получении материалов урока. Попробуйте позже.")


# Функция для получения файлов урока ненадо
def get_lesson_files(user_id, lesson_number, course_id):
    """Получает список файлов урока (аудио, видео, изображения) с задержками."""
    logger.info(f"  get_lesson_files {user_id} - {lesson_number=}")
    try:
        # Убедимся, что lesson_number - это целое число
        lesson_number = int(lesson_number)
        lesson_dir = f"courses/{course_id}/"
        files = []

        for filename in os.listdir(lesson_dir):
            if (
                filename.startswith(f"lesson{lesson_number}")
                and os.path.isfile(os.path.join(lesson_dir, filename))
                and not filename.endswith(".txt")
            ):

                file_path = os.path.join(lesson_dir, filename)
                match = DELAY_PATTERN.search(filename)
                delay = 0
                if match:
                    delay_value = int(match.group(1))
                    delay_unit = match.group(2)
                    if delay_unit in ("min", "m"):
                        delay = delay_value * 60  # minutes to seconds
                    elif delay_unit in ("hour", "h"):
                        delay = delay_value * 3600  # hours to seconds

                file_type = "document"  # Default

                if filename.endswith((".jpg", ".jpeg", ".png", ".gif")):
                    file_type = "photo"
                elif filename.endswith((".mp3", ".wav", ".ogg")):
                    file_type = "audio"
                elif filename.endswith((".mp4", ".avi", ".mov")):
                    file_type = "video"

                files.append({"path": file_path, "delay": delay, "type": file_type})

        # Сортируем файлы так, чтобы сначала шли файлы без задержки, потом с наименьшей задержкой
        files.sort(key=lambda x: x["delay"])
        return files

    except FileNotFoundError:
        logger.error(f"Папка с файлами урока не найдена: ")
        return []
    except Exception as e:
        logger.error(f"Ошибка при получении файлов урока: {e}")
        return []


# предварительные задания
async def send_preliminary_material(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Отправляет предварительные материалы для следующего урока."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    logger.info(f"send_preliminary_material ")

    # Получаем active_course_id из users
    cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
    active_course_data = cursor.fetchone()

    if not active_course_data or not active_course_data[0]:
        await query.message.reply_text("Для начала активируйте кодовое слово курса.")
        return

    active_course_id_full = active_course_data[0]
    # Обрезаем название курса до первого символа "_"
    active_course_id = active_course_id_full.split("_")[0]

    # Получаем progress (номер урока) из user_courses
    cursor.execute(
        """
        SELECT progress
        FROM user_courses
        WHERE user_id = ? AND course_id = ?
    """,
        (user_id, active_course_id_full),
    )
    progress_data = cursor.fetchone()

    try:
        if not progress_data:
            await query.message.reply_text("Прогресс курса не найден. Пожалуйста, начните курс сначала.")
            return

        lesson = progress_data[0]
        next_lesson = lesson + 1

        # Получаем список предварительных материалов
        materials = get_preliminary_materials(active_course_id, next_lesson)

        if not materials:
            await query.message.reply_text("Предварительные материалы для следующего урока отсутствуют.")
            return

        # Отправляем материалы
        for material_file in materials:
            material_path = f"courses/{active_course_id}/{material_file}"

            # Определяем тип файла
            try:
                if material_file.endswith((".jpg", ".jpeg", ".png", ".gif")):
                    with open(material_path, "rb") as photo_file:
                        await context.bot.send_photo(chat_id=user_id, photo=photo_file)
                elif material_file.endswith((".mp4", ".avi", ".mov")):
                    with open(material_path, "rb") as video_file:
                        await context.bot.send_video(chat_id=user_id, video=video_file)
                elif material_file.endswith((".mp3", ".wav", ".ogg")):
                    with open(material_path, "rb") as audio_file:
                        await context.bot.send_audio(chat_id=user_id, audio=audio_file)
                else:
                    with open(material_path, "rb") as document_file:
                        await context.bot.send_document(chat_id=user_id, document=document_file)
            except FileNotFoundError:
                logger.error(f"Файл не найден: {material_path}")
                await query.message.reply_text(f"Файл {material_file} не найден.")
            except TelegramError as e:
                logger.error(f"Ошибка при отправке файла {material_file}: {e}")
                await query.message.reply_text(f"Произошла ошибка при отправке файла {material_file}.")
            except Exception as e:
                logger.error(f"Неожиданная ошибка при отправке файла {material_file}: {e}")
                await query.message.reply_text(f"Произошла непредвиденная ошибка при отправке файла {material_file}.")

        await query.message.reply_text("Все предварительные материалы для следующего урока отправлены.")

    except FileNotFoundError:
        logger.error(f"Папка с файлами урока не найдена: {f'courses/{active_course_id}/{material_file}'}")
        return []
    except Exception as e:
        logger.error(f"Ошибка при получении файлов урока: {e}")
        return []


async def handle_go_to_payment(
    conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext, tariff_id: str
):
    """Handles the "Go to Payment" button."""
    query = update.callback_query
    user_id = update.effective_user.id
    logger.info(f"handle_go_to_payment")
    try:
        # Load tariffs from file
        with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
            tariffs = json.load(f)

        # Find selected tariff
        selected_tariff = next((tariff for tariff in tariffs if tariff["id"] == tariff_id), None)

        if selected_tariff:
            logger.info(f"Handling go to payment for tariff: {selected_tariff}")

            # Get payment information
            phone_number = PAYMENT_INFO.get("phone_number")
            name = PAYMENT_INFO.get("name")
            payment_message = PAYMENT_INFO.get("payment_message")
            amount = selected_tariff.get("price")

            if not phone_number or not name or not payment_message or not amount:
                logger.error("Missing payment information.")
                await query.message.reply_text("Произошла ошибка. Не удалось получить информацию об оплате.")
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
            await query.edit_message_text(
                text=f"{formatted_message}\nНомер телефона: {phone_number}\nИмя: {name}",
                reply_markup=reply_markup,
            )
        else:
            logger.warning(f"Tariff with id {tariff_id} not found.")
            await query.message.reply_text("Выбранный тариф не найден.")
    except Exception as e:
        logger.error(f"Error handling go to payment: {e}")
        await query.message.reply_text("Произошла ошибка при переходе к оплате. Попробуйте позже.")


async def handle_buy_tariff(
    conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext, tariff_id: str
):
    """Обрабатывает нажатие на кнопку 'Купить'."""
    query = update.callback_query
    user_id = update.effective_user.id

    logger.info(f"handle_buy_tariff: tariff_id={tariff_id}, user_id={user_id}")

    try:
        # Загружаем тарифы из файла
        try:
            with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
                tariffs = json.load(f)
            logger.info(f"handle_buy_tariff: Tariffs data loaded from {TARIFFS_FILE}")
        except FileNotFoundError:
            logger.error(f"handle_buy_tariff: Файл {TARIFFS_FILE} не найден.")
            await query.message.reply_text("Произошла ошибка: файл с тарифами не найден.")
            return
        except json.JSONDecodeError as e:
            logger.error(f"handle_buy_tariff: Ошибка при чтении JSON из файла {TARIFFS_FILE}: {e}")
            await query.message.reply_text("Произошла ошибка: не удалось прочитать данные о тарифах.")
            return
        except Exception as e:
            logger.error(f"handle_buy_tariff: Непредвиденная ошибка при загрузке тарифов: {e}")
            await query.message.reply_text("Произошла непредвиденная ошибка. Попробуйте позже.")
            return

        # Ищем выбранный тариф
        selected_tariff = next((tariff for tariff in tariffs if tariff["id"] == tariff_id), None)

        if selected_tariff:
            logger.info(f"handle_buy_tariff: Найден тариф: {selected_tariff}")

            # Загружаем информацию об оплате
            payment_info = load_payment_info(PAYMENT_INFO_FILE)

            if not payment_info:
                logger.error("handle_buy_tariff: Не удалось загрузить информацию об оплате.")
                await query.message.reply_text("Произошла ошибка: не удалось получить информацию об оплате.")
                return

            phone_number = payment_info.get("phone_number")
            name = payment_info.get("name")
            payment_message = payment_info.get("payment_message")
            amount = selected_tariff.get("price")

            if not all([phone_number, name, payment_message, amount]):
                logger.error("handle_buy_tariff: Отсутствует необходимая информация для оплаты.")
                await query.message.reply_text("Произошла ошибка: отсутствует необходимая информация для оплаты.")
                return

            # Форматируем сообщение об оплате
            formatted_message = payment_message.format(amount=amount)

            # Создаем кнопки
            keyboard = [
                [InlineKeyboardButton("Я оплатил", callback_data=f"check_payment_{tariff_id}")],
                [InlineKeyboardButton("Назад к тарифам", callback_data="tariffs")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Отправляем сообщение с информацией об оплате
            payment_info_message = (
                f"Для оплаты тарифа '{selected_tariff['title']}' выполните следующие действия:\n\n"
                f"{formatted_message}\n"
                f"Номер телефона: {phone_number}\n"
                f"Имя получателя: {name}\n\n"
                f"После оплаты нажмите кнопку 'Я оплатил'."
            )

            await query.edit_message_text(payment_info_message, reply_markup=reply_markup)
            logger.info(f"handle_buy_tariff: Сообщение об оплате отправлено пользователю {user_id}")
        else:
            logger.warning(f"handle_buy_tariff: Тариф с id '{tariff_id}' не найден.")
            await query.message.reply_text("Выбранный тариф не найден. Пожалуйста, выберите тариф снова.")

    except Exception as e:
        logger.exception(f"handle_buy_tariff: Непредвиденная ошибка при обработке покупки: {e}")
        await query.message.reply_text("Произошла непредвиденная ошибка при обработке покупки. Попробуйте позже.")


async def get_gallery_count(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
):
    """
    Считает количество работ в галерее (реализация зависит от способа хранения галереи).
    """
    cursor.execute('SELECT COUNT(*) FROM homeworks WHERE status = "approved"')
    logger.info(f"get_gallery_count -------------<")
    return cursor.fetchone()[0]


# галерея
async def show_gallery(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    logger.info(f"show_gallery -------------<")
    await get_random_homework(conn, cursor, update, context)


# галерейка
async def get_random_homework(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    query = update.callback_query
    if query:
        await query.answer()
        user_id = query.from_user.id
    else:
        user_id = update.effective_user.id
    logger.info(f"get_random_homework -------------<")
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
        if query:
            await query.edit_message_text("В галерее пока нет работ 😞\nХотите стать первым?")
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text="В галерее пока нет работ 😞\nХотите стать первым?",
            )
        await show_main_menu(conn, cursor, update, context)  # Возвращаем в основное меню
        return

    hw_id, author_id, course_type, lesson, file_id = hw

    # Получаем информацию об авторе
    cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (author_id,))
    author_name = cursor.fetchone()[0] or "Аноним"

    # Формируем текст сообщения
    text = f"📚 Курс: {course_type}\n"
    text += f"📖 Урок: {lesson}\n"
    text += f"👩🎨 Автор: {author_name}\n\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"
    text += "Чтобы увидеть другую работу - нажмите «Следующая»"

    # Создаем клавиатуру
    keyboard = [
        [InlineKeyboardButton("Следующая работа ➡️", callback_data="gallery_next")],
        [InlineKeyboardButton("Вернуться в меню ↩️", callback_data="menu_back")],
    ]

    try:
        # Отправляем файл с клавиатурой
        if query:
            await context.bot.edit_message_media(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                media=InputMediaPhoto(media=file_id, caption=text),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        else:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=file_id,
                caption=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
    except Exception as e:
        # Если не фото, пробуем отправить как документ
        try:
            if query:
                await context.bot.edit_message_media(
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id,
                    media=InputMediaDocument(media=file_id, caption=text),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            else:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=file_id,
                    caption=text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
        except Exception as e:
            logger.error(f"Ошибка отправки работы: {e}")
            await context.bot.send_message(
                chat_id=user_id,
                text="Не удалось загрузить работу 😞",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )


# Обрабатывает нажатия на кнопки все
button_handlers = {
    "get_current_lesson": lambda update, context: get_current_lesson(update, context),
    "gallery": show_gallery,
    "gallery_next": lambda update, context: get_random_homework(update, context),
    "menu_back": lambda update, context: show_main_menu(update, context),
    "support": lambda update, context: show_support(update, context),
    "tariffs": lambda update, context: show_tariffs(update.callback_query.message.chat_id),
    "course_settings": lambda update, context: show_course_settings(update.callback_query.message.chat_id),
}


async def button_handler(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Handles button presses."""
    query = update.callback_query
    data = query.data
    logger.info(f"{update.effective_user.id} - button_handler")
    await query.answer()

    try:
        # Check for tariff selection first
        if data.startswith("tariff_"):
            logger.info(f" 777 данные {data} ==================")
            # Извлекаем tariff_id, разделяя строку только один раз
            tariff_id = data.split("_", 1)[1]
            logger.info(f" handler для handle_tariff_selection {tariff_id}")
            await handle_tariff_selection(update, context, tariff_id)
        elif data.startswith("buy_tariff_"):
            # Handle "Buy" button
            tariff_id = data.split("_", 2)[2]
            logger.info(f" handler для handle_buy_tariff {tariff_id}")
            await handle_buy_tariff(conn, cursor, update, context, tariff_id)
        elif data.startswith("go_to_payment_"):
            # Handle "Go to Payment" button
            tariff_id = data.split("_", 2)[2]
            logger.info(f" handler для handle_go_to_payment {tariff_id}")
            await handle_go_to_payment(update, context, tariff_id)

        elif data.startswith("check_payment_"):
            # Handle "I Paid" button
            try:
                tariff_id = data.split("_", 2)[1]  # Извлекаем tariff_id правильно
                logger.info(f" handler для handle_check_payment {tariff_id}")
            except IndexError:
                logger.error(f"Не удалось извлечь tariff_id из data: {data} ====== 8888")
                await query.message.reply_text("Произошла ошибка. Попробуйте позже.")
                return
            await handle_check_payment(update, context, tariff_id)

        elif data in button_handlers:
            handler = button_handlers[data]
            await handler(update, context)
        else:
            await query.message.reply_text("Unknown command")
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.message.reply_text("Произошла ошибка. Попробуйте позже.")


# выбор товара в магазине *
async def handle_tariff_selection(
    conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext, tariff_id: str
):
    """Handles the selection of a tariff."""
    query = update.callback_query
    user_id = update.effective_user.id
    logger.info(f"  handle_tariff_selection --------------------------------")
    try:
        logger.info(f"333 Handling tariff selection for tariff_id: {tariff_id}")
        with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
            tariffs = json.load(f)

        # Find selected tariff
        selected_tariff = next((tariff for tariff in tariffs if tariff["id"] == tariff_id), None)

        if selected_tariff:
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
            await query.edit_message_text(text=message, reply_markup=reply_markup)
        else:
            logger.warning(f"Tariff 2 with id {tariff_id} not found.")
            await query.message.reply_text("Выбранный 2 тариф не найден.")
    except Exception as e:
        logger.error(f"Error handling tariff selection: {e}")
        await query.message.reply_text("Произошла ошибка при выборе тарифа. Попробуйте позже.")


# Обрабатывает текстовые сообщения. *
async def handle_text_message(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Обрабатывает текстовые сообщения."""
    user_id = update.effective_user.id
    text = update.message.text.lower()  # Приводим текст к нижнему регистру

    # Проверяем, находится ли пользователь в состоянии ожидания кодового слова
    if context.user_data.get("waiting_for_code"):
        return  # Если ждем кодовое слово, игнорируем сообщение
    if "предварительные" in text or "пм" in text:
        await send_preliminary_material(conn, cursor, update, context)
    if "текущий урок" in text or "ту" in text:
        await get_current_lesson(update, context)
    elif "галерея дз" in text or "гдз" in text:
        await show_gallery(conn, cursor, update, context)
    elif "тарифы" in text or "ТБ" in text:
        logger.info(f" тарифы 1652 строка ")
        await show_tariffs(conn, cursor, update, context)
    elif "поддержка" in text or "пд" in text:
        await start_support_request(conn, cursor, update, context)  # Вызываем функцию для начала запроса в поддержку
    else:
        await update.message.reply_text("Я не понимаю эту команду.")


# Отправляет запрос в поддержку администратору. *
async def start_support_request(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Начинает запрос в поддержку."""
    await update.message.reply_text("Пожалуйста, опишите вашу проблему или вопрос. Вы также можете прикрепить фотографию.")
    return WAIT_FOR_SUPPORT_TEXT


# Отправляет запрос в поддержку администратору. *
async def get_support_text(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Получает текст запроса в поддержку."""
    user_id = update.effective_user.id
    text = update.message.text
    context.user_data["support_text"] = text

    logger.info(f" get_support_text  get_support_text {user_id}  {text}  ")

    # Проверяем наличие фотографии
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data["support_photo"] = file_id
    else:
        context.user_data["support_photo"] = None

    await send_support_request_to_admin(update, context)

    return ACTIVE


# Отправляет запрос в поддержку администратору. *
async def send_support_request_to_admin(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Отправляет запрос в поддержку администратору."""
    user_id = update.effective_user.id
    support_text = context.user_data.get("support_text", "No text provided")
    support_photo = context.user_data.get("support_photo")
    logger.info(f"send_support_request_to_admin {user_id}  {support_text}  {support_photo}")
    try:
        # Формируем сообщение для администратора
        caption = f"Новый запрос в поддержку!\nUser ID: {user_id}\nТекст: {support_text}"

        # Отправляем сообщение администратору
        if support_photo:
            await context.bot.send_photo(chat_id=ADMIN_GROUP_ID, photo=support_photo, caption=caption)
        else:
            await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=caption)

        # Увеличиваем счетчик обращений в поддержку
        cursor.execute(
            "UPDATE users SET support_requests = support_requests + 1 WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()

        await update.message.reply_text("Ваш запрос в поддержку отправлен. Ожидайте ответа.")

    except Exception as e:
        logger.error(f"Ошибка при отправке запроса в поддержку администратору: {e}")
        await update.message.reply_text("Произошла ошибка при отправке запроса. Попробуйте позже.")


# Сохраняет имя пользователя и запрашивает кодовое слово *
async def handle_name(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Сохраняет имя пользователя и запрашивает кодовое слово."""
    user_id = update.effective_user.id
    full_name = update.message.text.strip()

    logger.info(f" 333 4 handle_name {user_id}  {full_name}  ")

    # Сохраняем имя пользователя в базе данных
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, full_name) VALUES (?, ?)",
        (user_id, full_name),
    )
    conn.commit()

    # Устанавливаем состояние ожидания кодового слова
    context.user_data["waiting_for_code"] = True

    await update.message.reply_text(f"Отлично, {full_name}! Теперь введите кодовое слово для активации курса.")
    return WAIT_FOR_CODE


def add_tokens(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id: int, amount: int, reason: str):
    """Начисляет жетоны пользователю."""
    try:
        with conn:
            # Обновляем количество жетонов
            cursor = conn.cursor()
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
        logger.info(f"Начислено {amount} жетонов пользователю {user_id} по причине: {reason}")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при начислении жетонов пользователю {user_id}: {e}")
        raise


def spend_tokens(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id: int, amount: int, reason: str):
    """Списывает жетоны у пользователя."""
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


def get_token_balance(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id: int):
    """Возвращает текущий баланс жетонов пользователя."""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
        balance_data = cursor.fetchone()
        return balance_data[0] if balance_data else 0
    except sqlite3.Error as e:
        logger.error(f"Ошибка при получении баланса пользователя {user_id}: {e}")
        return 0


async def show_token_balance(
    conn: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    update: Update,
    context: CallbackContext,
):
    """Показывает баланс жетонов пользователя."""
    user_id = update.effective_user.id
    balance = get_token_balance(conn, user_id)
    await update.message.reply_text(f"У вас {balance} АнтКоинов.")


async def buy_lootbox(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Обрабатывает покупку лутбокса."""
    user_id = update.effective_user.id

    try:
        # Проверяем тип лутбокса
        box_type = context.args[0].lower()  # Например, 'light' или 'full'

        # Стоимость лутбокса
        cost = 1 if box_type == "light" else 3

        # Списываем жетоны
        spend_tokens(conn, user_id, cost, f"purchase_{box_type}_lootbox")

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


def roll_lootbox(conn: sqlite3.Connection, box_type: str):
    """Определяет награду из лутбокса."""
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


async def reminders(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
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
async def set_morning(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Устанавливает утреннее напоминание."""
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



async def disable_reminders(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Отключает все напоминания."""
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



# Create a wrapper function for send_reminders
async def send_reminders_wrapper(context):
    """Wrapper function for send_reminders to provide database connection"""
    logger.info(f" send_reminders_wrapper ")
    conn = sqlite3.connect("bot_db.sqlite", check_same_thread=False)
    cursor = conn.cursor()
    try:
        await send_reminders(conn, cursor, context)
    finally:
        cursor.close()
        conn.close()

async def send_reminders(conn: sqlite3.Connection, cursor: sqlite3.Cursor, context: CallbackContext):
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


# Define a scheduler for sending lessons
scheduler = AsyncIOScheduler()


# тута инициативно шлём уроки *
@handle_telegram_errors
def add_user_to_scheduler(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id: int, time2: datetime, context: CallbackContext):
    """Add user to send_lesson_by_timer with specific time."""
    # Schedule the daily message
    scheduler.add_job(
        send_lesson_by_timer,
        trigger="cron",
        hour=time2.hour,
        minute=time2.minute,
        start_date=datetime.now(),  # Начало выполнения задачи
        kwargs={"user_id": user_id, "context": context},
        id=f"lesson_{user_id}",  # Уникальный ID для задачи
    )


async def stats(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    # Активные пользователи за последние 3 дня
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


async def set_evening(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
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


def parse_delay_from_filename(conn: sqlite3.Connection, cursor: sqlite3.Cursor, filename):
    """
    Извлекает время задержки из имени файла. TODO повторяет функционал get_lesson_files
    Возвращает задержку в секундах или None, если задержка не указана.
    """
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


async def send_file_with_delay(conn: sqlite3.Connection, cursor: sqlite3.Cursor, context: CallbackContext):
    """
    Отправляет файл с задержкой.
    """
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    file_path = job_data["file_path"]
    file_name = job_data["file_name"]

    try:
        await send_file(context.bot, chat_id, file_path, file_name)
    except Exception as e:
        logger.error(f"Ошибка при отправке файла с задержкой: {e}")


async def send_file(conn: sqlite3.Connection, cursor: sqlite3.Cursor, bot, chat_id, file_path, file_name):
    """
    Отправляет файл пользователю.
    """
    try:
        if file_name.lower().endswith((".jpg", ".jpeg", ".png")):
            with open(file_path, "rb") as photo:
                await bot.send_photo(chat_id=chat_id, photo=photo)
        elif file_name.lower().endswith(".mp4"):
            with open(file_path, "rb") as video:
                await bot.send_video(chat_id=chat_id, video=video)
        elif file_name.lower().endswith(".mp3"):
            with open(file_path, "rb") as audio:
                await bot.send_audio(chat_id=chat_id, audio=audio)
        else:
            with open(file_path, "rb") as document:
                await bot.send_document(chat_id=chat_id, document=document, filename=file_name)  # Передаём имя файла
    except FileNotFoundError:
        logger.error(f"Файл не найден: {file_path}")
    except Exception as e:
        logger.error(f"Ошибка при отправке файла {file_name}: {e}")
        await bot.send_message(chat_id=chat_id, text=f"Не удалось загрузить файл {file_name}.")


# Qwen 15 марта Замена get_lesson_after_code
async def get_lesson_after_code(
    conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext, course_type: str
):
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
async def send_lesson_by_timer(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id: int, context: CallbackContext):
    """Send lesson to users by timer."""
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


async def show_homework(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    lesson_number = query.data.split("_")[1]
    await query.edit_message_text(f"Здесь будет галерея ДЗ по {lesson_number} уроку")


# Функция для получения предварительных материалов строго ненадо  conn: sqlite3.Connection, cursor: sqlite3.Cursor,
def get_preliminary_materials(course_id, lesson):
    """
    Возвращает список всех предварительных материалов для урока.
    """
    lesson_dir = f"courses/{course_id}/"
    materials = []
    for filename in os.listdir(lesson_dir):
        if filename.startswith(f"lesson{lesson}_p") and os.path.isfile(os.path.join(lesson_dir, filename)):
            materials.append(filename)
    materials.sort()  # Сортируем по порядку (p1, p2, ...)
    return materials


# проверим скока уроков всего строго ненадо conn: sqlite3.Connection, cursor: sqlite3.Cursor,
def check_last_lesson(active_course_id):
    """Checking amount of lessons"""
    logger.info(f"check_last_lesson {active_course_id=}")
    dir_path = f"courses/{active_course_id}"
    count = 0
    try:
        for path in os.listdir(dir_path):
            # check if current path
            if os.path.isfile(os.path.join(dir_path, path)):
                count += 1
    except Exception as e:
        logger.error(f"Error during checking  {e=}")
    logger.warning(f"{count=}")
    return count


# Обработчик кнопки "Получить предварительные материалы"
async def send_preliminary_material(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Отправляет предварительные материалы для следующего урока."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        # Получаем active_course_id из users
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await query.message.reply_text("Активируйте курс через кодовое слово.")
            return

        active_course_id_full = active_course_data[0]
        # Обрезаем название курса до первого символа "_"
        active_course_id = active_course_id_full.split("_")[0]

        # Получаем progress (номер урока) из user_courses
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
            await query.message.reply_text("Не найден прогресс курса. Пожалуйста, начните курс сначала.")
            return

        lesson = progress_data[0]
        next_lesson = lesson + 1

        # Получаем список предварительных материалов
        materials = get_preliminary_materials(active_course_id, next_lesson)

        if not materials:
            await query.message.reply_text("Предварительные материалы для следующего урока отсутствуют.")
            return

        # Отправляем материалы
        for material_file in materials:
            material_path = f"courses/{active_course_id}/{material_file}"

            # Определяем тип файла
            try:
                if material_file.endswith((".jpg", ".jpeg", ".png", ".gif")):
                    with open(material_path, "rb") as photo_file:
                        await context.bot.send_photo(chat_id=user_id, photo=photo_file)
                elif material_file.endswith((".mp4", ".avi", ".mov")):
                    with open(material_path, "rb") as video_file:
                        await context.bot.send_video(chat_id=user_id, video=video_file)
                elif material_file.endswith((".mp3", ".wav", ".ogg")):
                    with open(material_path, "rb") as audio_file:
                        await context.bot.send_audio(chat_id=user_id, audio=audio_file)
                else:
                    with open(material_path, "rb") as document_file:
                        await context.bot.send_document(chat_id=user_id, document=document_file)
            except FileNotFoundError:
                logger.error(f"Файл не найден: {material_path}")
                await query.message.reply_text(f"Файл {material_file} не найден.")
            except TelegramError as e:
                logger.error(f"Ошибка при отправке файла {material_file}: {e}")
                await query.message.reply_text(f"Произошла ошибка при отправке файла {material_file}.")
            except Exception as e:
                logger.error(f"Неожиданная ошибка при отправке файла {material_file}: {e}")
                await query.message.reply_text(f"Произошла непредвиденная ошибка при отправке файла {material_file}.")

        await query.message.reply_text("Все предварительные материалы для следующего урока отправлены.")

    except Exception as e:
        logger.error(f"Ошибка при отправке предварительных материалов: {e}")
        await query.message.reply_text("Произошла ошибка при отправке предварительных материалов. Попробуйте позже.")


# Функция для добавления кнопки "Получить предварительные материалы"
async def add_preliminary_button(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id, course_type):
    # Извлекаем префикс курса (main/auxiliary)
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


def get_average_homework_time(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id):
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


async def handle_admin_approval(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    query = update.callback_query
    logger.info(f" handle_admin_approval {update.effective_user.id} -{query}")
    await query.answer()

    data = query.data.split("_")
    action = data[1]
    hw_id = data[2]

    if action == "approve":
        # Запрашиваем комментарий у админа
        await query.message.reply_text("Введите комментарий к домашней работе:")
        context.user_data["awaiting_comment"] = hw_id
        context.user_data["approval_status"] = "approved"  # Сохраняем статус
    elif action == "reject":
        # Запрашиваем комментарий у админа
        await query.message.reply_text("Введите комментарий к домашней работе:")
        context.user_data["awaiting_comment"] = hw_id
        context.user_data["approval_status"] = "rejected"  # Сохраняем статус

    else:
        await query.message.reply_text("Неизвестное действие.")


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
async def tariff_callback(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
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


# Обрабатывает нажатие кнопки "Купить" *
async def buy_tariff(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Обрабатывает нажатие кнопки "Купить"."""
    query = update.callback_query
    await query.answer()
    tariff = context.user_data.get("tariff")
    logger.info(f"buy_tariff  555555 666 tariff={tariff}")
    context.user_data["tariff_id"] = tariff["id"]  # Сохраняем tariff_id
    if tariff["type"] == "discount":
        await query.message.reply_text(
            "Для получения скидки отправьте селфи и короткое описание, почему вы хотите получить эту скидку:"
        )
        return WAIT_FOR_SELFIE

    # Инструкция по оплате
    text = f"Для приобретения акции, пожалуйста, переведите {tariff['price']} рублей на номер [номер] и загрузите чек сюда в этот диалог."  # Замените [сумма] и [номер]
    await query.message.reply_text(text)
    await query.message.reply_text(
        "Пожалуйста, поделитесь своим номером телефона:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("Поделиться номером телефона", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    return WAIT_FOR_PHONE_NUMBER


# Обрабатывает нажатие кнопки "В подарок" *
async def gift_tariff(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Обрабатывает нажатие кнопки "В подарок"."""
    query = update.callback_query
    await query.answer()
    tariff = context.user_data.get("tariff")
    logger.info(f"gift_tariff  555555 tariff={tariff}  0000000000")
    if tariff["type"] == "discount":
        await query.message.reply_text("Подарочные сертификаты со скидками недоступны. Выберите другой тариф.")
        return ConversationHandler.END

    context.user_data["tariff_id"] = tariff["id"]  # Сохраняем tariff_id

    await query.message.reply_text("Введите user ID получателя подарка:")
    return WAIT_FOR_GIFT_USER_ID


# Добавляет купленный курс пользователю. *
async def add_purchased_course(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id, tariff_id, context: CallbackContext):
    """Добавляет купленный курс пользователю."""
    logger.info(f"add_purchased_course 555555")
    try:
        # Проверяем, есть ли уже такой курс у пользователя
        cursor.execute(
            """
            SELECT * FROM user_courses
            WHERE user_id = ? AND course_id = ?
        """,
            (user_id, tariff_id),
        )
        existing_course = cursor.fetchone()

        if existing_course:
            await context.bot.send_message(user_id, "Этот курс уже есть в вашем профиле.")
            return

        # Получаем данные о курсе из tariffs.json
        tariffs = load_tariffs()
        tariff = next((t for t in tariffs if t["id"] == tariff_id), None)

        if not tariff:
            logger.error(f"Тариф с id {tariff_id} не найден в tariffs.json")
            await context.bot.send_message(user_id, "Произошла ошибка при добавлении курса. Попробуйте позже.")
            return

        course_type = tariff.get("course_type", "main")  # Получаем тип курса из tariff
        tariff_name = tariff_id.split("_")[1] if len(tariff_id.split("_")) > 1 else "default"

        # Добавляем курс в user_courses
        cursor.execute(
            """
            INSERT INTO user_courses (user_id, course_id, course_type, progress, tariff)
            VALUES (?, ?, ?, ?, ?)
        """,
            (user_id, tariff_id, course_type, 1, tariff_name),
        )  # Начинаем с progress = 1
        conn.commit()

        # Обновляем active_course_id в users
        cursor.execute(
            """
            UPDATE users
            SET active_course_id = ?
            WHERE user_id = ?
        """,
            (tariff_id, user_id),
        )
        conn.commit()

        logger.info(f"Курс {tariff_id} добавлен пользователю {user_id}")
        await context.bot.send_message(user_id, "Новый курс был добавлен вам в профиль.")

    except Exception as e:
        logger.error(f"Ошибка при добавлении курса пользователю {user_id}: {e}")
        await context.bot.send_message(user_id, "Произошла ошибка при добавлении курса. Попробуйте позже.")


# Отклоняет скидку администратором. *
async def show_stats(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Показывает статистику для администратора."""
    logger.info(f"show_stats <")
    try:
        # Получаем количество пользователей
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]

        # Получаем количество активных курсов
        cursor.execute("SELECT COUNT(DISTINCT course_id) FROM user_courses")
        course_count = cursor.fetchone()[0]

        # Формируем сообщение
        text = f"📊 Статистика:\n\n" f"👥 Пользователей: {user_count}\n" f"📚 Активных курсов: {course_count}"

        await update.message.reply_text(text)

    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        await update.message.reply_text("Произошла ошибка при получении статистики.")


# Отклоняет скидку администратором.*
async def admin_approve_discount(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
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
async def admin_reject_discount(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
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
async def admin_approve_purchase(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Подтверждает покупку админом."""
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
async def admin_reject_purchase(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
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
async def process_selfie(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Обрабатывает селфи для получения скидки."""
    user_id = update.effective_user.id
    tariff = context.user_data.get("tariff")

    photo = update.message.photo[-1]
    file_id = photo.file_id
    context.user_data["selfie_file_id"] = file_id

    await update.message.reply_text("Теперь отправьте описание, почему вы хотите получить эту скидку:")
    return WAIT_FOR_DESCRIPTION


# Обрабатывает описание для получения скидки.*
async def process_description(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
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
    return ConversationHandler.END


# Обрабатывает загруженный чек *
async def process_check(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Обрабатывает загруженный чек."""
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

    await update.message.reply_text("Чек отправлен на проверку администраторам. Ожидайте подтверждения.")
    context.user_data.clear()  # Очищаем context.user_data
    return ConversationHandler.END


# Обрабатывает User ID получателя подарка. *
async def process_gift_user_id(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
    """Обрабатывает User ID получателя подарка."""
    gift_user_id = update.message.text
    logger.info(f"process_gift_user_id  {gift_user_id} -------------<")

    if not gift_user_id.isdigit():
        await update.message.reply_text("Пожалуйста, введите корректный User ID, состоящий только из цифр.")
        return WAIT_FOR_GIFT_USER_ID

    context.user_data["gift_user_id"] = gift_user_id
    user_id = update.effective_user.id
    tariff = context.user_data.get("tariff")
    # Инструкция по оплате
    text = f"Для оформления подарка, пожалуйста, переведите {tariff['price']} рублей на номер [номер] и загрузите чек сюда в этот диалог."  # Замените [сумма] и [номер]
    await update.message.reply_text(text)
    return WAIT_FOR_CHECK


# просим номерок *
async def process_phone_number(conn: sqlite3.Connection, cursor: sqlite3.Cursor, update: Update, context: CallbackContext):
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
    context.user_data.clear()  # Очищаем context.user_data
    return ConversationHandler.END


async def get_next_lesson_time(conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id):
    """Получает время следующего урока из базы данных."""
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
                next_lesson_time = datetime.datetime.strptime(next_lesson_time_str, "%Y-%m-%d %H:%M:%S")
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


def setup_admin_commands(application):
    """Настраивает команды администратора."""
    application.add_handler(CommandHandler("stats", show_stats))
    application.add_handler(CallbackQueryHandler(admin_approve_purchase, pattern="^admin_approve_purchase_"))
    application.add_handler(CallbackQueryHandler(admin_reject_purchase, pattern="^admin_reject_purchase_"))
    application.add_handler(CallbackQueryHandler(admin_approve_discount, pattern="^admin_approve_discount_"))
    application.add_handler(CallbackQueryHandler(admin_reject_discount, pattern="^admin_reject_discount_"))


def setup_user_commands(application):
    """Настраивает команды пользователя."""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_main_menu))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(CallbackQueryHandler(tariff_callback, pattern="^tariff_"))

    # лутбоксы
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


def main():
    # Создание таблиц
    # Инициализация БД
    conn = sqlite3.connect("bot_db.sqlite", check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL DEFAULT 'ЧЕБУРАШКА',
                penalty_task TEXT,
                preliminary_material_index INTEGER DEFAULT 0,
                tariff TEXT,
                continuous_flow BOOLEAN DEFAULT 0,
                next_lesson_time DATETIME,
                active_course_id TEXT,
                user_code TEXT,
                support_requests INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS homeworks (
                hw_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                course_id TEXT,  
                lesson INTEGER,
                file_id TEXT,
                message_id INTEGER,
                status TEXT DEFAULT 'pending',
                feedback TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                lesson_sent_time DATETIME,
                first_submission_time DATETIME,
                submission_time DATETIME,
                approval_time DATETIME,
                final_approval_time DATETIME,
                admin_comment TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS user_tokens (
                user_id INTEGER PRIMARY KEY,
                tokens INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT, -- 'earn' или 'spend'
                amount INTEGER,
                reason TEXT, -- Например, 'registration', 'referral', 'lootbox'
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS lootboxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                box_type TEXT, -- 'light' или 'full'
                reward TEXT, -- Награда (например, 'скидка', 'товар')
                probability REAL -- Вероятность выпадения
            );

            CREATE TABLE IF NOT EXISTS admins (
                admin_id INTEGER PRIMARY KEY,
                level INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS admin_codes (
                code_id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                code TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
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

            CREATE TABLE IF NOT EXISTS user_courses (
                user_id INTEGER,
                course_id TEXT,
                course_type TEXT CHECK(course_type IN ('main', 'auxiliary')),
                progress INTEGER DEFAULT 0,
                purchase_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                tariff TEXT,
                PRIMARY KEY (user_id, course_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            """
        )
        conn.commit()
        logger.info("База данных успешно создана.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при создании базы данных: {e}")

    with conn:
        for admin_id in ADMIN_IDS:
            try:
                admin_id = int(admin_id)
                cursor.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (admin_id,))
                conn.commit()
                logger.info(f"Администратор с ID {admin_id} добавлен.")
            except ValueError:
                logger.warning(f"Некорректный ID администратора: {admin_id}")

    init_lootboxes(conn, cursor)

    application = ApplicationBuilder().token(TOKEN).persistence(persistence).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAIT_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_info)],
            WAIT_FOR_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code_words)],
            ACTIVE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message),
                CallbackQueryHandler(button_handler),
                MessageHandler(filters.Document.IMAGE | filters.PHOTO, handle_homework_submission),
                CallbackQueryHandler(self_approve_homework, pattern=r"^self_approve_\d+$"),
                CallbackQueryHandler(approve_homework, pattern=r"^approve_homework_\d+_\d+$"),
                CommandHandler("self_approve", self_approve_homework),
            ],
            WAIT_FOR_SUPPORT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND | filters.PHOTO, get_support_text)],
            WAIT_FOR_SELFIE: [MessageHandler(filters.PHOTO, process_selfie)],
            WAIT_FOR_DESCRIPTION: [MessageHandler(filters.TEXT, process_description)],
            WAIT_FOR_CHECK: [MessageHandler(filters.PHOTO, process_check)],  # вот тут ждём чек
            WAIT_FOR_GIFT_USER_ID: [MessageHandler(filters.TEXT, process_gift_user_id)],
            WAIT_FOR_PHONE_NUMBER: [MessageHandler(filters.CONTACT, process_phone_number)],
        },
        fallbacks=[],
        persistent=True,  # Включаем персистентность
        name="my_conversation",
        allow_reentry=True,
    )
    application.add_handler(conv_handler)

    setup_user_commands(application)
    setup_admin_commands(application)

    # Обработчик для кнопок предварительных материалов
    application.add_handler(CallbackQueryHandler(send_preliminary_material, pattern="^preliminary_"))

    application.job_queue.run_repeating(send_reminders_wrapper, interval=60, first=10)  # Проверка каждую минуту
    application.add_handler(CommandHandler("reminders", reminders))
    application.add_handler(CommandHandler("set_morning", set_morning))
    application.add_handler(CommandHandler("set_evening", set_evening))
    application.add_handler(CommandHandler("disable_reminders", disable_reminders))
    application.add_handler(CommandHandler("stats", stats))

    application.add_handler(CallbackQueryHandler(button_handler))

    # Start the scheduler
    scheduler.start()

    application.run_polling()


if __name__ == "__main__":
    main()
