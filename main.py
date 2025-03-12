import logging
import time

from telegram.ext import PicklePersistence
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaDocument, \
    KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext, \
    CallbackQueryHandler, ConversationHandler
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import re
import asyncio
from telegram.error import TelegramError
import datetime
import json


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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

COURSE_DATA_FILE = "courses.json"

TARIFFS_FILE = "tariffs.json"

def load_course_data(filename):
    """Загружает данные о курсах из JSON файла."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
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

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
ADMIN_IDS = os.getenv("ADMIN_IDS").split(',')

# персистентность
persistence = PicklePersistence(filepath="bot_data.pkl")

# Состояния
(
    WAIT_FOR_NAME,
    WAIT_FOR_CODE,
    ACTIVE,
    HOMEWORK_RESPONSE,
    COURSE_SETTINGS,
    WAIT_FOR_SUPPORT_TEXT,
    WAIT_FOR_SELFIE,
    WAIT_FOR_DESCRIPTION,
    WAIT_FOR_CHECK,
    WAIT_FOR_GIFT_USER_ID,
    WAIT_FOR_PHONE_NUMBER
) = range(11)




# Регулярное выражение для извлечения времени задержки из имени файла
DELAY_PATTERN = re.compile(r"_(\d+)([mh])$")

# Интервал между уроками по умолчанию (в часах)
DEFAULT_LESSON_INTERVAL = 0.3 # интервал уроков 72 часа

DEFAULT_LESSON_DELAY_HOURS = 3

logger.info(f"{DEFAULT_LESSON_DELAY_HOURS=} {DEFAULT_LESSON_INTERVAL=} время старта {time.strftime('%d/%m/%Y %H:%M:%S')}")

# клавиатурка главного меню *
async def create_main_menu_keyboard(user_id, active_course_id):
    """Создает клавиатуру главного меню."""
    inline_keyboard = [
        [InlineKeyboardButton("Следующий урок", callback_data="next_lesson")],
        [InlineKeyboardButton("Профиль", callback_data="profile")],
        [InlineKeyboardButton("Галерея", callback_data="gallery")],
        [InlineKeyboardButton("Поддержка", callback_data="support")],
        [InlineKeyboardButton("Настройки курса", callback_data="course_settings")],  # Добавляем кнопку настроек
    ]
    return inline_keyboard

# получение имени и проверка *
async def handle_user_info(update: Update, context: CallbackContext):
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
        cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,))
        saved_name = cursor.fetchone()[0]

        if saved_name != full_name:
            logger.error(f"Имя не совпадает с сохраненным {saved_name} != {full_name}")
            print(f"Имя не совпадает с сохраненным {saved_name} != {full_name}")

        # Успешное сохранение, переход к следующему шагу
        await update.effective_message.reply_text(
            f"Отлично, {full_name}! Теперь введите кодовое слово для активации курса."
        )
        return WAIT_FOR_CODE

    except Exception as e:
        # Обработка ошибок при сохранении имени
        logger.error(f"Ошибка при сохранении имени: {e}")
        logger.error(f"Ошибка SQL при сохранении пользователя {user_id}: {e}")
        await update.effective_message.reply_text(
            "Произошла ошибка при сохранении данных. Попробуйте снова."
        )
        return WAIT_FOR_NAME

# проверка оплаты через кодовые слова *
async def handle_code_words(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_code = update.message.text.strip()

    # Логирование текущего состояния пользователя
    logger.info(f" handle_code_words {user_id} - Current state")

    if user_code in COURSE_DATA:
        # Активируем курс
        await activate_course(update, context, user_id, user_code)

        # Отправляем текущий урок
        await get_current_lesson(update, context)

        # Отправляем сообщение
        await update.message.reply_text("Курс активирован! Вы переходите в главное меню.")

        # Показываем главное меню
        await show_main_menu(update, context)

        # Сбрасываем состояние ожидания кодового слова
        context.user_data['waiting_for_code'] = False

        return ACTIVE  # Переходим в состояние ACTIVE

    # Неверное кодовое слово
    await update.message.reply_text("Неверное кодовое слово. Попробуйте еще раз.")
    return WAIT_FOR_CODE


# текущий урок заново
async def get_current_lesson(update: Update, context: CallbackContext):
    """Отправляет все материалы текущего урока."""
    user_id = update.effective_user.id
    logger.info(f" get_current_lesson {user_id} - Current state")

    try:
        # Получаем active_course_id из users
        cursor.execute('SELECT active_course_id FROM users WHERE user_id = ?', (user_id,))
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
        active_course_id = active_course_id_full.split('_')[0]
        logger.info(f" active_course_id {active_course_id} +")

        # Получаем progress (номер урока) из user_courses
        cursor.execute('''
            SELECT progress
            FROM user_courses
            WHERE user_id = ? AND course_id = ?
        ''', (user_id, active_course_id_full))
        progress_data = cursor.fetchone()

        # Если progress не найден, начинаем с первого урока и создаем запись
        if not progress_data:
            lesson = 1
            cursor.execute('''
                INSERT INTO user_courses (user_id, course_id, course_type, progress, tariff)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, active_course_id_full, 'main', lesson, 'self_check'))  # Замени 'main' и 'self_check' на актуальные значения
            conn.commit()
            # Используем callback_query, если это callback
            if update.callback_query:
                await update.callback_query.message.reply_text("Вы начинаете курс с первого урока.")
            else:
                await update.message.reply_text("Вы начинаете курс с первого урока.")
        else:
            lesson = progress_data[0]

        # Формируем путь к файлу урока
        file_path = os.path.join("courses", active_course_id, f"lesson{lesson}.txt")
        logger.warning(f" 7777777 Файл урока {file_path=}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lesson_text = f.read()
            # Используем callback_query, если это callback
            if update.callback_query:
                await update.callback_query.message.reply_text(lesson_text)
            else:
                await update.message.reply_text(lesson_text)

        except FileNotFoundError:
            logger.error(f"Файл урока не найден: {file_path}")
            # Используем callback_query, если это callback
            if update.callback_query:
                await update.callback_query.message.reply_text(f"Файл урока не найден. Возможно, это последний урок.")
            else:
                await update.message.reply_text(f"Файл урока не найден. Возможно, это последний урок.")
            return

    except Exception as e:
        logger.error(f"Ошибка при получении текущего урока: {e}")
        # Используем callback_query, если это callback
        if update.callback_query:
            await update.callback_query.message.reply_text("Ошибка при получении текущего урока. Попробуйте позже.")
        else:
            await update.message.reply_text("Ошибка при получении текущего урока. Попробуйте позже.")





# менюшечка *
async def show_main_menu(update: Update, context: CallbackContext):
    user = update.effective_user
    logger.info(f"{user} - show_main_menu")

    try:  # Получаем данные о курсе
        # Получаем active_course_id из users
        cursor.execute('SELECT active_course_id FROM users WHERE user_id = ?', (user.id,))
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
        active_course_id = active_course_id_full.split('_')[0]
        active_tariff = active_course_id_full.split('_')[1] if len(active_course_id_full.split('_')) > 1 else "default"
        # Получаем данные курса из user_courses
        cursor.execute('''
            SELECT course_type, progress
            FROM user_courses
            WHERE user_id = ? AND course_id = ?
        ''', (user.id, active_course_id_full))
        course_type, progress = cursor.fetchone()

        # Получаем времена уведомлений из user_settings
        cursor.execute('SELECT morning_notification, evening_notification FROM user_settings WHERE user_id = ?',
                       (user.id,))
        settings = cursor.fetchone()
        morning_time = settings[0] if settings else "Не установлено"
        evening_time = settings[1] if settings else "Не установлено"

        # Формируем приветствие
        cursor.execute('SELECT full_name FROM users WHERE user_id = ?', (user.id,))
        full_name = cursor.fetchone()[0]
        greeting = f"""Привет, {full_name.split()[0]}!
        Курс: {active_course_id} ({course_type}) {active_tariff}
        Прогресс: урок {progress}
        Домашнее задание: {await get_homework_status_text(user.id, active_course_id_full)}"""

        # Создаем кнопки с эмоджи и в одном ряду
        keyboard = [
            [
                InlineKeyboardButton("📚 Текущий Урок", callback_data='get_current_lesson'),
                InlineKeyboardButton("🖼 Галерея ДЗ", callback_data='gallery')
            ],
            [
                InlineKeyboardButton(f"⚙️ Настройка Курса ({morning_time}, {evening_time})",
                                     callback_data='course_settings')
            ],
            [
                InlineKeyboardButton("💰 Тарифы и Бонусы", callback_data='tariffs'),
                InlineKeyboardButton("🙋‍♂️ ПоДдержка", callback_data='support')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Отправляем меню
        # Используем callback_query, если это callback
        if update.callback_query:
            await update.callback_query.message.reply_text(greeting, reply_markup=reply_markup)
        else:
            await update.message.reply_text(greeting, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"время {time.strftime('%H:%M:%S')} Ошибка в show_main_menu: {str(e)}")
        # Используем callback_query, если это callback
        if update.callback_query:
            await update.callback_query.message.reply_text("Ошибка отображения меню. Попробуйте позже.")
        else:
            await update.message.reply_text("Ошибка отображения меню. Попробуйте позже.")




# домашка ???
async def get_homework_status_text(user_id, course_id):
    cursor.execute('''
        SELECT hw_id, lesson, status 
        FROM homeworks 
        WHERE user_id = ? AND course_id = ? AND status = 'pending'
    ''', (user_id, course_id))
    pending_hw = cursor.fetchone()
    logger.info(f"  get_homework_status_text  {user_id=} {course_id=}  pending_hw={pending_hw}- get_homework_status_text")
    if pending_hw:
        hw_id, lesson, status = pending_hw
        return f"есть домашка по {lesson} уроку"
    else:
        return "домашек нет"


# НАЧАЛО *
async def start(update: Update, context: CallbackContext):
    """Обрабатывает команду /start."""
    user_id = update.effective_user.id

    # Логирование команды /НАЧАЛО
    logger.info(f"  start {user_id} - НАЧАЛО")

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

        # Если пользователь не найден, запрашиваем имя
        if not user_data:
            await update.effective_message.reply_text("Пожалуйста, введите ваше имя:")
            context.user_data['waiting_for_name'] = True  # Устанавливаем состояние ожидания имени
            return WAIT_FOR_NAME
        else:
            # Проверяем, есть ли активный курс
            cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
            active_course = cursor.fetchone()[0]

            # Если курсы не активированы, запрашиваем кодовое слово
            if not active_course:
                await update.effective_message.reply_text(
                    "Для начала введите кодовое слово вашего курса:"
                )
                context.user_data['waiting_for_code'] = True  # Устанавливаем состояние ожидания кодового слова
                return WAIT_FOR_CODE
            else:
                # Если курсы активированы, показываем главное меню
                await show_main_menu(update, context)
                return ACTIVE  # Переходим в состояние ACTIVE
    except Exception as e:
        logger.error(f"Ошибка в функции НАЧАЛО start: {e}")
        await update.effective_message.reply_text(
            "Произошла ошибка. Попробуйте позже."
        )
        return ConversationHandler.END

# проверка активации курсов *
async def activate_course(update: Update, context: CallbackContext, user_id, user_code):
    """Активирует курс для пользователя."""

    # Получаем данные о курсе из COURSE_DATA по кодовому слову
    course = COURSE_DATA[user_code]
    course_id_full = course.course_id  # Полное название курса (например, femininity_premium)
    course_id = course_id_full.split('_')[0]  # Базовое название курса (например, femininity)
    course_type = course.course_type  # 'main' или 'auxiliary'
    tariff = course_id_full.split('_')[1] if len(course_id_full.split('_')) > 1 else "default"  # Тариф (premium, self_check и т.д.)

    try:
        # Проверяем, есть ли уже какой-то курс с таким базовым названием у пользователя
        cursor.execute('''
            SELECT course_id, tariff FROM user_courses
            WHERE user_id = ? AND course_id LIKE ?
        ''', (user_id, f'{course_id}%'))
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
                cursor.execute('''
                    UPDATE user_courses
                    SET course_id = ?, tariff = ?
                    WHERE user_id = ? AND course_id = ?
                ''', (course_id_full, tariff, user_id, existing_course_id))
                conn.commit()
                await update.message.reply_text(f"Вы перешли с тарифа {existing_tariff} на тариф {tariff}.")

                # Обновляем active_course_id в users
                cursor.execute('''
                    UPDATE users
                    SET active_course_id = ?
                    WHERE user_id = ?
                ''', (course_id_full, user_id))
                conn.commit()
                logger.info(f"Обновлен тариф пользователя {user_id} с {existing_tariff} на {tariff} для курса {course_id}")

                return  # Важно: завершаем функцию после обновления
        else:
            # Курса с таким базовым названием еще нет - создаем новый
            cursor.execute('''
                INSERT INTO user_courses (user_id, course_id, course_type, progress, tariff)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, course_id_full, course_type, 1, tariff))
            conn.commit()

            await update.message.reply_text(f"Курс {course_id} ({tariff}) активирован!")

            # Обновляем active_course_id в users
            cursor.execute('''
                UPDATE users
                SET active_course_id = ?
                WHERE user_id = ?
            ''', (course_id_full, user_id))
            conn.commit()
            logger.info(f"Курс {course_id} типа {course_type} активирован для пользователя {user_id} с тарифом {tariff}")

    except Exception as e:
        logger.error(f"Ошибка при активации или обновлении курса для пользователя {user_id}: {e}")
        await update.message.reply_text("Произошла ошибка при активации курса. Попробуйте позже.")

# отправлять урок, читать текст урока из файла и обновлять номер текущего урока в базе данных *
async def send_lesson(update: Update, context: CallbackContext, course_id: str):
    """
    Отправляет пользователю следующий урок.
    """
    user = update.effective_user
    logger.info(f"  send_lesson {user} - ")
    try:
        # Получаем информацию о курсе из user_courses
        cursor.execute('''
            SELECT course_type, progress 
            FROM user_courses 
            WHERE user_id = ? AND course_id = ?
        ''', (user.id, course_id))
        course_data = cursor.fetchone()

        if not course_data:
            await context.bot.send_message(chat_id=user.id, text="Ошибка: Курс не найден.")
            return

        course_type, current_lesson = course_data
        next_lesson = current_lesson + 1

        # Получаем текст следующего урока
        lesson_text = get_lesson_text(user.id, next_lesson, course_id)
        if not lesson_text:
            await context.bot.send_message(chat_id=user.id, text="Урок не найден. Возможно, это последний урок.")
            return

        # Отправляем урок
        await context.bot.send_message(chat_id=user.id, text=lesson_text)

        # Обновляем номер текущего урока в базе данных
        cursor.execute('''
            UPDATE user_courses 
            SET progress = ? 
            WHERE user_id = ? AND course_id = ?
        ''', (next_lesson, user.id, course_id))
        conn.commit()

        # Обновляем информацию о следующем уроке
        await update_next_lesson_time(user.id, course_id)

        logger.info(f"Пользователю {user.id} отправлен урок {next_lesson} курса {course_id}")

    except Exception as e:
        logger.error(f"Ошибка при отправке урока: {e}")
        await context.bot.send_message(chat_id=user.id, text="Произошла ошибка при отправке урока. Попробуйте позже.")

# читать текст урока из файла *
def get_lesson_text(user_id, lesson_number, course_id):
    """Получает текст урока из файла."""
    logger.info(f"  get_lesson_text {user_id} - lesson_number {lesson_number}")
    try:
        # Убедимся, что lesson_number - это целое число
        lesson_number = int(lesson_number)

        filepath = f'courses/{course_id}/lesson{lesson_number}.txt'
        with open(filepath, 'r', encoding='utf-8') as file:
            return file.read()

    except FileNotFoundError:
        logger.error(f" 88888888 Файл урока не найден: {filepath}")
        return None
    except Exception as e:
        logger.error(f"Ошибка при чтении файла урока: {e}")
        return None


# вычисляем время следующего урока *
async def update_next_lesson_time(user_id, course_id):
    """Обновляет время следующего урока для пользователя."""
    try:
        # Получаем текущее время
        now = datetime.datetime.now()

        # Вычисляем время следующего урока
        next_lesson_time = now + datetime.timedelta(hours=DEFAULT_LESSON_DELAY_HOURS)
        next_lesson_time_str = next_lesson_time.strftime('%Y-%m-%d %H:%M:%S')

        # Обновляем время в базе данных
        cursor.execute('''
            UPDATE users 
            SET next_lesson_time = ? 
            WHERE user_id = ?
        ''', (next_lesson_time_str, user_id))
        conn.commit()

        logger.info(f"Для пользователя {user_id} установлено время следующего урока: {next_lesson_time_str}")

    except Exception as e:
        logger.error(f"Ошибка при обновлении времени следующего урока: {e}")

# управление курсом и КНОПОЧКИ СВОИ *
async def course_management(update: Update, context: CallbackContext):
    """Управление курсом."""
    user_id = update.effective_user.id
    logger.info(f" 445566 course_management {user_id}")

    # Получаем active_course_id из базы данных
    cursor.execute('''
        SELECT active_course_id
        FROM users
        WHERE user_id = ?
    ''', (user_id,))
    active_course_data = cursor.fetchone()

    if not active_course_data or not active_course_data[0]:
        await update.message.reply_text("У вас не активирован ни один курс.")
        return

    active_course_id = active_course_data[0]

    # Формируем кнопки
    keyboard = [
        [InlineKeyboardButton("Сменить тариф", callback_data="change_tariff")],
        [InlineKeyboardButton("Мои курсы", callback_data="my_courses")],
        [InlineKeyboardButton("История ДЗ", callback_data="hw_history")]
    ]
    await update.message.reply_text("Управление курсом:", reply_markup=InlineKeyboardMarkup(keyboard))

# Обрабатывает отправку домашнего задания и отправляет его администратору (если требуется *
async def handle_homework_submission(update: Update, context: CallbackContext):
    """Обрабатывает отправку домашнего задания."""
    user_id = update.effective_user.id

    # Получаем active_course_id из users
    cursor.execute('SELECT active_course_id FROM users WHERE user_id = ?', (user_id,))
    active_course_data = cursor.fetchone()

    if not active_course_data or not active_course_data[0]:
        await update.message.reply_text("Активируйте курс через кодовое слово.")
        return

    active_course_id_full = active_course_data[0]
    course_id = active_course_id_full.split('_')[0]
    tariff = active_course_id_full.split('_')[1] if len(active_course_id_full.split('_')) > 1 else "default"

    # Получаем номер текущего урока
    cursor.execute('''
        SELECT progress FROM user_courses
        WHERE user_id = ? AND course_id = ?
    ''', (user_id, active_course_id_full))
    progress_data = cursor.fetchone()

    if not progress_data:
        # await update.message.reply_text("Не найден прогресс курса.") # Removing this line
        lesson = 1 #If no progress, start with lesson 1
    else:
        lesson = progress_data[0]

    try:
        # Сохраняем информацию о ДЗ в базе данных
        file_id = update.message.photo[-1].file_id if update.message.photo else update.message.document.file_id
        cursor.execute('''
            INSERT INTO homeworks (user_id, course_id, lesson, file_id, submission_time, status)
            VALUES (?, ?, ?, ?, DATETIME('now'), ?)
        ''', (user_id, active_course_id_full, lesson, file_id, 'pending'))
        conn.commit()

        if tariff == "self":
            # Если тариф self, сразу подтверждаем и увеличиваем прогресс
            await approve_homework(update, context, user_id=user_id, course_id=active_course_id_full, lesson=lesson)
            await update.message.reply_text("ДЗ принято. Переходим к следующему уроку!")
        else:
            # Отправляем ДЗ администратору для проверки (для других тарифов)
            # Получаем hw_id только что добавленной домашки
            cursor.execute("SELECT last_insert_rowid()")
            hw_id = cursor.fetchone()[0]
            # Формируем подпись
            caption = f"Новое ДЗ для проверки!\nUser ID: {user_id}\nКурс: {course_id} ({tariff})\nУрок: {lesson}"

            # Создаем кнопки для одобрения и отклонения
            keyboard = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f'admin_approve_{hw_id}'),
                    InlineKeyboardButton("❌ Reject", callback_data=f'admin_reject_{hw_id}')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Отправляем фото администратору
            await context.bot.send_photo(chat_id=ADMIN_GROUP_ID, photo=file_id, caption=caption, reply_markup=reply_markup)
            await update.message.reply_text("ДЗ отправлено администратору для проверки.")

    except Exception as e:
        logger.error(f"Ошибка при обработке ДЗ: {e}")
        await update.message.reply_text("Произошла ошибка при отправке ДЗ. Попробуйте позже.")

    # Выводим меню и время ожидания следующего урока
    await show_main_menu(update, context)

    next_lesson_time = await calculate_time_to_next_lesson(user_id, active_course_id_full)

    if next_lesson_time > timedelta(0):
        hours, remainder = divmod(next_lesson_time.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        time_str = f"{int(hours)} часов {int(minutes)} минут"
        await update.message.reply_text(f"Следующий урок будет доступен через: {time_str}")
    else:
        await update.message.reply_text("Следующий урок доступен прямо сейчас!")

# Добавьте функцию для получения следующего времени урока
async def calculate_time_to_next_lesson(user_id, active_course_id_full):
    """Вычисляет, сколько времени осталось до следующего урока."""
    # Получаем время последнего урока
    cursor.execute('''
        SELECT submission_time FROM homeworks
        WHERE user_id = ? AND course_id = ?
        ORDER BY submission_time DESC
        LIMIT 1
    ''', (user_id, active_course_id_full))
    last_submission_data = cursor.fetchone()

    if not last_submission_data:
        # Если еще не было уроков, то следующий урок через DEFAULT_LESSON_INTERVAL
        next_lesson_time = datetime.datetime.now() + datetime.timedelta(hours=DEFAULT_LESSON_INTERVAL)
        return next_lesson_time - datetime.datetime.now()

    last_submission_time = datetime.datetime.strptime(last_submission_data[0], '%Y-%m-%d %H:%M:%S')

    # Рассчитываем время следующего урока
    next_lesson_time = last_submission_time + datetime.timedelta(hours=DEFAULT_LESSON_INTERVAL)

    # Возвращаем, сколько времени осталось до следующего урока
    return next_lesson_time - datetime.datetime.now()

async def send_preliminary_material(update: Update, context: CallbackContext):
    """Отправляет предварительные материалы для следующего урока."""
    await update.message.reply_text("Здесь будут предварительные задания для следующего урока.")



# Подтверждает домашнее задание и увеличивает прогресс пользователя *
async def approve_homework(update: Update, context: CallbackContext, hw_id: int = None, user_id: int = None, course_id: str = None, lesson: int = None):
    """Подтверждает домашнее задание и увеличивает прогресс пользователя."""
    try:
        # Если передан hw_id, получаем данные из базы
        if hw_id:
            cursor.execute('''
                SELECT user_id, course_id, lesson 
                FROM homeworks 
                WHERE hw_id = ?
            ''', (hw_id,))
            hw_data = cursor.fetchone()

            if not hw_data:
                await update.message.reply_text("Домашнее задание не найдено.")
                return

            user_id, course_id, lesson = hw_data

        # Проверка обязательных параметров
        if not all([user_id, course_id, lesson]):
            await update.message.reply_text("Недостаточно данных для подтверждения ДЗ.")
            return

        # Обновляем статус домашней работы
        if hw_id:
            cursor.execute('''
                UPDATE homeworks 
                SET status = 'approved', 
                    approval_time = DATETIME('now'), 
                    feedback = COALESCE(feedback, 'Проверено автоматически')
                WHERE hw_id = ?
            ''', (hw_id,))
        else:
            cursor.execute('''
                UPDATE homeworks 
                SET status = 'approved', 
                    approval_time = DATETIME('now')
                WHERE user_id = ? 
                    AND course_id = ? 
                    AND lesson = ?
            ''', (user_id, course_id, lesson))

        # Увеличиваем прогресс пользователя
        cursor.execute('''
            UPDATE user_courses
            SET progress = progress + 1
            WHERE user_id = ? 
                AND course_id = ?
        ''', (user_id, course_id))

        conn.commit()

        logger.info(f"ДЗ подтверждено [User: {user_id}, Course: {course_id}, Lesson: {lesson}]")

        # Отправляем уведомление пользователю
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Ваше домашнее задание к уроку {lesson} успешно подтверждено!"
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"Ошибка при подтверждении ДЗ: {e}")
        await update.message.reply_text("Произошла ошибка при подтверждении ДЗ.")


async def save_admin_comment(update: Update, context: CallbackContext):
    """
    Сохраняет комментарий админа и обновляет статус ДЗ.
    """
    user_id = update.effective_user.id
    logger.info(f" save_admin_comment {user_id} ")
    cursor.execute('SELECT admin_id FROM admins WHERE admin_id = ?', (user_id,))
    if not cursor.fetchone():
        logger.info(f" this admin? NO! {cursor.fetchone()} ")
        await update.message.reply_text("⛔ Команда только для админов")
        return  # Прекращаем выполнение функции для не-админов
    hw_id = context.user_data.get('awaiting_comment')
    approval_status = context.user_data.pop('approval_status', None)

    logger.info(f" this admin? yep {cursor.fetchone()}  {hw_id} {approval_status=}")

    if not hw_id or not approval_status:
        # Убираем reply_text для обычных пользователей
        if update.message.chat.type != 'private':
            await update.message.reply_text("Команда доступна только админам")
        return

    if hw_id and approval_status:
        comment = update.message.text
        try:
            cursor.execute('''
                UPDATE homeworks 
                SET status = ?, feedback = ?, approval_time = DATETIME('now'), admin_comment = ?
                WHERE hw_id = ?
            ''', (approval_status, comment, comment, hw_id))  # Сохраняем комментарий
            conn.commit()
            await update.message.reply_text(f"Комментарий сохранен. Статус ДЗ обновлен: {approval_status}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении комментария и статуса ДЗ: {e}")
            await update.message.reply_text("Произошла ошибка при сохранении комментария.")
    else:
        await update.message.reply_text("Не найден hw_id или статус. Повторите действие.")

# отказ * всё хуйня - переделывай
async def handle_admin_rejection(update: Update, context: CallbackContext):
    """Обрабатывает отклонение ДЗ администратором."""
    query = update.callback_query
    await query.answer()

    try:
        # Получаем hw_id из callback_data
        hw_id = query.data.split('_')[2] #was '|' and [1]

        # Обновляем статус ДЗ в базе данных
        cursor.execute('''
            UPDATE homeworks
            SET status = 'rejected'
            WHERE hw_id = ?
        ''', (hw_id,))
        conn.commit()

        # Получаем user_id и lesson из homeworks
        cursor.execute('''
            SELECT user_id, course_id, lesson
            FROM homeworks
            WHERE hw_id = ?
        ''', (hw_id,))
        homework_data = cursor.fetchone()

        if not homework_data:
            await query.message.reply_text("Ошибка: ДЗ не найдено.")
            return

        user_id, course_id, lesson = homework_data

        # Отправляем уведомление пользователю
        await context.bot.send_message(
            chat_id=user_id,
            text=f"К сожалению, Ваше домашнее задание по уроку {lesson} курса {course_id} отклонено администратором. Попробуйте еще раз."
        )

        # Редактируем сообщение в админ-группе
        await context.bot.edit_message_reply_markup(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            reply_markup=None  # Убираем кнопки
        )
        await context.bot.edit_message_caption(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            caption=query.message.caption + "\n\n❌ Отклонено!"
        )

        logger.info(f"ДЗ {hw_id} отклонено администратором")

    except Exception as e:
        logger.error(f"Ошибка при отклонении ДЗ: {e}")
        await query.message.reply_text("Произошла ошибка при отклонении ДЗ. Попробуйте позже.")


# Обрабатывает выбор тарифа
async def change_tariff(update: Update, context: CallbackContext):
    """Обрабатывает выбор тарифа."""
    user_id = update.effective_user.id

    try:
        # Получаем active_course_id из базы данных
        cursor.execute('''
            SELECT active_course_id
            FROM users
            WHERE user_id = ?
        ''', (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await update.callback_query.message.reply_text("У вас не активирован ни один курс.")
            return

        active_course_id = active_course_data[0]

        # Создаем кнопки с вариантами тарифов
        keyboard = [
            [InlineKeyboardButton("Self-Check", callback_data=f"set_tariff|{active_course_id}|self_check")],
            [InlineKeyboardButton("Admin-Check", callback_data=f"set_tariff|{active_course_id}|admin_check")],
            [InlineKeyboardButton("Premium", callback_data=f"set_tariff|{active_course_id}|premium")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.callback_query.message.reply_text("Выберите новый тариф:", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Ошибка при отображении вариантов тарифов: {e}")
        await update.callback_query.message.reply_text("Произошла ошибка при отображении вариантов тарифов. Попробуйте позже.")

# Отображает список курсов пользователя
async def my_courses(update: Update, context: CallbackContext):
    """Отображает список курсов пользователя."""
    user_id = update.effective_user.id

    try:
        # Получаем список курсов пользователя из базы данных
        cursor.execute('''
            SELECT course_id, course_type
            FROM user_courses
            WHERE user_id = ?
        ''', (user_id,))
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

# "Отображает историю домашних заданий пользователя
async def hw_history(update: Update, context: CallbackContext):
    """Отображает историю домашних заданий пользователя."""
    user_id = update.effective_user.id

    try:
        # Получаем историю домашних заданий пользователя из базы данных
        cursor.execute('''
            SELECT course_id, lesson, status, submission_time
            FROM homeworks
            WHERE user_id = ?
            ORDER BY submission_time DESC
        ''', (user_id,))
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

# Устанавливает выбранный тариф для пользователя
async def set_tariff(update: Update, context: CallbackContext):
    """Устанавливает выбранный тариф для пользователя."""
    query = update.callback_query
    await query.answer()

    try:
        # Извлекаем данные из callback_data
        _, course_id, tariff = query.data.split('|')

        # Обновляем тариф в базе данных
        cursor.execute('''
            UPDATE user_courses
            SET tariff = ?
            WHERE user_id = ? AND course_id = ?
        ''', (tariff, query.from_user.id, course_id))
        conn.commit()

        # Обновляем информацию о тарифе в таблице users
        cursor.execute('''
            UPDATE users
            SET tariff = ?
            WHERE user_id = ?
        ''', (tariff, query.from_user.id))
        conn.commit()

        # Отправляем подтверждение пользователю
        await query.message.reply_text(f"Тариф для курса {course_id} изменен на {tariff}.")

    except Exception as e:
        logger.error(f"Ошибка при установке тарифа: {e}")
        await query.message.reply_text("Произошла ошибка при установке тарифа. Попробуйте позже.")

# Отображает настройки курса *
async def show_course_settings(update: Update, context: CallbackContext):
    """Отображает настройки курса."""
    user_id = update.effective_user.id
    logger.error(f"show_course_settings {user_id}")
    try:
        # Получаем времена уведомлений из базы данных
        cursor.execute('SELECT morning_notification, evening_notification FROM user_settings WHERE user_id = ?', (user_id,))
        settings = cursor.fetchone()
        morning_time = settings[0] if settings else "Не установлено"
        evening_time = settings[1] if settings else "Не установлено"

        # Формируем сообщение с настройками
        text = f"Ваши текущие настройки:\n\n" \
               f"⏰ Утреннее напоминание: {morning_time}\n" \
               f"🌙 Вечернее напоминание: {evening_time}\n\n" \
               f"Вы можете изменить эти настройки через соответствующие команды."

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

# "Показывает текст урока по запросу."*
async def show_lesson(update: Update, context: CallbackContext):
    """Отправляет все материалы текущего урока, включая текст и файлы, а также напоминает о ДЗ."""
    user_id = update.effective_user.id
    logger.info(f" show_lesson {user_id} - Current state")

    try:
        # Получаем active_course_id из users
        cursor.execute('SELECT active_course_id FROM users WHERE user_id = ?', (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            if update.callback_query:
                await update.callback_query.message.reply_text("Активируйте курс через кодовое слово.")
            else:
                await update.message.reply_text("Активируйте курс через кодовое слово.")
            return

        active_course_id_full = active_course_data[0]
        # Обрезаем название курса до первого символа "_"
        active_course_id = active_course_id_full.split('_')[0]
        logger.info(f" active_course_id {active_course_id} +")

        # Получаем progress (номер урока) из user_courses
        cursor.execute('''
            SELECT progress
            FROM user_courses
            WHERE user_id = ? AND course_id = ?
        ''', (user_id, active_course_id_full))
        progress_data = cursor.fetchone()

        # Если progress не найден, отдаем первый урок
        if not progress_data:
            lesson = 1
            await update.callback_query.message.reply_text("Начинаем с первого урока.")
        else:
            lesson = progress_data[0]

        # 1. Отправляем текст урока
        lesson_text = get_lesson_text(user_id, lesson, active_course_id)
        if lesson_text:
            await update.callback_query.message.reply_text(lesson_text)
        else:
            await update.callback_query.message.reply_text("Текст урока не найден.")

        # 2. Отправляем файлы урока (аудио, видео, изображения)
        lesson_files = await get_lesson_files(user_id, lesson, active_course_id)
        if lesson_files:
            total_files = len(lesson_files)  # Общее количество файлов
            for i, file_info in enumerate(lesson_files):
                file_path = file_info['path']
                delay = file_info['delay']
                file_type = file_info['type']

                if delay > 0:
                    await asyncio.sleep(delay)

                try:
                    if file_type == 'photo':
                         with open(file_path, 'rb') as photo_file:
                            if update.callback_query:
                                await context.bot.send_photo(
                                    chat_id=update.effective_chat.id,
                                    photo=photo_file,
                                    caption=f"Фото к уроку {lesson}"
                                )
                            else:
                                await context.bot.send_photo(
                                    chat_id=user_id,
                                    photo=photo_file,
                                    caption=f"Фото к уроку {lesson}"
                                )
                    elif file_type == 'audio':
                        with open(file_path, 'rb') as audio_file:
                            if update.callback_query:
                                await context.bot.send_audio(
                                    chat_id=update.effective_chat.id,
                                    audio=audio_file,
                                    caption=f"Аудио к уроку {lesson}"
                                )
                            else:
                                 await context.bot.send_audio(
                                    chat_id=user_id,
                                    audio=audio_file,
                                    caption=f"Аудио к уроку {lesson}"
                                )
                    elif file_type == 'video':
                        with open(file_path, 'rb') as video_file:
                            if update.callback_query:
                                 await context.bot.send_video(
                                    chat_id=update.effective_chat.id,
                                    video=video_file,
                                    caption=f"Видео к уроку {lesson}"
                                )
                            else:
                                await context.bot.send_video(
                                    chat_id=user_id,
                                    video=video_file,
                                    caption=f"Видео к уроку {lesson}"
                                )
                    elif file_type == 'document':
                        with open(file_path, 'rb') as doc_file:
                            if update.callback_query:
                                await context.bot.send_document(
                                    chat_id=update.effective_chat.id,
                                    document=doc_file,
                                    caption=f"Документ к уроку {lesson}"
                                )
                            else:
                                await context.bot.send_document(
                                    chat_id=user_id,
                                    document=doc_file,
                                    caption=f"Документ к уроку {lesson}"
                                )
                    else:
                        logger.warning(f"Неизвестный тип файла: {file_type}, {file_path}")

                except FileNotFoundError as e:
                    logger.error(f"Файл не найден: {file_path} - {e}")
                    await update.callback_query.message.reply_text(f"Файл {os.path.basename(file_path)} не найден.")
                except TelegramError as e:
                    logger.error(f"Ошибка при отправке файла {file_path}: {e}")
                    await update.callback_query.message.reply_text(
                        f"Произошла ошибка при отправке файла {os.path.basename(file_path)}.")
                except Exception as e:
                    logger.error(f"Неожиданная ошибка при отправке файла {file_path}: {e}")
                    await update.callback_query.message.reply_text(
                        f"Произошла непредвиденная ошибка при отправке файла {os.path.basename(file_path)}.")

            # После отправки последнего файла показываем меню и напоминаем о ДЗ
            await show_main_menu(update, context)

            # Добавляем напоминание о ДЗ
            homework_status = await get_homework_status_text(user_id, active_course_id_full)
            if update.callback_query:
                 await update.callback_query.message.reply_text(f"Напоминаем: {homework_status}")
            else:
                await update.message.reply_text(f"Напоминаем: {homework_status}")

        else:
             if update.callback_query:
                await update.callback_query.message.reply_text("Файлы к этому уроку не найдены.")
             else:
                 await update.message.reply_text("Файлы к этому уроку не найдены.")

            await show_main_menu(update, context)  # Показываем меню, даже если файлов не
            homework_status = await get_homework_status_text(user_id, active_course_id_full)
            if update.callback_query:
                 await update.callback_query.message.reply_text(f"Напоминаем: {homework_status}")
            else:
                await update.message.reply_text(f"Напоминаем: {homework_status}")

    except Exception as e: # это часть show_lesson
        logger.error(f"Ошибка при получении материалов урока: {e}")
        if update.callback_query:
            await update.callback_query.message.reply_text("Ошибка при получении материалов урока. Попробуйте позже.")
        else:
            await update.message.reply_text("Ошибка при получении материалов урока. Попробуйте позже.")



# Функция для получения файлов урока (обновленная версия)
async def get_lesson_files(user_id, lesson_number, course_id):
    """Получает список файлов для урока с указанием задержки."""
    logger.info(f" get_lesson_files {user_id} - lesson_number {lesson_number}")
    lesson_number = int(lesson_number)
    lesson_dir = f'courses/{course_id}'

    try:
        files_info = []
        for filename in os.listdir(lesson_dir):
            if filename.startswith(f'lesson{lesson_number}_'):
                filepath = os.path.join(lesson_dir, filename)

                # Извлекаем задержку
                match = DELAY_PATTERN.search(filename)
                if match:
                    delay_value = int(match.group(1))
                    delay_unit = match.group(2)
                    delay = delay_value * 60 if delay_unit == 'm' else delay_value * 3600 if delay_unit == 'h' else 0
                else:
                    delay = 0

                # Определяем тип файла
                if filename.endswith(('.jpg', '.jpeg', '.png', '.gif')):
                    file_type = 'photo'
                elif filename.endswith(('.mp3', '.wav', '.ogg')):
                    file_type = 'audio'
                elif filename.endswith(('.mp4', '.avi', '.mov')):
                    file_type = 'video'
                else:
                    file_type = 'document'

                files_info.append({
                    'path': filepath,
                    'delay': delay,
                    'type': file_type
                })

        return files_info
    except FileNotFoundError:
        logger.error(f"Директория не найдена: {lesson_dir}")
        return None
    except Exception as e:
        logger.error(f"Ошибка при получении списка файлов урока: {e}")
        return None


# Обрабатывает нажатия на
async def button_handler(update: Update, context: CallbackContext):
    """Обрабатывает нажатия на кнопки."""
    logger.info(f"{update.effective_user.id} - button_handler")
    query = update.callback_query
    data = query.data
    await query.answer()

    button_handlers = {
        'get_current_lesson': show_lesson,  # <-- заменено на show_lesson
        'gallery': show_gallery,
        'gallery_next': get_random_homework,
        'menu_back': show_main_menu,
        'support': show_support,
        'profile': show_profile,
        'tariffs': show_tariffs,
        'course_settings': show_course_settings,
    }
    if data.startswith('self_approve_'):
        hw_id = int(data.split('_')[2])
        await approve_homework(update, context, hw_id=hw_id)
        await query.message.reply_text("ДЗ подтверждено. Переходим к следующему уроку!")
    elif data.startswith('admin'):
        data_split = data.split('_')
        if len(data_split) > 1:
            if data_split[1] == 'approve':
                await handle_admin_approval(update, context)
            elif data_split[1] == 'reject':
                await handle_admin_rejection(update, context)
    elif data.startswith('review'):
        await show_homework(update, context)
    elif data.startswith('repeat_lesson_'):
        lesson_number = int(data.split('_')[1])
        user_id = update.effective_user.id

        # Получаем active_course_id из users
        cursor.execute('SELECT active_course_id FROM users WHERE user_id = ?', (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await query.message.reply_text("Активируйте курс через кодовое слово.")
            return

        active_course_id = active_course_data[0]

        # Получаем course_type из user_courses
        cursor.execute('''
            SELECT course_type
            FROM user_courses
            WHERE user_id = ? AND course_id = ?
        ''', (user_id, active_course_id))
        course_type_data = cursor.fetchone()

        if not course_type_data:
            await query.message.reply_text("Курс не найден.")
            return

        course_type = course_type_data[0]

        # Отправляем урок
        await send_lesson(update, context, active_course_id)
        logger.info(f"Повторно отправляем урок {lesson_number} пользователю {user_id} курса {active_course_id}")
    elif data.startswith("approve_hw"):
        try:
            hw_id = int(data.split('_')[2])
            await approve_homework(update, context, hw_id=hw_id)
        except (IndexError, ValueError):
            logger.error(f"Неверный формат approve_hw callback_data: {data}")
            await query.message.reply_text("Неверный формат запроса на подтверждение ДЗ.")

    elif data in button_handlers:
        handler = button_handlers[data]
        await handler(update, context)





 #Обрабатывает текстовые сообщения. *
async def handle_text_message(update: Update, context: CallbackContext):
    """Обрабатывает текстовые сообщения."""
    user_id = update.effective_user.id
    text = update.message.text.lower()  # Приводим текст к нижнему регистру

    # Проверяем, находится ли пользователь в состоянии ожидания кодового слова
    if context.user_data.get('waiting_for_code'):
        return  # Если ждем кодовое слово, игнорируем сообщение

    if "текущий урок" in text or "ту" in text:
        await get_current_lesson(update, context)
    elif "галерея дз" in text or "гдз" in text:
        await show_gallery(update, context)
    elif "тарифы" in text or "ТБ" in text:
        await show_tariffs(update, context)
    elif "поддержка" in text or "пд" in text:
        await start_support_request(update, context)  # Вызываем функцию для начала запроса в поддержку
    else:
        await update.message.reply_text("Я не понимаю эту команду.")

# Отправляет запрос в поддержку администратору. *
async def start_support_request(update: Update, context: CallbackContext):
    """Начинает запрос в поддержку."""
    await update.message.reply_text(
        "Пожалуйста, опишите вашу проблему или вопрос. Вы также можете прикрепить фотографию."
    )
    return WAIT_FOR_SUPPORT_TEXT

# Отправляет запрос в поддержку администратору. *
async def get_support_text(update: Update, context: CallbackContext):
    """Получает текст запроса в поддержку."""
    user_id = update.effective_user.id
    text = update.message.text
    context.user_data['support_text'] = text

    logger.info(f" get_support_text  get_support_text {user_id}  {text}  ")

    # Проверяем наличие фотографии
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data['support_photo'] = file_id
    else:
        context.user_data['support_photo'] = None

    await send_support_request_to_admin(update, context)

    return ACTIVE

# Отправляет запрос в поддержку администратору. *
async def send_support_request_to_admin(update: Update, context: CallbackContext):
    """Отправляет запрос в поддержку администратору."""
    user_id = update.effective_user.id
    support_text = context.user_data.get('support_text', "No text provided")
    support_photo = context.user_data.get('support_photo')
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
        cursor.execute("UPDATE users SET support_requests = support_requests + 1 WHERE user_id = ?", (user_id,))
        conn.commit()

        await update.message.reply_text("Ваш запрос в поддержку отправлен. Ожидайте ответа.")

    except Exception as e:
        logger.error(f"Ошибка при отправке запроса в поддержку администратору: {e}")
        await update.message.reply_text("Произошла ошибка при отправке запроса. Попробуйте позже.")


# Сохраняет имя пользователя и запрашивает кодовое слово *
async def handle_name(update: Update, context: CallbackContext):
    """Сохраняет имя пользователя и запрашивает кодовое слово."""
    user_id = update.effective_user.id
    full_name = update.message.text.strip()

    logger.info(f" 333 4 handle_name {user_id}  {full_name}  ")

    # Сохраняем имя пользователя в базе данных
    cursor.execute('INSERT OR REPLACE INTO users (user_id, full_name) VALUES (?, ?)', (user_id, full_name))
    conn.commit()

    # Устанавливаем состояние ожидания кодового слова
    context.user_data['waiting_for_code'] = True

    await update.message.reply_text(f"Отлично, {full_name}! Теперь введите кодовое слово для активации курса.")
    return WAIT_FOR_CODE


# Обрабатывает отправленные пользователем документы *
async def handle_document(update: Update, context: CallbackContext):
    """Обрабатывает отправленные пользователем документы."""
    if update.message.document.mime_type.startswith('image/'):
        await handle_homework_submission(update, context)
    else:
        await update.message.reply_text("⚠️ Отправьте, пожалуйста, картинку или фотографию.")


async def show_support(update: Update, context: CallbackContext):
    """Отображает информацию о поддержке."""
    await update.message.reply_text("Здесь будет информация о поддержке.")

async def show_profile(update: Update, context: CallbackContext):
    """Отображает профиль пользователя."""
    await update.message.reply_text("Здесь будет профиль пользователя.")



# Инициализация БД
conn = sqlite3.connect('bot_db.sqlite', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
try:
    cursor.executescript('''
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
    submission_time DATETIME,
    approval_time DATETIME,
    admin_comment TEXT,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
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

    ''')
    conn.commit()
    logger.info("База данных успешно создана и инициализирована.")
except sqlite3.Error as e:
    logger.error(f"Ошибка при создании базы данных: {e}")



with conn:
    for admin_id in ADMIN_IDS:
        try:
            admin_id = int(admin_id)
            cursor.execute('INSERT OR IGNORE INTO admins (admin_id) VALUES (?)', (admin_id,))
            conn.commit()
            logger.info(f"Администратор с ID {admin_id} добавлен.")
        except ValueError:
            logger.warning(f"Некорректный ID администратора: {admin_id}")


async def reminders(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    cursor.execute('SELECT morning_notification, evening_notification FROM user_settings WHERE user_id = ?', (user_id,))
    settings = cursor.fetchone()
    if not settings:
        cursor.execute('INSERT INTO user_settings (user_id) VALUES (?)', (user_id,))
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

async def set_morning(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    try:
        time = context.args[0]
        if not re.match(r"^\d{2}:\d{2}$", time):
            raise ValueError
        cursor.execute('UPDATE user_settings SET morning_notification = ? WHERE user_id = ?', (time, user_id))
        conn.commit()
        await update.message.reply_text(f"🌅 Утреннее напоминание установлено на {time}.")
    except (IndexError, ValueError):
        await update.message.reply_text("Неверный формат времени. Используйте формат HH:MM.")

async def disable_reminders(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    cursor.execute('UPDATE user_settings SET morning_notification = NULL, evening_notification = NULL WHERE user_id = ?', (user_id,))
    conn.commit()
    await update.message.reply_text("🔕 Все напоминания отключены.")

async def send_reminders(context: CallbackContext):
    now = datetime.datetime.now().strftime("%H:%M")
    cursor.execute('SELECT user_id, morning_notification, evening_notification FROM user_settings')
    for user_id, morning, evening in cursor.fetchall():
        if morning and now == morning:
            await context.bot.send_message(chat_id=user_id, text="🌅 Доброе утро! Не забудьте посмотреть материалы курса.")
        if evening and now == evening:
            await context.bot.send_message(chat_id=user_id, text="🌇 Добрый вечер! Не забудьте выполнить домашнее задание.")

async def stats(update: Update, context: CallbackContext):
    # Активные пользователи за последние 3 дня
    active_users = cursor.execute('''
        SELECT COUNT(DISTINCT user_id) 
        FROM homeworks 
        WHERE submission_time >= DATETIME('now', '-3 days')
    ''').fetchone()[0]

    # Домашние задания за последние сутки
    recent_homeworks = cursor.execute('''
        SELECT COUNT(*) 
        FROM homeworks 
        WHERE submission_time >= DATETIME('now', '-1 day')
    ''').fetchone()[0]

    # Общее количество пользователей
    total_users = cursor.execute('SELECT COUNT(*) FROM users').fetchone()[0]

    text = "📊 Статистика:\n"
    text += f"👥 Активных пользователей за последние 3 дня: {active_users}\n"
    text += f"📚 Домашних заданий за последние сутки: {recent_homeworks}\n"
    text += f"👤 Всего пользователей с начала работы бота: {total_users}"

    await update.message.reply_text(text)

async def set_evening(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    try:
        time = context.args[0]
        if not re.match(r"^\d{2}:\d{2}$", time):
            raise ValueError
        cursor.execute('UPDATE user_settings SET evening_notification = ? WHERE user_id = ?', (time, user_id))
        conn.commit()
        await update.message.reply_text(f"🌇 Вечернее напоминание установлено на {time}.")
    except (IndexError, ValueError):
        await update.message.reply_text("Неверный формат времени. Используйте формат HH:MM.")

def parse_delay_from_filename(filename):
    """
    Извлекает время задержки из имени файла.
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

async def send_file_with_delay(context: CallbackContext):
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

async def send_file(bot, chat_id, file_path, file_name):
    """
    Отправляет файл пользователю.
    """
    try:
        if file_name.lower().endswith(('.jpg', '.jpeg', '.png')):
            with open(file_path, 'rb') as photo:
                await bot.send_photo(chat_id=chat_id, photo=photo)
        elif file_name.lower().endswith('.mp4'):
            with open(file_path, 'rb') as video:
                await bot.send_video(chat_id=chat_id, video=video)
        elif file_name.lower().endswith('.mp3'):
            with open(file_path, 'rb') as audio:
                await bot.send_audio(chat_id=chat_id, audio=audio)
        else:
            with open(file_path, 'rb') as document:
                await bot.send_document(chat_id=chat_id, document=document, filename=file_name)  # Передаём имя файла
    except FileNotFoundError:
        logger.error(f"Файл не найден: {file_path}")
    except Exception as e:
        logger.error(f"Ошибка при отправке файла {file_name}: {e}")
        await bot.send_message(chat_id=chat_id, text=f"Не удалось загрузить файл {file_name}.")

async def get_lesson_after_code(update: Update, context: CallbackContext, course_type: str):
    user = update.effective_user
    # Посылаем урок
    await send_lesson(update, context, course_type)

async def show_homework(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    lesson_number = query.data.split('_')[1]
    await query.edit_message_text(f"Здесь будет галерея ДЗ по {lesson_number} уроку")

# Функция для получения предварительных материалов
def get_preliminary_materials(course, next_lesson):
    try:
        lesson_dir = f'courses/{course}/'
        if not os.path.exists(lesson_dir):
            return []

        return [
            f for f in os.listdir(lesson_dir)
            if f.startswith(f'lesson{next_lesson}_p')
               and os.path.isfile(os.path.join(lesson_dir, f))
        ]
    except FileNotFoundError:
        logger.error(f"Директория {lesson_dir} не найдена")
        return []

# Обработчик кнопки "Получить предварительные материалы"
async def send_preliminary_material(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    course_type = query.data.split('_')[1]  # Получаем тип курса из callback_data
    course_prefix = course_type.split('_')[0]

    # Проверяем, какой урок следующий
    cursor.execute(
        f'SELECT {course_prefix}_current_lesson FROM users WHERE user_id = ?',
        (user_id,)
    )
    current_lesson = cursor.fetchone()[0]
    next_lesson = current_lesson + 1

    # Получаем название курса
    cursor.execute(f'SELECT {course_type}_course FROM users WHERE user_id = ?', (user_id,))
    course = cursor.fetchone()[0]

    # Получаем список предварительных материалов
    materials = get_preliminary_materials(course, next_lesson)

    if not materials:
        await query.edit_message_text("Предварительные материалы для следующего урока отсутствуют.")
        return

    # Проверяем, сколько материалов уже отправлено
    cursor.execute('SELECT preliminary_material_index FROM users WHERE user_id = ?', (user_id,))
    material_index = cursor.fetchone()[0] or 0  # Индекс текущего материала

    if material_index >= len(materials):
        await query.edit_message_text("Вы получили все предварительные материалы для следующего урока.")
        return

    # Отправляем текущий материал
    material_file = materials[material_index]

    # Определяем тип файла
    material_path = f'courses/{course}/{material_file}'

    if material_file.endswith('.jpg') or material_file.endswith('.png'):
        await context.bot.send_photo(chat_id=user_id, photo=open(material_path, 'rb'))
    elif material_file.endswith('.mp4'):
        await context.bot.send_video(chat_id=user_id, video=open(material_path, 'rb'))
    elif material_file.endswith('.mp3'):
        await context.bot.send_audio(chat_id=user_id, audio=open(material_path, 'rb'))
    else:
        await context.bot.send_document(chat_id=user_id, document=open(material_path, 'rb'))

    # Увеличиваем индекс отправленных материалов
    material_index += 1
    cursor.execute('UPDATE users SET preliminary_material_index = ? WHERE user_id = ?', (material_index, user_id))
    conn.commit()

    # Обновляем кнопку с количеством оставшихся материалов
    remaining_materials = len(materials) - material_index
    keyboard = [
        [InlineKeyboardButton(f"Получить предварительные материалы к след уроку ({remaining_materials} осталось)",
                              callback_data=f'preliminary_{course_type}')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if remaining_materials > 0:
        await query.edit_message_text("Материал отправлен. Хотите получить ещё?", reply_markup=reply_markup)
    else:
        await query.edit_message_text("Вы получили все предварительные материалы для следующего урока.")

# Функция для добавления кнопки "Получить предварительные материалы"
async def add_preliminary_button(user_id, course_type):
    # Извлекаем префикс курса (main/auxiliary)
    course_prefix = course_type.split('_')[0]  # Получаем "main" или "auxiliary"

    # Получаем текущий урок
    cursor.execute(
        f'SELECT {course_prefix}_current_lesson FROM users WHERE user_id = ?',
        (user_id,)
    )
    current_lesson = cursor.fetchone()[0]
    next_lesson = current_lesson + 1

    # Получаем название курса
    cursor.execute(
        f'SELECT {course_prefix}_course FROM users WHERE user_id = ?',
        (user_id,)
    )
    course = cursor.fetchone()[0]

    materials = get_preliminary_materials(course, next_lesson)
    if not materials:
        return None

    cursor.execute('SELECT preliminary_material_index FROM users WHERE user_id = ?', (user_id,))
    material_index = cursor.fetchone()[0] or 0

    remaining_materials = len(materials) - material_index
    if remaining_materials > 0:
        return InlineKeyboardButton(
            f"Получить предварительные материалы к след. уроку({remaining_materials} осталось)",
            callback_data=f'preliminary_{course_type}'
        )
    return None

def get_average_homework_time(user_id):
    cursor.execute('''
        SELECT AVG((JULIANDAY(approval_time) - JULIANDAY(submission_time)) * 24 * 60 * 60)
        FROM homeworks
        WHERE user_id = ? AND status = 'approved'
    ''', (user_id,))
    result = cursor.fetchone()[0]

    logger.info(f"{result} - get_average_homework_time")

    if result:
        average_time_seconds = int(result)
        hours, remainder = divmod(average_time_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours} часов {minutes} минут"
    else:
        return "Нет данных"



async def handle_admin_approval(update: Update, context: CallbackContext):
    query = update.callback_query
    logger.info(f" handle_admin_approval {update.effective_user.id} -{query}")
    await query.answer()

    data = query.data.split('_')
    action = data[1]
    hw_id = data[2]

    if action == 'approve':
        # Запрашиваем комментарий у админа
        await query.message.reply_text("Введите комментарий к домашней работе:")
        context.user_data['awaiting_comment'] = hw_id
        context.user_data['approval_status'] = 'approved'  # Сохраняем статус
    elif action == 'reject':
        # Запрашиваем комментарий у админа
        await query.message.reply_text("Введите комментарий к домашней работе:")
        context.user_data['awaiting_comment'] = hw_id
        context.user_data['approval_status'] = 'rejected'  # Сохраняем статус

    else:
        await query.message.reply_text("Неизвестное действие.")




# Загружает тарифы из файла.*
def load_tariffs():
    """Загружает тарифы из файла."""
    try:
        with open(TARIFFS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Файл {TARIFFS_FILE} не найден.")
        return []
    except json.JSONDecodeError:
        logger.error(f"Ошибка декодирования JSON в файле {TARIFFS_FILE}.")
        return []

# Отображает тарифы и акции. *
async def show_tariffs(update: Update, context: CallbackContext):
    """Отображает тарифы и акции."""
    tariffs = load_tariffs()

    if not tariffs:
        await update.message.reply_text("К сожалению, сейчас нет доступных акций.")
        return

    keyboard = []
    for tariff in tariffs:
        keyboard.append(
            [InlineKeyboardButton(f"{tariff['emoji']} {tariff['title']}", callback_data=f"tariff_{tariff['id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите интересующую вас акцию:", reply_markup=reply_markup)

# Обрабатывает выбор тарифа. *
async def tariff_callback(update: Update, context: CallbackContext):
    """Обрабатывает выбор тарифа."""
    query = update.callback_query
    await query.answer()
    tariff_id = query.data.split('_')[1]
    tariffs = load_tariffs()
    tariff = next((t for t in tariffs if t['id'] == tariff_id), None)

    if not tariff:
        await query.message.reply_text("Акция не найдена.")
        return

    context.user_data['tariff'] = tariff  # Сохраняем данные о тарифе

    # Добавляем кнопки "Купить" и "В подарок"
    keyboard = [
        [InlineKeyboardButton("Купить", callback_data=f"buy_{tariff_id}")],
        [InlineKeyboardButton("В подарок", callback_data=f"gift_{tariff_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if tariff['type'] == 'payment':
        text = f"<b>{tariff['title']}</b>\n\n{tariff['description']}\n\nЦена: {tariff['price']} рублей"  # Укажите валюту, если нужно
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
    elif tariff['type'] == 'discount':
        text = f"<b>{tariff['title']}</b>\n\n{tariff['description']}"
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')


# Обрабатывает нажатие кнопки "Купить" *
async def buy_tariff(update: Update, context: CallbackContext):
    """Обрабатывает нажатие кнопки "Купить"."""
    query = update.callback_query
    await query.answer()
    tariff = context.user_data.get('tariff')

    context.user_data['tariff_id'] = tariff['id']  # Сохраняем tariff_id
    if tariff['type'] == 'discount':
        await query.message.reply_text(
            "Для получения скидки отправьте селфи и короткое описание, почему вы хотите получить эту скидку:")
        return WAIT_FOR_SELFIE

    # Инструкция по оплате
    text = f"Для приобретения акции, пожалуйста, переведите {tariff['price']} рублей на номер [номер] и загрузите чек сюда в этот диалог."  # Замените [сумма] и [номер]
    await query.message.reply_text(text)
    await query.message.reply_text("Пожалуйста, поделитесь своим номером телефона:",
                                   reply_markup=ReplyKeyboardMarkup(
                                       [[KeyboardButton(
                                           "Поделиться номером телефона", request_contact=True)]],
                                       resize_keyboard=True,
                                       one_time_keyboard=True)
                                   )
    return WAIT_FOR_PHONE_NUMBER

# Обрабатывает нажатие кнопки "В подарок" *
async def gift_tariff(update: Update, context: CallbackContext):
    """Обрабатывает нажатие кнопки "В подарок"."""
    query = update.callback_query
    await query.answer()
    tariff = context.user_data.get('tariff')
    if tariff['type'] == 'discount':
        await query.message.reply_text("Подарочные сертификаты со скидками недоступны. Выберите другой тариф.")
        return ConversationHandler.END

    context.user_data['tariff_id'] = tariff['id']  # Сохраняем tariff_id

    await query.message.reply_text("Введите user ID получателя подарка:")
    return WAIT_FOR_GIFT_USER_ID



# Добавляет купленный курс пользователю. *
async def add_purchased_course(user_id, tariff_id, context: CallbackContext):
    """Добавляет купленный курс пользователю."""
    try:
        # Проверяем, есть ли уже такой курс у пользователя
        cursor.execute('''
            SELECT * FROM user_courses
            WHERE user_id = ? AND course_id = ?
        ''', (user_id, tariff_id))
        existing_course = cursor.fetchone()

        if existing_course:
            await context.bot.send_message(user_id, "Этот курс уже есть в вашем профиле.")
            return

        # Получаем данные о курсе из tariffs.json
        tariffs = load_tariffs()
        tariff = next((t for t in tariffs if t['id'] == tariff_id), None)

        if not tariff:
            logger.error(f"Тариф с id {tariff_id} не найден в tariffs.json")
            await context.bot.send_message(user_id, "Произошла ошибка при добавлении курса. Попробуйте позже.")
            return

        course_type = tariff.get('course_type', 'main')  # Получаем тип курса из tariff
        tariff_name = tariff_id.split('_')[1] if len(tariff_id.split('_')) > 1 else "default"

        # Добавляем курс в user_courses
        cursor.execute('''
            INSERT INTO user_courses (user_id, course_id, course_type, progress, tariff)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, tariff_id, course_type, 1, tariff_name))  # Начинаем с progress = 1
        conn.commit()

        # Обновляем active_course_id в users
        cursor.execute('''
            UPDATE users
            SET active_course_id = ?
            WHERE user_id = ?
        ''', (tariff_id, user_id))
        conn.commit()

        logger.info(f"Курс {tariff_id} добавлен пользователю {user_id}")
        await context.bot.send_message(user_id, "Новый курс был добавлен вам в профиль.")

    except Exception as e:
        logger.error(f"Ошибка при добавлении курса пользователю {user_id}: {e}")
        await context.bot.send_message(user_id, "Произошла ошибка при добавлении курса. Попробуйте позже.")


# Отклоняет скидку администратором. *
async def show_stats(update: Update, context: CallbackContext):
    """Показывает статистику для администратора."""
    try:
        # Получаем количество пользователей
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]

        # Получаем количество активных курсов
        cursor.execute("SELECT COUNT(DISTINCT course_id) FROM user_courses")
        course_count = cursor.fetchone()[0]

        # Формируем сообщение
        text = f"📊 Статистика:\n\n" \
               f"👥 Пользователей: {user_count}\n" \
               f"📚 Активных курсов: {course_count}"

        await update.message.reply_text(text)

    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        await update.message.reply_text("Произошла ошибка при получении статистики.")

# Отклоняет скидку администратором.*
async def admin_approve_discount(update: Update, context: CallbackContext):
    """Подтверждает скидку администратором."""
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    user_id = int(data[3])
    tariff_id = data[4]
    try:
        # Добавляем логику уведомления пользователя
        await context.bot.send_message(user_id, f"🎉 Ваша заявка на скидку для тарифа {tariff_id} одобрена!")
        await query.message.reply_text(f"Скидка для пользователя {user_id} одобрена.")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")
        await query.message.reply_text("Скидка одобрена, но не удалось уведомить пользователя.")

#Отклоняет скидку администратором.*
async def admin_reject_discount(update: Update, context: CallbackContext):
    """Отклоняет скидку администратором."""
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
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
async def admin_approve_purchase(update: Update, context: CallbackContext):
    """Подтверждает покупку админом."""
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    buyer_user_id = int(data[3])  # Индекс 3, а не 2, чтобы получить user_id
    tariff_id = data[4]
    try:
        # Добавляем купленный курс пользователю
        await add_purchased_course(buyer_user_id, tariff_id, context)
        await query.message.reply_text(f"Покупка для пользователя {buyer_user_id} подтверждена!")
        await context.bot.send_message(chat_id=buyer_user_id,
                                       text="Ваш чек был подтверждён, приятного пользования курсом")
    except Exception as e:
        logger.error(f"Ошибка при подтверждении покупки: {e}")
        await query.message.reply_text("Произошла ошибка при подтверждении покупки.")

# Отклоняет покупку админом.*
async def admin_reject_purchase(update: Update, context: CallbackContext):
    """Отклоняет покупку админом."""
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    buyer_user_id = int(data[3])
    tariff_id = data[4]
    await query.message.reply_text("Покупка отклонена.")
    await context.bot.send_message(chat_id=buyer_user_id,
                                   text="Ваш чек не был подтверждён. Пожалуйста, свяжитесь с администратором")



# Обрабатывает селфи для получения скидки. *
async def process_selfie(update: Update, context: CallbackContext):
    """Обрабатывает селфи для получения скидки."""
    user_id = update.effective_user.id
    tariff = context.user_data.get('tariff')

    photo = update.message.photo[-1]
    file_id = photo.file_id
    context.user_data['selfie_file_id'] = file_id

    await update.message.reply_text("Теперь отправьте описание, почему вы хотите получить эту скидку:")
    return WAIT_FOR_DESCRIPTION

# Обрабатывает описание для получения скидки."*
async def process_description(update: Update, context: CallbackContext):
    """Обрабатывает описание для получения скидки."""
    user_id = update.effective_user.id
    tariff = context.user_data.get('tariff')
    description = update.message.text
    context.user_data['description'] = description

    photo = context.user_data.get('selfie_file_id')

    # Формируем сообщение для администратора
    caption = f"Запрос на скидку!\nUser ID: {user_id}\nТариф: {tariff['title']}\nОписание: {description}"
    keyboard = [
        [
            InlineKeyboardButton("✅ Подтвердить скидку",
                                 callback_data=f'admin_approve_discount_{user_id}_{tariff["id"]}'),
            InlineKeyboardButton("❌ Отклонить скидку", callback_data=f'admin_reject_discount_{user_id}_{tariff["id"]}')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_photo(chat_id=ADMIN_GROUP_ID, photo=photo, caption=caption, reply_markup=reply_markup)
    await update.message.reply_text("Ваш запрос отправлен на рассмотрение администраторам.")
    return ConversationHandler.END

# Обрабатывает загруженный чек." *
async def process_check(update: Update, context: CallbackContext):
    """Обрабатывает загруженный чек."""
    user_id = update.effective_user.id
    tariff = context.user_data.get('tariff')
    photo = update.message.photo[-1]
    file_id = photo.file_id

    # Отправляем админам фото чека и информацию о покупке
    caption = f"Новый запрос на покупку!\nUser ID: {user_id}\nТариф: {tariff['title']}"
    keyboard = [
        [
            InlineKeyboardButton("✅ Подтвердить покупку",
                                 callback_data=f'admin_approve_purchase_{user_id}_{tariff["id"]}'),
            InlineKeyboardButton("❌ Отклонить покупку", callback_data=f'admin_reject_purchase_{user_id}_{tariff["id"]}')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_photo(chat_id=ADMIN_GROUP_ID, photo=file_id, caption=caption, reply_markup=reply_markup)

    await update.message.reply_text("Чек отправлен на проверку администраторам. Ожидайте подтверждения.")
    context.user_data.clear()  # Очищаем context.user_data
    return ConversationHandler.END


# Обрабатывает User ID получателя подарка. *
async def process_gift_user_id(update: Update, context: CallbackContext):
    """Обрабатывает User ID получателя подарка."""
    gift_user_id = update.message.text

    if not gift_user_id.isdigit():
        await update.message.reply_text("Пожалуйста, введите корректный User ID, состоящий только из цифр.")
        return WAIT_FOR_GIFT_USER_ID

    context.user_data['gift_user_id'] = gift_user_id
    user_id = update.effective_user.id
    tariff = context.user_data.get('tariff')
    # Инструкция по оплате
    text = f"Для оформления подарка, пожалуйста, переведите {tariff['price']} рублей на номер [номер] и загрузите чек сюда в этот диалог."  # Замените [сумма] и [номер]
    await update.message.reply_text(text)
    return WAIT_FOR_CHECK

# просим *
async def process_phone_number(update: Update, context: CallbackContext):
    contact = update.message.contact
    phone_number = contact.phone_number
    context.user_data['phone_number'] = phone_number

    user_id = update.effective_user.id
    tariff = context.user_data.get('tariff')
    # Формируем сообщение для администратора
    caption = f"Новый запрос на покупку!\nUser ID: {user_id}\nТариф: {tariff['title']}\nНомер телефона: {phone_number}"
    keyboard = [
        [
            InlineKeyboardButton("✅ Подтвердить покупку",
                                 callback_data=f'admin_approve_purchase_{user_id}_{tariff["id"]}'),
            InlineKeyboardButton("❌ Отклонить покупку", callback_data=f'admin_reject_purchase_{user_id}_{tariff["id"]}')
        ]
    ]
    photo = context.user_data.get('selfie_file_id')
    reply_markup = InlineKeyboardMarkup(keyboard)
    if photo:
        await context.bot.send_photo(chat_id=ADMIN_GROUP_ID, photo=photo, caption=caption, reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=caption, reply_markup=reply_markup)

    await update.message.reply_text("Ваш запрос отправлен на рассмотрение администраторам.")
    context.user_data.clear()  # Очищаем context.user_data
    return ConversationHandler.END


async def get_next_lesson_time(user_id):
    """Получает время следующего урока из базы данных."""
    try:
        cursor.execute('''
            SELECT next_lesson_time, submission_time FROM users WHERE user_id = ?
        ''', (user_id,))
        result = cursor.fetchone()

        if result and result[0]:
            next_lesson_time_str = result[0]
            try:
                next_lesson_time = datetime.datetime.strptime(next_lesson_time_str, '%Y-%m-%d %H:%M:%S')
                return next_lesson_time.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError as e:
                logger.error(f"Ошибка при парсинге времени: {e}, строка: {next_lesson_time_str}")
                return "время указано в неверном формате"
        else:
            # Если время не определено, устанавливаем его на 3 часа после submission_time
            cursor.execute('''
                SELECT submission_time FROM homeworks 
                WHERE user_id = ? AND status = 'pending'
                ORDER BY submission_time DESC LIMIT 1
            ''', (user_id,))
            submission_result = cursor.fetchone()

            if submission_result and submission_result[0]:
                submission_time_str = submission_result[0]
                submission_time = datetime.datetime.strptime(submission_time_str, '%Y-%m-%d %H:%M:%S')
                next_lesson_time = submission_time + datetime.timedelta(hours=DEFAULT_LESSON_DELAY_HOURS)
                next_lesson_time_str = next_lesson_time.strftime('%Y-%m-%d %H:%M:%S')

                # Обновляем время в базе данных
                cursor.execute('''
                    UPDATE users SET next_lesson_time = ? WHERE user_id = ?
                ''', (next_lesson_time_str, user_id))
                conn.commit()

                return next_lesson_time_str
            else:
                return "время пока не определено"
    except Exception as e:
        logger.error(f"Ошибка при получении времени следующего урока: {e}")
        return "время пока не определено"







async def show_gallery(update: Update, context: CallbackContext):
    await get_random_homework(update, context)

async def get_gallery_count():
    """
    Считает количество работ в галерее (реализация зависит от способа хранения галереи).
    """
    cursor.execute('SELECT COUNT(*) FROM homeworks WHERE status = "approved"')
    return cursor.fetchone()[0]

async def get_random_homework(update: Update, context: CallbackContext):
    query = update.callback_query
    if query:
        await query.answer()
        user_id = query.from_user.id
    else:
        user_id = update.effective_user.id

    # Получаем случайную одобренную работу
    cursor.execute('''
        SELECT hw_id, user_id, course_type, lesson, file_id 
        FROM homeworks 
        WHERE status = 'approved'
        ORDER BY RANDOM() 
        LIMIT 1
    ''')
    hw = cursor.fetchone()

    if not hw:
        # Если работ нет, показываем сообщение и возвращаем в основное меню
        if query:
            await query.edit_message_text("В галерее пока нет работ 😞\nХотите стать первым?")
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text="В галерее пока нет работ 😞\nХотите стать первым?"
            )
        await show_main_menu(update, context)  # Возвращаем в основное меню
        return

    hw_id, author_id, course_type, lesson, file_id = hw

    # Получаем информацию об авторе
    cursor.execute('SELECT full_name FROM users WHERE user_id = ?', (author_id,))
    author_name = cursor.fetchone()[0] or "Аноним"

    # Формируем текст сообщения
    text = f"📚 Курс: {course_type}\n"
    text += f"📖 Урок: {lesson}\n"
    text += f"👩🎨 Автор: {author_name}\n\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"
    text += "Чтобы увидеть другую работу - нажмите «Следующая»"

    # Создаем клавиатуру
    keyboard = [
        [InlineKeyboardButton("Следующая работа ➡️", callback_data='gallery_next')],
        [InlineKeyboardButton("Вернуться в меню ↩️", callback_data='menu_back')]
    ]

    try:
        # Отправляем файл с клавиатурой
        if query:
            await context.bot.edit_message_media(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                media=InputMediaPhoto(media=file_id, caption=text),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=file_id,
                caption=text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        # Если не фото, пробуем отправить как документ
        try:
            if query:
                await context.bot.edit_message_media(
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id,
                    media=InputMediaDocument(media=file_id, caption=text),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=file_id,
                    caption=text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        except Exception as e:
            logger.error(f"Ошибка отправки работы: {e}")
            await context.bot.send_message(
                chat_id=user_id,
                text="Не удалось загрузить работу 😞",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

def setup_admin_commands(application):
    """Настраивает команды администратора."""
    application.add_handler(CommandHandler("stats", show_stats))
    application.add_handler(CallbackQueryHandler(admin_approve_purchase, pattern='^admin_approve_purchase_'))
    application.add_handler(CallbackQueryHandler(admin_reject_purchase, pattern='^admin_reject_purchase_'))
    application.add_handler(CallbackQueryHandler(admin_approve_discount, pattern='^admin_approve_discount_'))
    application.add_handler(CallbackQueryHandler(admin_reject_discount, pattern='^admin_reject_discount_'))

def setup_user_commands(application):
    """Настраивает команды пользователя."""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_main_menu))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_homework_submission))
    application.add_handler(CallbackQueryHandler(tariff_callback, pattern='^tariff_'))


def main():
    application = ApplicationBuilder().token(TOKEN).persistence(persistence).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAIT_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_info)],
            WAIT_FOR_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code_words)],
            ACTIVE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message),
                CallbackQueryHandler(button_handler),
                MessageHandler(filters.PHOTO, handle_homework_submission),
                MessageHandler(filters.Document.IMAGE, handle_document),
            ],
            WAIT_FOR_SUPPORT_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND | filters.PHOTO, get_support_text)
            ],
            WAIT_FOR_SELFIE: [MessageHandler(filters.PHOTO, process_selfie)],
            WAIT_FOR_DESCRIPTION: [MessageHandler(filters.TEXT, process_description)],
            WAIT_FOR_CHECK: [MessageHandler(filters.PHOTO, process_check)],
            WAIT_FOR_GIFT_USER_ID: [MessageHandler(filters.TEXT, process_gift_user_id)],
            WAIT_FOR_PHONE_NUMBER: [MessageHandler(filters.CONTACT, process_phone_number) ],
        },
        fallbacks=[],
        persistent=True,  # Включаем персистентность
        name="my_conversation",
        allow_reentry=True
    )
    application.add_handler(conv_handler)

    setup_user_commands(application)
    setup_admin_commands(application)



    application.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    # Обработчик для кнопок предварительных материалов
    application.add_handler(CallbackQueryHandler(send_preliminary_material, pattern='^preliminary_'))

    application.job_queue.run_repeating(send_reminders, interval=60, first=10)  # Проверка каждую минуту
    application.add_handler(CommandHandler("reminders", reminders))
    application.add_handler(CommandHandler("set_morning", set_morning))
    application.add_handler(CommandHandler("set_evening", set_evening))
    application.add_handler(CommandHandler("disable_reminders", disable_reminders))
    application.add_handler(CommandHandler("stats", stats))

    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()

if __name__ == '__main__':
    main()
