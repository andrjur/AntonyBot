import logging
from telegram.ext import PicklePersistence
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaDocument
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




# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
ADMIN_IDS = os.getenv("ADMIN_IDS").split(',')

# состояния
USER_INFO, WAIT_FOR_CODE, ACTIVE, HOMEWORK_RESPONSE = range(4)

# Кодовые слова
CODE_WORDS = {
    "роза": ("main_course", "femininity", "no_check"),
    "фиалка": ("main_course", "femininity", "with_check"),
    "лепесток": ("main_course", "femininity", "premium"),
    "тыква": ("auxiliary_course", "autogenic", "no_check"),
    "слива": ("auxiliary_course", "autogenic", "with_check"),
    "молоко": ("auxiliary_course", "autogenic", "premium")
}

persistence = PicklePersistence(filepath="bot_data.pkl")

# Регулярное выражение для извлечения времени задержки из имени файла
DELAY_PATTERN = re.compile(r"_(\d+)([mh])$")

# Интервал между уроками по умолчанию (в часах)
DEFAULT_LESSON_INTERVAL = 0.3 # интервал уроков 72 часа

DEFAULT_LESSON_DELAY_HOURS = 3 # задержка между уроками

# if not os.access('bot_db.sqlite', os.W_OK):
#     logger.critical("Нет прав на запись в файл базы данных!")
#     sys.exit(1)

# Инициализация БД
conn = sqlite3.connect('bot_db.sqlite', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
try:
    cursor.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        full_name TEXT NOT NULL DEFAULT 'ЧЕБУРАШКА',
        main_course TEXT,
        auxiliary_course TEXT,
        main_paid INTEGER DEFAULT 0,
        auxiliary_paid INTEGER DEFAULT 0,
        main_current_lesson INTEGER DEFAULT 1,
        auxiliary_current_lesson INTEGER DEFAULT 1,
        main_homework_status TEXT DEFAULT 'none',
        auxiliary_homework_status TEXT DEFAULT 'none',
        main_last_homework_time DATETIME,
        auxiliary_last_homework_time DATETIME,
        penalty_task TEXT,
        main_last_message_id INTEGER,
        auxiliary_last_message_id INTEGER,
        preliminary_material_index INTEGER DEFAULT 0,
        main_tariff TEXT,
        auxiliary_tariff TEXT
    );

    CREATE TABLE IF NOT EXISTS homeworks (
        hw_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        course_type TEXT,
        lesson INTEGER,
        file_id TEXT,
        message_id INTEGER,
        status TEXT DEFAULT 'pending',
        feedback TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        submission_time DATETIME,
        approval_time DATETIME,
        admin_comment TEXT,  -- Добавлено поле для комментариев администратора
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

async def handle_user_info(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    full_name = update.effective_message.text.strip()

    # Логирование текущего состояния пользователя
    logger.info(f"{user_id} - Current state")

    # Проверка на пустое имя
    if not full_name:
        await update.effective_message.reply_text("Имя не может быть пустым. Введите ваше полное имя:")
        return USER_INFO

    try:
        # Сохранение имени пользователя в базе данных
        cursor.execute(
            """
            INSERT INTO users (user_id, full_name) 
            VALUES (?, ?)
            ON CONFLICT(user_id) DO 
            UPDATE SET full_name = excluded.full_name,
                      main_course = NULL,
                      auxiliary_course = NULL
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
        return USER_INFO

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



async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    # Логирование команды /start
    logger.info(f"{user_id} - start")

    # Получение данных о пользователе из базы данных
    cursor.execute(
        """
        SELECT user_id, main_course, auxiliary_course 
        FROM users 
        WHERE user_id = ?
        """,
        (user_id,),
    )
    user_data = cursor.fetchone()

    # Если пользователь не найден, запрашиваем имя
    if not user_data:
        await update.effective_message.reply_text("Пожалуйста, введите ваше имя:")
        return USER_INFO
    else:
        # Извлекаем данные пользователя
        _, main_course, auxiliary_course = user_data

        # Если курсы не активированы, запрашиваем кодовое слово
        if not main_course and not auxiliary_course:
            await update.effective_message.reply_text(
                "Для начала введите кодовое слово вашего курса:"
            )
            return WAIT_FOR_CODE
        else:
            # Если курсы активированы, показываем главное меню
            await show_main_menu(update, context)
            return ConversationHandler.END

async def show_main_menu(update: Update, context: CallbackContext):
    logger.info(
        f"{update.effective_user.id} - show_main_menu")

    user = update.effective_user
    message = update.effective_message  # Используем effective_message вместо message

    cursor.execute('SELECT main_course, auxiliary_course, main_current_lesson FROM users WHERE user_id = ?', (user.id,))
    user_data = cursor.fetchone()

    if not user_data:
        await message.reply_text("Пожалуйста, введите ваше имя, чтобы начать.")
        return
    main_course, auxiliary_course, main_current_lesson = user_data
    # Формируем приветствие
    cursor.execute('SELECT full_name FROM users WHERE user_id = ?', (user.id,))
    full_name = cursor.fetchone()[0]
    greeting_text = f"Привет, {full_name.split()[0]}!"  # Берём имя из базы

    # Определяем курс и статус ДЗ
    if main_course:
        homework_status = await get_homework_status_text(user.id, 'main_course')
        greeting_text += f"\nТы на курсе '{main_course}'  (домашка {homework_status})."
        greeting_text += " Просто отправь в чат картинку или фотографию."

    else:
        greeting_text += "\nЧтобы начать, введи кодовое слово для активации курса."

    # Формируем кнопки
    keyboard = await create_main_menu_keyboard(user.id, main_course)

    # Отправляем сообщение
    await message.reply_text(greeting_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def get_homework_status_text(user_id, course_type):
    cursor.execute(f'''
    SELECT hw_id, lesson, status FROM homeworks 
    WHERE user_id = ? AND course_type = ? AND status = 'pending'
    ''', (user_id, course_type))
    pending_hw = cursor.fetchone()

    if pending_hw:
        hw_id, lesson, status = pending_hw
        return f"домашку по {lesson} уроку"  # или f"домашнюю работу по {lesson} уроку (id {hw_id})", если id тоже важен
    else:
        return " :-) "  # можно "не жду никаких домашних заданий"

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

def get_lesson_text(user_id, lesson_number, course_type):
    # Определение названия курса на основе типа курса
    if course_type == 'main_course':
        cursor.execute('SELECT main_course FROM users WHERE user_id = ?', (user_id,))
    else:
        cursor.execute('SELECT auxiliary_course FROM users WHERE user_id = ?', (user_id,))
    course = cursor.fetchone()[0]

    try:
        with open(f'courses/{course}/lesson{lesson_number}.txt', 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        logger.error(f"Файл урока не найден: 'courses/{course}/lesson{lesson_number}.txt'")
        return None

async def send_lesson(update: Update, context: CallbackContext, course_type: str):
    """
    Отправляет пользователю следующий урок.
    """
    user = update.effective_user
    try:
        # Получаем текущий урок из базы данных
        if course_type == "main_course":
            lesson_field = "main_current_lesson"
            course_field = "main_course"
        elif course_type == "auxiliary_course":
            lesson_field = "auxiliary_current_lesson"
            course_field = "auxiliary_course"
        else:
            await context.bot.send_message(chat_id=user.id, text="Ошибка: Неверный тип курса.")
            return

        cursor.execute(f'SELECT {lesson_field}, {course_field} FROM users WHERE user_id = ?', (user.id,))
        lesson_data = cursor.fetchone()
        if not lesson_data:
            await context.bot.send_message(chat_id=user.id, text="Ошибка: Не найдены данные пользователя.")
            return

        current_lesson, course_name = lesson_data
        next_lesson = current_lesson + 1

        # Получаем текст урока
        lesson_text = get_lesson_text(user.id, next_lesson, course_type)
        if not lesson_text:
            await context.bot.send_message(chat_id=user.id, text="Урок не найден.")
            return

        # Отправляем текст урока
        await context.bot.send_message(chat_id=user.id, text=lesson_text)

        # Получаем список всех файлов для урока
        lesson_dir = f'courses/{course_name}/'
        files = [
            f for f in os.listdir(lesson_dir)
            if f.startswith(f'lesson{next_lesson}_') and os.path.isfile(os.path.join(lesson_dir, f))
        ]

        # Отправляем файлы без задержки
        for file in files:
            file_path = os.path.join(lesson_dir, file)
            delay_seconds = parse_delay_from_filename(file)
            if not delay_seconds:  # Отправляем только файлы без задержки
                await send_file(context.bot, user.id, file_path, file)

        # Обновляем номер текущего урока
        cursor.execute(f'UPDATE users SET {lesson_field} = ? WHERE user_id = ?', (next_lesson, user.id))
        conn.commit()

        # Сообщение с ожиданием домашней работы
        await context.bot.send_message(
            chat_id=user.id,
            text="Жду домашнюю работу в виде фото или картинки. После принятия домашки - ждём след урока и по желанию смотрим предварительные материалы"
        )

        # Показываем основное меню
        await show_main_menu(update, context)

    except Exception as e:
        logger.error(f"Ошибка при отправке урока: {e}")
        await context.bot.send_message(chat_id=user.id, text="Произошла ошибка при отправке урока. Попробуйте позже.")

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

async def create_main_menu_keyboard(user_id, course_type):

    keyboard = [
        [InlineKeyboardButton("Галерея работ", callback_data='gallery')],
        [InlineKeyboardButton("Поддержка/Тарифы", callback_data='support')]
    ]

    # Получаем курс пользователя
    main_course, auxiliary_course = get_user_courses(user_id)
    active_course_type = 'main_course' if main_course else 'auxiliary_course'

    preliminary_button = await add_preliminary_button(user_id, active_course_type)
    if preliminary_button:
        keyboard.insert(0, [preliminary_button])

    return keyboard

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
    if result:
        average_time_seconds = int(result)
        hours, remainder = divmod(average_time_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours} часов {minutes} минут"
    else:
        return "Нет данных"

async def continue_course(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    cursor.execute(
        'SELECT main_course, auxiliary_course, main_current_lesson, auxiliary_current_lesson FROM users WHERE user_id = ?',
        (user_id,))
    user_data = cursor.fetchone()

    if not user_data:
        return False  # Пользователь не найден

    main_course, auxiliary_course, main_lesson, auxiliary_lesson = user_data

    if main_course:
        # Получаем информацию о последней домашней работе
        cursor.execute(
            'SELECT hw_id, lesson FROM homeworks WHERE user_id = ? AND course_type = ? AND status = ? ORDER BY timestamp DESC LIMIT 1',
            (user_id, 'main_course', 'pending'))
        pending_hw = cursor.fetchone()

        if pending_hw:
            hw_id, lesson = pending_hw

            # Получаем информацию о пользователе
            cursor.execute(
                'SELECT main_course, main_paid, main_current_lesson, main_homework_status FROM users WHERE user_id = ?',
                (user_id,))
            course_data = cursor.fetchone()
            main_course, main_paid, main_current_lesson, main_homework_status = course_data

            bonuses = ""  # заглушка для будущих бонусов

            # Формируем текст сообщения
            text = f"У вас есть незавершенное домашнее задание по курсу {main_course}, урок {lesson}.\n"
            text += f"Ваши бонусы: {bonuses}\n"

            # Вычисляем оставшееся время
            cursor.execute('SELECT submission_time FROM homeworks WHERE hw_id = ?', (hw_id,))
            submission_time = cursor.fetchone()[0]
            if submission_time:
                submission_time = datetime.fromisoformat(submission_time)
                deadline = submission_time + timedelta(hours=72)
                time_left = deadline - datetime.now()
                hours_left = int(time_left.total_seconds() / 3600)
                text += f"Осталось времени: {hours_left} часов\n\n"
            else:
                text += "Время отправки ДЗ не найдено.\n\n"

            text += "Отправьте фото для проверки:"

            # Формируем кнопки
            keyboard = [
                [InlineKeyboardButton("Повторить все материалы урока", callback_data=f"repeat_lesson_{lesson}")],
                [InlineKeyboardButton("Посмотреть домашки других", callback_data=f"view_other_hw_{lesson}")]
            ]

            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return True  # Есть что продолжить

        # Если нет незавершенного ДЗ, предлагаем получить следующий урок
        # Получаем параметры прохождения
        average_time = get_average_homework_time(user_id)
        cursor.execute('SELECT main_course, main_paid, main_current_lesson, main_homework_status FROM users WHERE user_id = ?', (user_id,))
        course_data = cursor.fetchone()
        main_course, main_paid, main_current_lesson, main_homework_status = course_data

        # Формируем текст
        text = f"Здравствуйте, {update.effective_user.full_name}!\n"
        text += f"Ваш курс: {main_course}\n"
        text += f"Оплачен: {'Да' if main_paid else 'Нет'}\n"
        text += f"Текущий урок: {main_current_lesson}\n"
        text += f"Статус ДЗ: {main_homework_status}\n"
        text += f"Вы сдаете ДЗ в среднем за: {average_time}\n\n"
        text += "ВВЕДИТЕ КОДОВОЕ СЛОВО ИЛИ нажмите кнопку:"

        # Формируем кнопки
        # Проверяем, является ли пользователь VIP
        cursor.execute('SELECT main_course, auxiliary_course FROM users WHERE user_id = ?', (update.effective_user.id,))
        main_course, auxiliary_course = cursor.fetchone()

        is_vip = False
        if main_course == 'femininity':
            cursor.execute('SELECT main_paid FROM users WHERE user_id = ?', (update.effective_user.id,))
            main_paid = cursor.fetchone()[0]
            if main_paid == 3:  # 3 - Premium
                is_vip = True
        elif auxiliary_course == 'autogenic':
            cursor.execute('SELECT auxiliary_paid FROM users WHERE user_id = ?', (update.effective_user.id,))
            auxiliary_paid = cursor.fetchone()[0]
            if auxiliary_paid == 3:  # 3 - Premium
                is_vip = True

        keyboard = [
            [InlineKeyboardButton("💰 Повысить тариф", callback_data='tariffs'),
             InlineKeyboardButton("📸 Отправить ДЗ", callback_data='send_hw')],
            [InlineKeyboardButton("👥 Галерея работ", callback_data='gallery')],
            [InlineKeyboardButton("🆘 Поддержка", callback_data='support')],
            [InlineKeyboardButton("Случайный анекдот", callback_data='random_joke')]
        ]

        # Добавляем кнопку "Получить предварительные материалы", только если они есть
        preliminary_button = await add_preliminary_button(update.effective_user.id, 'main_course')
        if preliminary_button:
            keyboard.insert(0, [preliminary_button])  # Добавляем в начало

        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return True
    return False

async def handle_admin_approval(update: Update, context: CallbackContext):
    query = update.callback_query
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


async def save_admin_comment(update: Update, context: CallbackContext):
    """
    Сохраняет комментарий админа и обновляет статус ДЗ.
    """
    logger.info(
        f"{update.effective_user.id} - Current state: {await context.application.persistence.get_user(update.effective_user.id)}")

    user_id = update.effective_user.id
    cursor.execute('SELECT admin_id FROM admins WHERE admin_id = ?', (user_id,))
    if not cursor.fetchone():
        await update.message.reply_text("⛔ Команда только для админов")
        return  # Прекращаем выполнение функции для не-админов
    hw_id = context.user_data.get('awaiting_comment')
    approval_status = context.user_data.pop('approval_status', None)

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

async def handle_admin_rejection(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    hw_id = query.data.split('_')[2]
    cursor.execute('UPDATE homeworks SET status = "rejected" WHERE hw_id = ?', (hw_id,))
    conn.commit()
    await query.edit_message_text(f"ДЗ {hw_id} отклонено")

async def show_tariffs(update: Update, context: CallbackContext):
    await update.message.reply_text("Здесь будут тарифы")

async def request_homework(update: Update, context: CallbackContext):
    # Добавьте в начало каждой функции:
    logger.info(
        f"{update.effective_user.id} - Current state: {await context.application.persistence.get_user(update.effective_user.id)}")

    await update.message.reply_text("Отправьте вашу домашнюю работу (фото или файл):")
    return HOMEWORK_RESPONSE  # Переходим в состояние ожидания ДЗ

async def save_homework(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    file_id = None

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document and update.message.document.mime_type.startswith('image/'):
        file_id = update.message.document.file_id

    try:
        # Определяем активный курс
        cursor.execute('''
                SELECT main_course, auxiliary_course, main_current_lesson 
                FROM users WHERE user_id = ?
            ''', (user_id,))
        main_course, auxiliary_course, current_lesson = cursor.fetchone()

        course_type = "main_course" if main_course else "auxiliary_course"
        course_name = main_course or auxiliary_course
        lesson = current_lesson - 1  # Текущий урок уже увеличен после отправки

        # Сохраняем ДЗ в БД
        cursor.execute('''
                INSERT INTO homeworks 
                (user_id, course_type, lesson, file_id, message_id, status, submission_time) 
                VALUES (?, ?, ?, ?, NULL, 'pending', DATETIME('now'))
            ''', (user_id, course_type, lesson, file_id))
        conn.commit()

        # Получаем ID только что вставленной записи
        hw_id = cursor.lastrowid

        # Формируем callback_data для самоодобрения
        self_approve_callback_data = f"self_approve|{course_type}|{hw_id}"

        # Отправляем уведомление пользователю с кнопкой самоодобрения
        confirmation_message = await update.message.reply_text(
            "✅ Домашка принята! Хотите самоодобрять?",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🚀 Самоодобряю", callback_data=self_approve_callback_data),
                ]
            ])
        )

        # Сохраняем ID сообщения для последующего удаления
        context.user_data['homework_message_id'] = confirmation_message.message_id
        logger.info(f"confirmation_message.message_id: {confirmation_message.message_id}")

        # Формируем callback_data с разделителем "|"
        approve_callback_data = f"approve|{course_type}|{hw_id}"
        reject_callback_data = f"reject|{course_type}|{hw_id}"

        # Логируем callback_data перед отправкой сообщения
        logger.info(f"approve_callback_data: {approve_callback_data}")
        logger.info(f"reject_callback_data: {reject_callback_data}")

        # Отправляем уведомление админам с повторными попытками
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Sending homework to admin group (attempt {attempt + 1}): chat_id={ADMIN_GROUP_ID}, file_id={file_id}")
                admin_message = await context.bot.send_photo(
                    chat_id=ADMIN_GROUP_ID,
                    photo=file_id,
                    caption=f"Новое ДЗ!\n"
                            f"User ID: {user_id}\n"
                            f"Курс: {course_name}\n"
                            f"Урок: {lesson}",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ Принять", callback_data=approve_callback_data),
                            InlineKeyboardButton("❌ Отклонить", callback_data=reject_callback_data)
                        ]
                    ])
                )
                logger.info(f"Successfully sent homework to admin group. Message ID: {admin_message.message_id}")
                break  # Если отправка прошла успешно, выходим из цикла

            except TelegramError as e:
                logger.error(f"Ошибка при отправке ДЗ админам (попытка {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)  # Ждем 2 секунды перед следующей попыткой
                else:
                    logger.error("Превышено максимальное количество попыток отправки ДЗ админам.")
                    await update.message.reply_text("⚠️ Ошибка при отправке работы администраторам. Попробуйте позже.")
                    return

        # Сохраняем ID сообщения в БД
        cursor.execute('''
                        UPDATE homeworks 
                        SET message_id = ? 
                        WHERE hw_id = ?
                    ''', (admin_message.message_id, hw_id))
        conn.commit()

        await update.message.reply_text("✅ Домашка принята! Админ проверит её в течение 24 часов.")
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка сохранения ДЗ: {e}")
        await update.message.reply_text("⚠️ Ошибка при сохранении работы. Попробуйте ещё раз.")
        return ConversationHandler.END

async def self_approve_homework(update: Update, context: CallbackContext):
    """Обрабатывает нажатие кнопки '🚀 Самоодобряю' пользователем."""
    query = update.callback_query
    await query.answer()

    # Логируем callback_data для отладки
    callback_data = query.data
    logger.info(f"Получено callback_data: {callback_data}")

    # Разделяем данные из callback_data
    parts = callback_data.split('|')
    if len(parts) != 3:
        logger.error(f"Неверный формат callback_data: {callback_data}")
        await query.message.reply_text("⚠️ Неверный формат данных. Попробуйте ещё раз.")
        return

    action = parts[0]  # self_approve
    course_type = parts[1]  # main_course или auxiliary_course
    try:
        hw_id = int(parts[2])  # ID домашней работы
        logger.info(f"Действие: {action}, Курс: {course_type}, ID домашней работы: {hw_id}")
    except ValueError as e:
        logger.error(f"Ошибка при извлечении hw_id из callback_data: {e}")
        await query.message.reply_text("⚠️ Ошибка в ID домашней работы. Попробуйте ещё раз.")
        return

    if action == "self_approve":
        try:
            # Обновляем статус ДЗ в БД
            cursor.execute('''
                UPDATE homeworks 
                SET status = 'self_approved', 
                    approval_time = DATETIME('now') 
                WHERE hw_id = ?
            ''', (hw_id,))
            conn.commit()

            # Получаем message_id из context.user_data
            homework_message_id = context.user_data.get('homework_message_id')
            if homework_message_id:
                try:
                    # Удаляем сообщение "✅ Домашка принята! Админ проверит её в течение 24 часов."
                    await context.bot.delete_message(
                        chat_id=query.message.chat_id,
                        message_id=homework_message_id
                    )
                except Exception as e:
                    logger.error(f"Ошибка при удалении сообщения: {e}")

            # Выводим инлайн-меню
            inline_keyboard = [
                [InlineKeyboardButton("Следующий урок", callback_data="next_lesson")],
                [InlineKeyboardButton("Профиль", callback_data="profile")],
                [InlineKeyboardButton("Галерея", callback_data="gallery")],
                [InlineKeyboardButton("Поддержка", callback_data="support")]
            ]
            markup = InlineKeyboardMarkup(inline_keyboard)

            # Добавляем логику для показа времени следующего урока
            next_lesson_time = await get_next_lesson_time(query.from_user.id)
            menu_text = f"🎉 Домашка самоодобрена! Возвращаемся в основное меню.\nСледующий урок будет доступен {next_lesson_time}."

            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=menu_text,
                reply_markup=markup
            )

        except Exception as e:
            logger.error(f"Ошибка при самоодобрении ДЗ: {e}")
            await query.message.reply_text("⚠️ Ошибка при самоодобрении работы. Попробуйте ещё раз.")

async def handle_inline_buttons(update: Update, context: CallbackContext):
    """Обрабатывает нажатие инлайн-кнопок."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "next_lesson":
        await query.message.reply_text("📘 Вот ваш следующий урок!")
    elif data == "profile":
        await query.message.reply_text("👤 Вот информация о вашем профиле!")
    elif data == "gallery":
        await query.message.reply_text("🖼️ Вот ваша галерея!")
    elif data == "support":
        await query.message.reply_text("📞 Свяжитесь с поддержкой!")


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

async def handle_photo(update: Update, context: CallbackContext):
    """Обрабатывает отправленные пользователем фотографии."""
    await save_homework(update, context)

async def handle_document(update: Update, context: CallbackContext):
    """Обрабатывает отправленные пользователем документы."""
    if update.message.document.mime_type.startswith('image/'):
        await save_homework(update, context)
    else:
        await update.message.reply_text("⚠️ Отправьте, пожалуйста, картинку или фотографию.")

async def approve_homework(update: Update, context: CallbackContext):
    """Обрабатывает нажатие кнопок 'Принять' или 'Отклонить' администратором."""
    query = update.callback_query
    await query.answer()

    # Логируем callback_data для отладки
    callback_data = query.data
    logger.info(f"Получено callback_data: {callback_data}")

    # Разделяем данные из callback_data
    parts = callback_data.split('|')
    if len(parts) != 3:
        logger.error(f"Неверный формат callback_data: {callback_data}")
        await query.message.reply_text("⚠️ Неверный формат данных. Попробуйте ещё раз.")
        return

    action = parts[0]  # approve или reject
    course_type = parts[1]  # main_course или auxiliary_course
    try:
        hw_id = int(parts[2])  # ID домашней работы
        logger.info(f"Действие: {action}, Курс: {course_type}, ID домашней работы: {hw_id}")
    except ValueError as e:
        logger.error(f"Ошибка при извлечении hw_id из callback_data: {e}")
        await query.message.reply_text("⚠️ Ошибка в ID домашней работы. Попробуйте ещё раз.")
        return

    if action == "approve":
        try:
            # Обновляем статус ДЗ в БД
            cursor.execute('''
                UPDATE homeworks
                SET status = 'approved',
                    approval_time = DATETIME('now')
                WHERE hw_id = ?
            ''', (hw_id,))
            conn.commit()

            # Получаем user_id и lesson
            cursor.execute('SELECT user_id, lesson FROM homeworks WHERE hw_id = ?', (hw_id,))
            user_id, lesson = cursor.fetchone()

            # Получаем homework_message_id из context.user_data
            homework_message_id = context.user_data.get('homework_message_id')
            if homework_message_id:
                try:
                    # Редактируем сообщение, чтобы убрать кнопку и изменить текст
                    inline_keyboard = [
                        [InlineKeyboardButton("Следующий урок", callback_data="next_lesson")],
                        [InlineKeyboardButton("Профиль", callback_data="profile")],
                        [InlineKeyboardButton("Галерея", callback_data="gallery")],
                        [InlineKeyboardButton("Поддержка", callback_data="support")]
                    ]
                    markup = InlineKeyboardMarkup(inline_keyboard)

                    next_lesson_time = await get_next_lesson_time(user_id)
                    await context.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=homework_message_id,
                        text=f"🎉 Ваша домашка по {lesson} уроку принята!\nСледующий урок будет доступен {next_lesson_time}.",
                        reply_markup=markup
                    )
                except Exception as e:
                    logger.error(f"Ошибка при редактировании сообщения: {e}")
            else:
                logger.warning("Не найден homework_message_id в context.user_data")

            # Редактируем сообщение в админ-группе
            await context.bot.edit_message_reply_markup(
                chat_id=ADMIN_GROUP_ID,
                message_id=query.message.message_id,
                reply_markup=None  # Убираем кнопки
            )
            await context.bot.edit_message_caption(
                chat_id=ADMIN_GROUP_ID,
                message_id=query.message.message_id,
                caption=query.message.caption + "\n\n✅ Принято!"
            )

        except Exception as e:
            logger.error(f"Ошибка при обновлении ДЗ в БД: {e}")
            await query.message.reply_text("⚠️ Ошибка при принятии работы. Попробуйте ещё раз.")
    elif action == "reject":
        try:
            # Обновляем статус ДЗ в БД
            cursor.execute('''
                UPDATE homeworks
                SET status = 'rejected'
                WHERE hw_id = ?
            ''', (hw_id,))
            conn.commit()

            # Получаем user_id и lesson
            cursor.execute('SELECT user_id, lesson FROM homeworks WHERE hw_id = ?', (hw_id,))
            user_id, lesson = cursor.fetchone()

            # Получаем homework_message_id из context.user_data
            homework_message_id = context.user_data.get('homework_message_id')
            if homework_message_id:
                try:
                    # Редактируем сообщение, чтобы убрать кнопку и изменить текст
                    await context.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=homework_message_id,
                        text=f"❌ Ваша домашка по {lesson} уроку отклонена! Попробуйте ещё раз.",
                        reply_markup=None  # Убираем кнопки
                    )
                except Exception as e:
                    logger.error(f"Ошибка при редактировании сообщения: {e}")
            else:
                logger.warning("Не найден homework_message_id в context.user_data")

            # Редактируем сообщение в админ-группе
            await context.bot.edit_message_reply_markup(
                chat_id=ADMIN_GROUP_ID,
                message_id=query.message.message_id,
                reply_markup=None  # Убираем кнопки
            )
            await context.bot.edit_message_caption(
                chat_id=ADMIN_GROUP_ID,
                message_id=query.message.message_id,
                caption=query.message.caption + "\n\n❌ Отклонено!"
            )

        except Exception as e:
            logger.error(f"Ошибка при отклонении ДЗ в БД: {e}")
            await query.message.reply_text("⚠️ Ошибка при отклонении работы. Попробуйте ещё раз.")
    else:
        logger.warning(f"Неизвестное действие в callback_data: {action}")
        await query.message.reply_text("⚠️ Неизвестное действие. Попробуйте ещё раз.")

def get_user_courses(user_id):
    cursor.execute('SELECT main_course, auxiliary_course FROM users WHERE user_id = ?', (user_id,))
    return cursor.fetchone()

def get_current_lesson(user_id, course_type):
    lesson_field = f"{course_type}_current_lesson"
    cursor.execute(f'SELECT {lesson_field} FROM users WHERE user_id = ?', (user_id,))
    return cursor.fetchone()[0]

async def handle_code_words(update: Update, context: CallbackContext):
    """
    Обрабатывает введенное пользователем кодовое слово, активирует курс и отправляет первый урок.
    """
    user = update.effective_user
    text = update.message.text.strip().lower()
    logger.info(f"{user.id} - Entered code: {text}")

    if text in CODE_WORDS:
        course_type, course_name, tariff = CODE_WORDS[text]
        prefix = course_type.split('_')[0]

        try:
            # Обновляем информацию о курсе пользователя в базе данных
            if course_type == "main_course":
                cursor.execute(
                    """
                    UPDATE users 
                    SET main_course = ?, main_tariff = ?
                    WHERE user_id = ?
                    """,
                    (course_name, tariff, user.id),
                )
            elif course_type == "auxiliary_course":
                cursor.execute(
                    """
                    UPDATE users 
                    SET auxiliary_course = ?, auxiliary_tariff = ?
                    WHERE user_id = ?
                    """,
                    (course_name, tariff, user.id),
                )
            conn.commit()

            await update.message.reply_text(
                f"Курс '{course_name}' успешно активирован! Тариф: {tariff}"
            )
            # Отправляем первый урок сразу после активации
            if course_type == "main_course":
                await send_lesson(update, context, "main_course")  # Отправляем урок
            elif course_type == "auxiliary_course":
                await send_lesson(update, context, "auxiliary_course")  # Отправляем урок
            return ConversationHandler.END

        except Exception as e:
            logger.error(f"Ошибка при активации курса: {e}")
            await update.message.reply_text(
                "Произошла ошибка при активации курса. Попробуйте снова."
            )
            return WAIT_FOR_CODE
    else:
        await update.message.reply_text("Неверное кодовое слово. Попробуйте еще раз.")
        return WAIT_FOR_CODE

async def request_support(update: Update, context: CallbackContext):
    await update.message.reply_text("Напишите ваш вопрос, и мы свяжемся с вами.")

async def get_lesson(update: Update, context: CallbackContext):
    user = update.effective_user
    # Определение типа курса
    if update.callback_query:
        query = update.callback_query
        course_type = query.data.split('_')[2]  # Извлекаем из callback_data
    else:
        # Если команда /start
        # TODO: Нужно определять курс как-то иначе
        course_type = 'main_course'

    # Запрашиваем урок
    await send_lesson(update, context, course_type)

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

async def button_handler(update: Update, context: CallbackContext):
    # Добавьте в начало каждой функции:
    logger.info(
        f"{update.effective_user.id} - Current state: {await context.application.persistence.get_user(update.effective_user.id)}")

    query = update.callback_query
    data = query.data
    await query.answer()  # Always answer callback queries

    if data == 'gallery':
        await show_gallery(update, context)
    elif data == 'gallery_next':
        await get_random_homework(update, context)
    elif data == 'menu_back':
        await show_main_menu(update, context) # Возвращаем в основное меню
    if data == 'tariffs':
        await show_tariffs(update, context)
    elif data == 'send_hw':
        await request_homework(update, context)
    elif data == 'get_lesson':
        await get_lesson(update, context)
    elif data == 'gallery':
        await show_gallery(update, context)
    elif data == 'support':
        await request_support(update, context)
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
        # Получаем информацию о пользователе
        user_id = update.effective_user.id
        cursor.execute('SELECT main_course, auxiliary_course FROM users WHERE user_id = ?', (user_id,))
        main_course, auxiliary_course = cursor.fetchone()

        # Определяем тип курса
        course_type = 'main_course' if main_course else 'auxiliary_course'

        # Вызываем функцию send_lesson для повторной отправки урока
        await send_lesson(update, context, course_type)
        logger.info(f"повторно отправляем урок {user_id}")

# Добавляем новую функцию для обработки текстовых сообщений в состоянии ACTIVE
async def handle_active_state(update: Update, context: CallbackContext):
    # Добавьте в начало каждой функции:
    logger.info(
        f"{update.effective_user.id} - Current state: {await context.application.persistence.get_user(update.effective_user.id)}")

    user = update.effective_user
    text = update.message.text.lower()

    # Проверяем, является ли текст кодовым словом
    if text in CODE_WORDS:
        # Если это кодовое слово, обрабатываем его
        await handle_code_words(update, context)
    elif text == "/start":
        return await start(update, context)
    else:
        # Иначе просто игнорируем или показываем подсказку
        await update.message.reply_text("Используйте кнопки меню для навигации.")
        return ACTIVE
# Состояния для ConversationHandler
USER_INFO, = range(1)
HOMEWORK_RESPONSE, = range(1)

def main():

    application = ApplicationBuilder().token(TOKEN).persistence(persistence).build()

    # Основной ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            USER_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_info)],
            WAIT_FOR_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code_words),
                CommandHandler("start", start)  # Разрешить перезапуск
            ],
            ACTIVE: [CallbackQueryHandler(button_handler)]
        },
        fallbacks=[CommandHandler("start", start)],
        persistent=True,  # Включаем персистентность
        name="my_conversation",
        allow_reentry=True
    )
    # ТОЛЬКО ЭТОТ ОБРАБОТЧИК НУЖЕН
    application.add_handler(conv_handler)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(r"^(Следующий урок|Профиль|Галерея|Поддержка)$"),
                   handle_code_words))  # Затем другие


    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))



    # Обработчик для кнопок предварительных материалов
    application.add_handler(CallbackQueryHandler(send_preliminary_material, pattern='^preliminary_'))

    application.add_handler(CallbackQueryHandler(approve_homework, pattern=r'^(approve|reject)\|.+$'))
    application.add_handler(CallbackQueryHandler(self_approve_homework, pattern=r'^self_approve\|.+$'))
    application.add_handler(
        CallbackQueryHandler(handle_inline_buttons, pattern=r'^(next_lesson|profile|gallery|support)$'))

    application.job_queue.run_repeating(send_reminders, interval=60, first=10)  # Проверка каждую минуту
    application.add_handler(CommandHandler("reminders", reminders))
    application.add_handler(CommandHandler("set_morning", set_morning))
    application.add_handler(CommandHandler("set_evening", set_evening))
    application.add_handler(CommandHandler("disable_reminders", disable_reminders))
    application.add_handler(CommandHandler("stats", stats))

    application.run_polling()

if __name__ == '__main__':
    main()
