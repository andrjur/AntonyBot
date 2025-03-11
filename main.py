import secrets
import string
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaDocument
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext, \
    CallbackQueryHandler, ConversationHandler
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import re



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

USER_INFO, WAIT_FOR_CODE, ACTIVE = range(3)

# Кодовые слова
CODE_WORDS = {
    "роза": ("main_course", "femininity", "no_check"),
    "фиалка": ("main_course", "femininity", "with_check"),
    "лепесток": ("main_course", "femininity", "premium"),
    "тыква": ("auxiliary_course", "autogenic", "no_check"),
    "слива": ("auxiliary_course", "autogenic", "with_check"),
    "молоко": ("auxiliary_course", "autogenic", "premium")
}

# Регулярное выражение для извлечения времени задержки из имени файла
DELAY_PATTERN = re.compile(r"_(\d+)([mh])$")

# Интервал между уроками по умолчанию (в часах)
DEFAULT_LESSON_INTERVAL = 0.04

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
        main_current_lesson INTEGER DEFAULT 0,
        auxiliary_current_lesson INTEGER DEFAULT 0,
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

def generate_admin_code(length=3):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

async def handle_admin_code(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    text = update.message.text

    # Проверяем, является ли пользователь админом
    cursor.execute('SELECT admin_id FROM admins WHERE admin_id = ?', (user_id,))
    admin = cursor.fetchone()

    if admin:
        # Проверяем, является ли введенный текст кодовым словом админа
        cursor.execute('SELECT code FROM admin_codes WHERE user_id = ? AND code = ?', (user_id, text))
        code = cursor.fetchone()

        if code:
            # Удаляем использованный код
            cursor.execute('DELETE FROM admin_codes WHERE user_id = ? AND code = ?', (user_id, text))
            conn.commit()

            # Показываем админ-меню
            await show_admin_menu(update, context)
        else:
            await update.message.reply_text("Неверный кодовый админ.")
    else:
        await update.message.reply_text("У вас нет прав для использования этой команды.")


async def handle_user_info(update: Update, context: CallbackContext):
    user = update.effective_user
    full_name = update.message.text.strip()

    if not full_name:
        await update.message.reply_text("Имя не может быть пустым. Введите ваше полное имя:")
        return USER_INFO
    try:
        # Сохраняем имя и сбрасываем курс при первом вводе
        cursor.execute('''
                   INSERT INTO users (user_id, full_name, main_course, auxiliary_course) 
                   VALUES (?, ?, NULL, NULL)
                   ON CONFLICT(user_id) DO UPDATE SET full_name = excluded.full_name
               ''', (user.id, full_name))
        conn.commit()

        # Проверяем запись
        cursor.execute('SELECT full_name FROM users WHERE user_id = ?', (user.id,))
        saved_name = cursor.fetchone()[0]
        if saved_name != full_name:
            #raise ValueError("Имя не совпадает с сохраненным")
            logger.error(f"Имя не совпадает с сохраненным {saved_name} != {full_name}")
            print(f"Имя не совпадает с сохраненным {saved_name} != {full_name}")

        await update.message.reply_text(f"Отлично, {full_name}! Теперь введите кодовое слово для активации курса.")
        return WAIT_FOR_CODE  # Переходим в состояние ожидания код

    except Exception as e:
        logger.error(f"Ошибка при сохранении имени: {e}")
        logger.error(f"Ошибка SQL при сохранении пользователя {user.id}: {e}")
        await update.message.reply_text("Произошла ошибка при сохранении данных. Попробуйте снова.")
        return USER_INFO

async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    cursor.execute('''
        SELECT user_id, main_course, auxiliary_course 
        FROM users 
        WHERE user_id = ?
    ''', (user.id,))
    user_data = cursor.fetchone()

    if not user_data:
        await update.message.reply_text("Пожалуйста, введите ваше имя:")
        return USER_INFO
    else:
        user_id, main_course, auxiliary_course = user_data
        if not main_course and not auxiliary_course:
            await update.message.reply_text("Для начала введите кодовое слово вашего курса:")
            return WAIT_FOR_CODE
        else:
            await show_main_menu(update, context)
        return ACTIVE

async def show_admin_menu(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("Одобрить ДЗ", callback_data='approve_hw')],
        [InlineKeyboardButton("Статистика", callback_data='stats')]
    ]
    await update.message.reply_text(
        "Админ-меню:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_main_menu(update: Update, context: CallbackContext):
    user = update.effective_user
    message = update.effective_message  # Используем effective_message вместо message

    cursor.execute('SELECT main_course, auxiliary_course, main_current_lesson FROM users WHERE user_id = ?', (user.id,))
    user_data = cursor.fetchone()

    if not user_data:
        await message.reply_text("Пожалуйста, введите ваше имя, чтобы начать.")
        return
    main_course, auxiliary_course, main_current_lesson = user_data
    # Формируем приветствие
    greeting_text = f"Привет, {user.first_name}!"

    # Определяем курс и статус ДЗ
    if main_course:
        homework_status = await get_homework_status_text(user.id, 'main_course')
        greeting_text += f"\nТы на курсе '{main_course}' и я жду от тебя {homework_status}."

        # Добавляем предложение отправить ДЗ, если его нет
        if "не жду" in homework_status.lower():
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
        return "не жду никакую домашку"  # можно "не жду никаких домашних заданий"

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
                await bot.send_document(chat_id=chat_id, document=document)
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
            f"Получить предварительные материалы ({remaining_materials} осталось)",
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
    hw_id = context.user_data.get('awaiting_comment')
    approval_status = context.user_data.pop('approval_status', None)  # Получаем статус и удаляем из context.user_data

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
    await update.message.reply_text("Отправьте вашу домашнюю работу (фото или файл):")
    return HOMEWORK_RESPONSE  # Переходим в состояние ожидания ДЗ

async def save_homework(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    # Определяем тип курса
    cursor.execute('SELECT main_course, auxiliary_course FROM users WHERE user_id = ?', (user_id,))
    main_course, auxiliary_course = cursor.fetchone()
    course_type = 'main_course' if main_course else 'auxiliary_course'

    # Получаем текущий урок
    lesson_field = f"{course_type}_current_lesson"
    query = f'SELECT {lesson_field} FROM users WHERE user_id = ?'
    cursor.execute(query, (user_id,))
    current_lesson = cursor.fetchone()[0]

    # Сохраняем файл
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document:
        file_id = update.message.document.file_id
    else:
        await update.message.reply_text("Пожалуйста, отправьте фото или документ.")
        return

    cursor.execute('''
        INSERT INTO homeworks (user_id, course_type, lesson, file_id) 
        VALUES (?, ?, ?, ?)
    ''', (user_id, course_type, current_lesson, file_id))
    conn.commit()

def get_user_courses(user_id):
    cursor.execute('SELECT main_course, auxiliary_course FROM users WHERE user_id = ?', (user_id,))
    return cursor.fetchone()

def get_current_lesson(user_id, course_type):
    lesson_field = f"{course_type}_current_lesson"
    cursor.execute(f'SELECT {lesson_field} FROM users WHERE user_id = ?', (user_id,))
    return cursor.fetchone()[0]

async def handle_code_words(update: Update, context: CallbackContext):
    user = update.effective_user
    text = update.message.text.lower()

    if text in CODE_WORDS:
        course_type, course_name, tariff = CODE_WORDS[text]

        try:
            # Обновляем данные пользователя
            cursor.execute(f'''
                UPDATE users 
                SET {course_type} = ?, 
                    {course_type.split('_')[0]}_paid = 1 
                WHERE user_id = ?
            ''', (course_name, user.id))
            conn.commit()

            # Отправляем подтверждение
            await update.message.reply_text(
                f"🎉 Курс '{course_name}' успешно активирован!\n"
                f"Ваш тариф: {tariff.replace('_', ' ').title()}"
            )

            # Показываем главное меню
            await show_main_menu(update, context)

            # Отправляем первый урок
            await get_lesson_after_code(update, context, course_type)

            return ACTIVE  # Переходим в активное состояние

        except sqlite3.Error as e:
            logger.error(f"Ошибка активации курса: {e}")
            await update.message.reply_text("Ошибка активации курса. Попробуйте позже.")
            return WAIT_FOR_CODE
    else:
        await update.message.reply_text("❌ Неверное кодовое слово. Попробуйте еще раз.")
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
        if query:
            await query.edit_message_text("В галерее пока нет работ 😞\nХотите стать первым?")
        else:
            await update.message.reply_text("В галерее пока нет работ 😞\nХотите стать первым?")
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
    query = update.callback_query
    data = query.data
    await query.answer()  # Always answer callback queries

    if data == 'gallery':
        await show_gallery(update, context)
    elif data == 'gallery_next':
        await get_random_homework(update, context)
    elif data == 'menu_back':
        await show_main_menu(update, context)
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

# Добавляем новую функцию для обработки текстовых сообщений в состоянии ACTIVE
async def handle_active_state(update: Update, context: CallbackContext):
    user = update.effective_user
    text = update.message.text

    # Проверяем, является ли текст кодовым словом
    if text.lower() in CODE_WORDS:
        # Если это кодовое слово, обрабатываем его
        await handle_code_words(update, context)
    else:
        # Иначе просто игнорируем или показываем подсказку
        await update.message.reply_text(
            "Вы уже активировали курс. Используйте кнопки меню для продолжения."
        )

# Состояния для ConversationHandler
USER_INFO, = range(1)
HOMEWORK_RESPONSE, = range(1)

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    # Обработчик для регистрации пользователя
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            USER_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_info)],
            WAIT_FOR_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code_words)],
            ACTIVE: [
                CommandHandler("start", start),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_active_state),
                CallbackQueryHandler(button_handler)
            ]
        },
        fallbacks=[]
    )

    application.add_handler(conv_handler)

    # Добавляем обработчик для команды /start
    application.add_handler(CommandHandler("start", start))

    # Обработчик для текстовых сообщений (получение имени пользователя)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_info))

    # Добавляем обработчики для админ-кода и сохранения комментария
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^[a-zA-Z0-9]+$'), handle_admin_code))
    application.add_handler(MessageHandler(filters.TEXT, save_admin_comment))  # Сохранение комментария

    # Добавляем ConversationHandler для получения ДЗ
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^(Отправить ДЗ)$'), request_homework)],
        states={
            HOMEWORK_RESPONSE: [MessageHandler(filters.PHOTO, save_homework)]
        },
        fallbacks=[]
    )
    application.add_handler(conv_handler)

    # Добавляем обработчики для кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(CallbackQueryHandler(send_preliminary_material, pattern='^preliminary_'))

    # Обработчик для кодовых слов
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code_words))

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
