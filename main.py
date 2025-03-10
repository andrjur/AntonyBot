import secrets
import string
import logging
import feedparser
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext, \
    CallbackQueryHandler
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

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
TARGET_USER_ID = 954230772  # Ваш user_id
ADMIN_IDS = os.getenv("ADMIN_IDS").split(',')

CODE_WORDS = {
    "роза": ("main_course", "femininity", "no_check"),  # Без проверки д/з
    "фиалка": ("main_course", "femininity", "with_check"),  # С проверкой д/з
    "лепесток": ("main_course", "femininity", "premium"),  # Личное сопровождение
    "тыква": ("auxiliary_course", "autogenic", "no_check"),
    "слива": ("auxiliary_course", "autogenic", "with_check"),
    "молоко": ("auxiliary_course", "autogenic", "premium")
}

# Инициализация БД
conn = sqlite3.connect('bot_db.sqlite', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
try:
    cursor.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        full_name TEXT,
        main_course TEXT,
        auxiliary_course TEXT,
        main_paid BOOLEAN DEFAULT 0,
        auxiliary_paid BOOLEAN DEFAULT 0,
        main_current_lesson INTEGER DEFAULT 0,
        auxiliary_current_lesson INTEGER DEFAULT 0,
        main_homework_status TEXT DEFAULT 'none',
        auxiliary_homework_status TEXT DEFAULT 'none',
        main_last_homework_time DATETIME,
        auxiliary_last_homework_time DATETIME,
        penalty_task TEXT,
        main_last_message_id INTEGER,
        auxiliary_last_message_id INTEGER
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
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    );

    CREATE TABLE IF NOT EXISTS admins (
        admin_id INTEGER PRIMARY KEY,
        level INTEGER DEFAULT 1
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


def generate_admin_code(length=16):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for i in range(length))

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


async def handle_code_words(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    text = update.message.text.lower()

    for code, details in CODE_WORDS.items():
        if code in text:
            course_type, course, tariff_type = details
            tariff_field = f"{course_type.split('_')[0]}_paid"
            cursor.execute(f'UPDATE users SET {course_type} = ?, {tariff_field} = 1 WHERE user_id = ?',
                           (course, user_id))
            conn.commit()
            await update.message.reply_text(
                f"Кодовое слово '{code}' активировано. Вам назначен курс '{course}' ({course_type})")

            # После активации кодового слова сразу выдаем первый урок
            if course_type == 'main_course':
                context.args = ['main']
            elif course_type == 'auxiliary_course':
                context.args = ['auxiliary']

            # Получаем первый урок
            await get_lesson_after_code(update, context, course_type)

            return

    await update.message.reply_text("Неверное кодовое слово.")


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
        # Проверяем, есть ли незавершенное ДЗ по основному курсу
        cursor.execute(
            'SELECT hw_id FROM homeworks WHERE user_id = ? AND course_type = ? AND status = ? ORDER BY timestamp DESC LIMIT 1',
            (user_id, 'main_course', 'pending'))
        pending_hw = cursor.fetchone()

        if pending_hw:
            await update.message.reply_text("У вас есть незавершенное домашнее задание. Отправьте фото для проверки:")
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
        keyboard = [
            [InlineKeyboardButton("💰 Выбрать тариф", callback_data='tariffs'),
             InlineKeyboardButton("📸 Отправить ДЗ", callback_data='send_hw')],
            [InlineKeyboardButton("📚 Получить урок", callback_data='get_lesson_main'),
             InlineKeyboardButton("👥 Галерея работ", callback_data='gallery')],
            [InlineKeyboardButton("🆘 Поддержка", callback_data='support'),
            InlineKeyboardButton("Случайный анекдот", callback_data='random_joke')]
        ]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return True


    # Аналогично для вспомогательного курса
    if auxiliary_course:
        # Проверяем, есть ли незавершенное ДЗ по вспомогательному курсу
        cursor.execute(
            'SELECT hw_id FROM homeworks WHERE user_id = ? AND course_type = ? AND status = ? ORDER BY timestamp DESC LIMIT 1',
            (user_id, 'auxiliary_course', 'pending'))
        pending_hw = cursor.fetchone()

        if pending_hw:
            await update.message.reply_text("У вас есть незавершенное домашнее задание. Отправьте фото для проверки:")
            return True

        # Если нет незавершенного ДЗ, предлагаем получить следующий урок
        keyboard = [[InlineKeyboardButton("Получить следующий урок (вспомогательный курс)",
                                          callback_data='get_lesson_auxiliary')]]
        await update.message.reply_text("Готовы к следующему уроку по вспомогательному курсу?",
                                         reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    return False  # Нечего продолжать


async def get_lesson(update: Update, context: CallbackContext):
    user = update.effective_user

    if update.callback_query:
        query = update.callback_query
        course_type = query.data.split('_')[2]
    else:
        # Если команда /start
        course_type = 'main_course'  # или 'auxiliary_course', в зависимости от логики


    await send_lesson(update, context, user, course_type)


async def get_lesson_after_code(update: Update, context: CallbackContext, course_type):
    user = update.effective_user

    # Посылаем урок
    await send_lesson(update, context, user, course_type)

async def send_lesson(update: Update, context: CallbackContext, user: Update.effective_user, course_type: str):
    # Определение типа курса и полей в таблице users
    if course_type == 'main_course':
        course_field = 'main_course'
        lesson_field = 'main_current_lesson'
        last_message_field = 'main_last_message_id'  # Поле для хранения message_id
    elif course_type == 'auxiliary_course':
        course_field = 'auxiliary_course'
        lesson_field = 'auxiliary_current_lesson'
        last_message_field = 'auxiliary_last_message_id'
    else:
        await context.bot.send_message(chat_id=user.id, text="Ошибка: Неверный тип курса.")
        return

    # Получение текущего урока и названия курса
    cursor.execute(f'SELECT {lesson_field}, {course_field}, {last_message_field} FROM users WHERE user_id = ?',
                   (user.id,))
    result = cursor.fetchone()
    if not result:
        await update.message.reply_text("Ошибка: Курс не найден.")
        return

    current_lesson, course, last_message_id = result

    # Проверка времени на выполнение предыдущего задания
    cursor.execute('SELECT MAX(timestamp) FROM homeworks WHERE user_id = ? AND course_type = ?',
                   (user.id, course_type))
    last_homework_time = cursor.fetchone()[0]
    if last_homework_time:
        last_homework_time = datetime.fromisoformat(last_homework_time)
        deadline = last_homework_time + timedelta(hours=72)
        if datetime.now() > deadline:
            # Курс завершен из-за просрочки
            await update.message.reply_text(
                "Время на выполнение предыдущего задания истекло. Курс завершен. Обратитесь к администратору для получения штрафного задания.")
            return

    next_lesson = current_lesson + 1
    lesson_text = get_lesson_text(user.id, next_lesson, course_type)

    if lesson_text:
        # Отправка картинки "пройдено" на место предыдущего задания
        if last_message_id:
            try:
                await context.bot.edit_message_media(
                    chat_id=user.id,
                    message_id=last_message_id,
                    media=InputMediaPhoto(media=open('passed.png', 'rb'))  # Замените 'passed.png' на путь к вашей картинке
                )
            except Exception as e:
                logger.error(f"Ошибка при редактировании сообщения: {e}")

        # Отправка нового урока
        average_time = get_average_homework_time(user.id)
        text = f"{lesson_text}\n\nСтатистика: Вы сдаете ДЗ в среднем за {average_time}."
        message = await context.bot.send_message(chat_id=user.id, text=text)

        # Сохранение message_id для следующего урока
        cursor.execute(f'UPDATE users SET {lesson_field} = ?, {last_message_field} = ? WHERE user_id = ?', (next_lesson, message.message_id, user.id))
        conn.commit()

    else:
        await update.message.reply_text("Урок не найден!")



async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    cursor.execute('INSERT OR IGNORE INTO users (user_id, full_name) VALUES (?, ?)',
                   (user.id, user.full_name))
    conn.commit()

    # Проверяем, нужно ли предлагать выбор курса или продолжить
    if not await continue_course(update, context):
        keyboard = [
            [InlineKeyboardButton("Основной курс - Женственность", callback_data='main_course_femininity')],
            [InlineKeyboardButton("Основной курс - Аутогенная тренировка", callback_data='main_course_autogenic')],
            [InlineKeyboardButton("Вспомогательный курс - Женственность", callback_data='auxiliary_course_femininity')],
            [InlineKeyboardButton("Вспомогательный курс - Аутогенная тренировка",
                                  callback_data='auxiliary_course_autogenic')],
        ]
        await update.message.reply_text("Здравствуйте! Выберите основной и вспомогательный курсы:",
                                         reply_markup=InlineKeyboardMarkup(keyboard))


async def course_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id
    course_type, course = query.data.split('_')[0], query.data.split('_')[1]

    cursor.execute(f'UPDATE users SET {course_type}_course = ? WHERE user_id = ?', (course, user_id))
    conn.commit()

    await query.message.reply_text(f"Вы выбрали {course_type} курс: {course}")


async def handle_homework(update: Update, context: CallbackContext):
    user = update.effective_user
    photo = update.message.photo[-1]
    course_type = 'main_course'  # Предполагаем, что ДЗ по основному курсу

    # Определяем course_type на основе активных курсов пользователя
    cursor.execute('SELECT main_course, auxiliary_course FROM users WHERE user_id = ?', (user.id,))
    main_course, auxiliary_course = cursor.fetchone()

    if not main_course and auxiliary_course:
        course_type = 'auxiliary_course'

    # Сохраняем file_id в БД
    lesson_field = 'main_current_lesson' if course_type == 'main_course' else 'auxiliary_current_lesson'
    cursor.execute(f'SELECT {lesson_field} FROM users WHERE user_id = ?', (user.id,))
    lesson = cursor.fetchone()[0]

    cursor.execute('''
        INSERT INTO homeworks (user_id, lesson, course_type, file_id, submission_time)
        VALUES (?, ?, ?, ?, ?)
        ''', (user.id, lesson, course_type, photo.file_id, datetime.now()))
    conn.commit()
    hw_id = cursor.lastrowid

    # Получаем message_id сообщения с фото
    message_id = update.message.message_id

    # Обновляем homeworks с message_id
    cursor.execute('UPDATE homeworks SET message_id = ? WHERE hw_id = ?', (message_id, hw_id))
    conn.commit()

    # Уведомление админов
    await context.bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=f"📸 Новое ДЗ от {user.full_name}\nУрок: {lesson} ({course_type})\n",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔍 Проверить", callback_data=f"review_{user.id}_{hw_id}")]])
    )

    await update.message.reply_text("📌 Ваше ДЗ сохранено и отправлено на проверку!")


async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data

    if data == 'tariffs':
        await show_tariffs(update, context)
    elif data == 'send_hw':
        await request_homework(update, context)
    elif data == 'get_lesson_main':
        await get_lesson(update, context)
    elif data == 'get_lesson_auxiliary':
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
    elif data == 'random_joke':
        await random_joke(update, context)
    elif data.startswith('review'):
        await show_homework(update, context)


async def handle_admin_approval(update: Update, context: CallbackContext):
    query = update.callback_query
    data_parts = query.data.split('_')
    user_id = int(data_parts[2])
    hw_id = int(data_parts[3])

    # Получаем информацию о домашней работе
    cursor.execute('SELECT course_type FROM homeworks WHERE hw_id = ?', (hw_id,))
    course_type = cursor.fetchone()[0]

    # Определяем поля для обновления в таблице users
    if course_type == 'main_course':
        lesson_field = 'main_current_lesson'
        homework_status_field = 'main_homework_status'
    else:
        lesson_field = 'auxiliary_current_lesson'
        homework_status_field = 'auxiliary_homework_status'

    # Обновляем статус ДЗ и увеличиваем номер урока
    cursor.execute(f'''
        UPDATE users 
        SET {homework_status_field} = 'approved', {lesson_field} = {lesson_field} + 1
        WHERE user_id = ?
    ''', (user_id,))
    conn.commit()

    # Обновляем статус ДЗ в таблице homeworks
    cursor.execute('UPDATE homeworks SET status = "approved", approval_time = ? WHERE hw_id = ?', (datetime.now(), hw_id,))
    conn.commit()

    await query.edit_message_caption(caption="✅ ДЗ одобрено!")

    # Формируем кнопки
    keyboard = [
        [InlineKeyboardButton("💰 Выбрать тариф", callback_data='tariffs'),
         InlineKeyboardButton("📸 Отправить ДЗ", callback_data='send_hw')],
        [InlineKeyboardButton("📚 Получить урок", callback_data='get_lesson_main'),
         InlineKeyboardButton("👥 Галерея работ", callback_data='gallery')],
        [InlineKeyboardButton("🆘 Поддержка", callback_data='support'),
         InlineKeyboardButton("👨‍💻 Админ-меню", callback_data='admin_menu')],
        [InlineKeyboardButton("Случайный анекдот", callback_data='random_joke')]
    ]
    await context.bot.send_message(
        chat_id=user_id,
        text="🎉 Спасибо, домашнее задание принято!",
    )

    # Автоматически показываем галерею работ по этому уроку
    await show_gallery_for_lesson(update, context)

async def show_gallery_for_lesson(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    # Получаем текущий урок
    cursor.execute('SELECT main_current_lesson FROM users WHERE user_id = ?', (user_id,))
    current_lesson = cursor.fetchone()[0]

    # Получаем работы по текущему уроку
    cursor.execute("SELECT hw_id, file_id FROM homeworks WHERE status = 'approved' AND lesson = ?", (current_lesson,))
    homeworks = cursor.fetchall()

    if not homeworks:
        await update.callback_query.message.reply_text("В галерее пока нет работ для этого урока.")
        return

    keyboard = []
    row = []
    for hw_id, file_id in homeworks:
        row.append(InlineKeyboardButton(f"Работа {hw_id}", callback_data=f"gallery_image_{hw_id}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await context.bot.send_message(
        chat_id=user_id,
        text="Выберите работу:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_admin_rejection(update: Update, context: CallbackContext):
    query = update.callback_query
    data_parts = query.data.split('_')
    user_id = int(data_parts[2])
    hw_id = int(data_parts[3])

    # Получаем информацию о домашней работе
    cursor.execute('SELECT course_type FROM homeworks WHERE hw_id = ?', (hw_id,))
    course_type = cursor.fetchone()[0]

    # Определяем поле для обновления статуса ДЗ в таблице users
    if course_type == 'main_course':
        homework_status_field = 'main_homework_status'
    else:
        homework_status_field = 'auxiliary_homework_status'

    cursor.execute(f"UPDATE users SET {homework_status_field} = 'rejected' WHERE user_id = ?", (user_id,))
    conn.commit()

    # Обновляем статус ДЗ в таблице homeworks
    cursor.execute('UPDATE homeworks SET status = "rejected" WHERE hw_id = ?', (hw_id,))
    conn.commit()

    await query.edit_message_caption(caption="❌ ДЗ отклонено. Ожидайте обратной связи.")
    await context.bot.send_message(user_id, "📛 Ваше ДЗ требует доработки. Ожидайте комментариев от куратора.")


async def show_homework(update: Update, context: CallbackContext):
    query = update.callback_query
    data_parts = query.data.split('_')
    user_id = int(data_parts[1])
    hw_id = int(data_parts[2])

    cursor.execute('SELECT file_id FROM homeworks WHERE hw_id = ?', (hw_id,))
    file_id = cursor.fetchone()[0]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Принять", callback_data=f'admin_approve_{user_id}_{hw_id}'),
         InlineKeyboardButton("❌ Отклонить", callback_data=f'admin_reject_{user_id}_{hw_id}')]
    ])

    try:
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=file_id,
            caption=f"Домашняя работа пользователя {user_id}",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        await query.message.reply_text("Не удалось отобразить работу.")


async def show_tariffs(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("💰 Без проверки ДЗ", callback_data='tariff_no_check')],
        [InlineKeyboardButton("📚 С проверкой ДЗ", callback_data='tariff_with_check')],
        [InlineKeyboardButton("🌟 Премиум (личный куратор)", callback_data='tariff_premium')]
    ]
    await update.callback_query.message.reply_text("Выберите тариф:", reply_markup=InlineKeyboardMarkup(keyboard))


async def request_homework(update: Update, context: CallbackContext):
    await update.callback_query.message.reply_text("Отправьте фото вашего домашнего задания:")


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


async def show_gallery(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    cursor.execute("SELECT hw_id, file_id FROM homeworks WHERE status = 'approved'")  # Only approved homeworks
    homeworks = cursor.fetchall()

    if not homeworks:
        await update.callback_query.message.reply_text("В галерее пока нет работ.")
        return

    keyboard = []
    row = []
    for hw_id, file_id in homeworks:
        row.append(InlineKeyboardButton(f"Работа {hw_id}", callback_data=f"gallery_image_{hw_id}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.callback_query.message.reply_text("Выберите работу:", reply_markup=InlineKeyboardMarkup(keyboard))


async def display_gallery_image(update: Update, context: CallbackContext):
    query = update.callback_query
    hw_id = int(query.data.split('_')[2])

    cursor.execute("SELECT file_id, user_id, lesson FROM homeworks WHERE hw_id = ?", (hw_id,))
    result = cursor.fetchone()

    if result:
        file_id, user_id, lesson = result
        try:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=file_id,
                caption=f"Работа пользователя {user_id}, урок {lesson}"
            )
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            await query.message.reply_text("Не удалось отобразить работу.")
    else:
        await query.message.reply_text("Работа не найдена.")


async def random_joke(update: Update, context: CallbackContext):
    rss_urls = [
        "https://www.anekdot.ru/rss/random.rss",
        "https://anekdotov-mnogo.ru/anekdoty_rss.xml",
        "http://www.anekdot.ru/rss/anekdot.rss",
        "http://www.anekdot.ru/rss/besty.rss",
        "http://www.umori.li/api/rss/56d9c03b61c4046c5e99a6b1"
    ]

    jokes = []  # Список для хранения анекдотов

    if update.callback_query:
        query = update.callback_query
        for i in range(2):  # Пытаемся получить два анекдота
            try:
                rss_url = random.choice(rss_urls)
                feed = feedparser.parse(rss_url)
                if feed.entries:
                    random_entry = random.choice(feed.entries)
                    joke = random_entry.title + "\n\n" + random_entry.description
                    jokes.append(joke)
            except Exception as e:
                logger.error(f"Ошибка при получении анекдота: {e}")

        if jokes:
            for joke in jokes:
                await query.message.reply_text(joke)  # Отправляем каждый анекдот отдельно
        else:
            await query.message.reply_text("Не удалось получить анекдоты.")
    else:
        for i in range(2):  # Пытаемся получить два анекдота
            try:
                rss_url = random.choice(rss_urls)
                feed = feedparser.parse(rss_url)
                if feed.entries:
                    random_entry = random.choice(feed.entries)
                    joke = random_entry.title + "\n\n" + random_entry.description
                    jokes.append(joke)
            except Exception as e:
                logger.error(f"Ошибка при получении анекдота: {e}")

        if jokes:
            for joke in jokes:
                await update.message.reply_text(joke)  # Отправляем каждый анекдот отдельно
        else:
            await update.message.reply_text("Не удалось получить анекдоты.")




async def request_support(update: Update, context: CallbackContext):
    await update.callback_query.message.reply_text("Запрос в поддержку отправлен. Ожидайте ответа.")


async def show_admin_menu(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    cursor.execute('SELECT admin_id FROM admins WHERE admin_id = ?', (user_id,))
    admin = cursor.fetchone()

    if admin:
        keyboard = [
            [InlineKeyboardButton("✅ Одобрить оплату", callback_data='admin_approve_payment')],
            [InlineKeyboardButton("➕ Добавить админа", callback_data='admin_add'),
             InlineKeyboardButton("➖ Удалить админа", callback_data='admin_remove')],
        ]
        await update.callback_query.message.reply_text("Админ-меню:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.message.reply_text("У вас нет прав для просмотра админ-меню.")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Регистрация обработчиков
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code_words))
    app.add_handler(CallbackQueryHandler(course_selection, pattern='^.+_course_.*'))  # Все виды выбора курса
    app.add_handler(MessageHandler(filters.PHOTO, handle_homework))
    app.add_handler(CallbackQueryHandler(button_handler, pattern='^((?!course).)*$'))  # Все остальные кнопки
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_code))

    app.run_polling()


if __name__ == '__main__':
    main()
