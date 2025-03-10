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
        preliminary_material_index INTEGER DEFAULT 0
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

# Функция для получения предварительных материалов
def get_preliminary_materials(course, next_lesson):
    """
    Возвращает список всех предварительных материалов для следующего урока.
    """
    lesson_dir = f'courses/{course}/'
    materials = [
        f for f in os.listdir(lesson_dir)
        if f.startswith(f'lesson{next_lesson}_p') and os.path.isfile(os.path.join(lesson_dir, f))
    ]
    materials.sort()  # Сортируем по порядку (p1, p2, ...)
    return materials

# Обработчик кнопки "Получить предварительные материалы"
async def send_preliminary_material(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    course_type = query.data.split('_')[1]  # Получаем тип курса из callback_data

    # Проверяем, какой урок следующий
    cursor.execute(f'SELECT {course_type}_current_lesson FROM users WHERE user_id = ?', (user_id,))
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
    material_path = f'courses/{course}/{material_file}'

    # Определяем тип файла
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
        [InlineKeyboardButton(f"Получить предварительные материалы ({remaining_materials} осталось)",
                              callback_data=f'preliminary_{course_type}')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if remaining_materials > 0:
        await query.edit_message_text("Материал отправлен. Хотите получить ещё?", reply_markup=reply_markup)
    else:
        await query.edit_message_text("Вы получили все предварительные материалы для следующего урока.")

# Функция для добавления кнопки "Получить предварительные материалы"
def add_preliminary_button(user_id, course_type):
    cursor.execute(f'SELECT {course_type}_current_lesson FROM users WHERE user_id = ?', (user_id,))
    current_lesson = cursor.fetchone()[0]
    next_lesson = current_lesson + 1

    cursor.execute(f'SELECT {course_type}_course FROM users WHERE user_id = ?', (user_id,))
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

        # Добавляем кнопку "Запросить урок немедленно" для VIP-пользователей
        if is_vip:
            keyboard.append([InlineKeyboardButton("🚀 Запросить урок немедленно", callback_data='get_lesson_now')])
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

async def send_status_message(user_id, context):
    # Получаем данные пользователя
    cursor.execute('''
        SELECT main_homework_status, auxiliary_homework_status, 
               main_current_lesson, auxiliary_current_lesson
        FROM users WHERE user_id = ?
    ''', (user_id,))
    hw_status_main, hw_status_aux, main_lesson, aux_lesson = cursor.fetchone()

    # Формируем текст и клавиатуру
    text = ""
    keyboard = []

    # Проверяем основной курс
    if hw_status_main == 'pending':
        text = "⏳ Ожидаю домашнее задание"
        keyboard = [[InlineKeyboardButton("📸 Отправить ДЗ", callback_data='send_hw')]]
    elif hw_status_main in ['approved', 'none']:
        next_time = datetime.now() + timedelta(days=1)
        text = f"✅ Задание выполнено! Следующий урок - завтра в {next_time.strftime('%H:%M')}"
        keyboard = [[InlineKeyboardButton("🚀 Получить следующий урок", callback_data='get_lesson_main')]]

    # Добавляем общие кнопки
    keyboard += [
        [InlineKeyboardButton("📚 Материалы", callback_data='materials')],
        [InlineKeyboardButton("📊 Статистика", callback_data='stats')]
    ]

    # Отправляем сообщение
    await context.bot.send_message(
        chat_id=user_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def get_lesson_now(update: Update, context: CallbackContext):
    user = update.effective_user
    # Получаем урок немедленно
    await get_lesson(update, context)

async def get_lesson(update: Update, context: CallbackContext):
    user = update.effective_user
    if update.callback_query:
        query = update.callback_query
        course_type = query.data.split('_')[2]
    else:
        # Если команда /start
        course_type = 'main_course'  # или 'auxiliary_course', в зависимости от логики

    # Определение типа курса и полей в таблице users
    if course_type == 'main_course':
        lesson_field = 'main_current_lesson'
        last_message_field = 'main_last_message_id'
    elif course_type == 'auxiliary_course':
        lesson_field = 'auxiliary_current_lesson'
        last_message_field = 'auxiliary_last_message_id'
    else:
        await context.bot.send_message(chat_id=user.id, text="Ошибка: Неверный тип курса.")
        return

    cursor.execute(f'SELECT {lesson_field}, main_paid, auxiliary_paid FROM users WHERE user_id = ?', (user.id,))
    current_lesson, main_paid, auxiliary_paid = cursor.fetchone()

    if current_lesson is None:
        current_lesson = 0

    next_lesson = current_lesson + 1

    # Проверяем, является ли пользователь премиум-пользователем
    is_premium = False
    if course_type == 'main_course' and main_paid == 3:
        is_premium = True
    elif course_type == 'auxiliary_course' and auxiliary_paid == 3:
        is_premium = True

    # Логика ожидания урока
    if not is_premium:
        cursor.execute(
            'SELECT timestamp FROM homeworks WHERE user_id = ? AND course_type = ? ORDER BY timestamp DESC LIMIT 1',
            (user.id, course_type))
        last_homework_time = cursor.fetchone()
        if last_homework_time:
            last_homework_time = datetime.fromisoformat(last_homework_time[0])
            deadline = last_homework_time + timedelta(hours=72)
            if datetime.now() < deadline:
                time_left = deadline - datetime.now()
                hours_left = int(time_left.total_seconds() / 3600)
                await query.edit_message_text(
                    text=f"Урок будет доступен через {hours_left} часов. Для немедленного доступа к урокам подпишитесь на премиум-тариф.")
                return

    # Проверка количества попыток запроса урока
    cursor.execute('SELECT request_count FROM users WHERE user_id = ?', (user.id,))
    request_count = cursor.fetchone()[0] if cursor.fetchone() else 0

    if request_count >= 5:
        await send_lesson(update, context, user, course_type, next_lesson)
        cursor.execute('UPDATE users SET request_count = 0 WHERE user_id = ?', (user.id,))
        conn.commit()
    else:
        cursor.execute('UPDATE users SET request_count = ? WHERE user_id = ?', (request_count + 1, user.id))
        conn.commit()
        if is_premium:
            await send_lesson(update, context, user, course_type, next_lesson)
        else:
            await query.edit_message_text(
                text="Урок будет доступен только завтра. Для немедленного доступа к урокам подпишитесь на премиум-тариф.")

async def send_lesson(update: Update, context: CallbackContext, user: Update.effective_user, course_type: str,
                      lesson_number: int):
    if lesson_number is None:
        logger.error("Lesson number is not provided")
        await context.bot.send_message(chat_id=user.id, text="Ошибка: Номер урока не определен.")
        return

    logger.info(
        f"send_lesson вызвана с параметрами: user={user}, course_type={course_type}, lesson_number={lesson_number}")

    # Определение типа курса и полей в таблице users
    if course_type == 'main_course':
        course_field = 'main_course'
        lesson_field = 'main_current_lesson'
        last_message_field = 'main_last_message_id'
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
        logger.warning(f"Ошибка: Курс не найден.: {result}")  # Логгируем,
        await update.message.reply_text("Ошибка: Курс не найден.")
        return
    current_lesson, course, last_message_id = result
    logger.debug(f"Данные из БД: current_lesson={current_lesson}, course={course}, last_message_id={last_message_id}")

    # Проверка времени на выполнение предыдущего задания
    cursor.execute('SELECT MAX(timestamp) FROM homeworks WHERE user_id = ? AND course_type = ?', (user.id, course_type))
    last_homework_time = cursor.fetchone()[0]
    if last_homework_time:
        last_homework_time = datetime.fromisoformat(last_homework_time)
        deadline = last_homework_time + timedelta(hours=72)
        if datetime.now() > deadline:
            # Курс завершен из-за просрочки
            await update.message.reply_text(
                "Время на выполнение предыдущего задания истекло. Курс завершен. Обратитесь к администратору для получения штрафного задания.")
            return

    lesson_text = get_lesson_text(user.id, lesson_number, course_type)
    if lesson_text:
        # Отправка картинки "пройдено" на место предыдущего задания
        if last_message_id:
            try:
                await context.bot.edit_message_media(
                    chat_id=user.id,
                    message_id=last_message_id,
                    media=InputMediaPhoto(media=open('passed.png', 'rb'))
                    # Замените 'passed.png' на путь к вашей картинке
                )
            except Exception as e:
                logger.error(f"Ошибка при редактировании сообщения: {e}")
            # Отправка нового урока
            average_time = get_average_homework_time(user.id)
            lesson_content = f"{lesson_text}\nСтатистика: Вы сдаете ДЗ в среднем за {average_time}."
            # Все файлы для урока (текст уже отправлен, поэтому исключаем его)
            lesson_dir = f'courses/{course}/'
            files = [f for f in os.listdir(lesson_dir) if
                     os.path.isfile(os.path.join(lesson_dir, f)) and f.startswith(f'lesson{lesson_number}')]
            files.sort()  # Важно сортировать, чтобы порядок был корректный
            media = []  # Список для хранения медиафайлов (для группировки)
            text_sent = False  # Флаг для отслеживания отправки текста
            for file in files:
                file_path = os.path.join(lesson_dir, file)
                try:
                    if file.endswith('.txt') and not text_sent:
                        # отправляем текст первым, НЕ один раз -- исправить и разрешить повторы
                        logger.info(f"Отправка текста для урока {lesson_number} пользователю {user.id}")
                        message = await context.bot.send_message(chat_id=user.id, text=lesson_content)
                        # Сохранение message_id для следующего урока
                        cursor.execute(
                            f'UPDATE users SET {lesson_field} = ?, {last_message_field} = ? WHERE user_id = ?',
                            (lesson_number, message.message_id, user.id))
                        conn.commit()
                        text_sent = True
                    elif file.endswith(('.jpg', '.jpeg', '.png')):
                        logger.info(f"Отправка фотографии {file} для урока {lesson_number} пользователю {user.id}")
                        with open(file_path, 'rb') as photo:
                            await context.bot.send_photo(chat_id=user.id, photo=photo)
                    elif file.endswith('.mp3'):
                        with open(file_path, 'rb') as audio:
                            await context.bot.send_audio(chat_id=user.id, audio=audio)
                    elif file.endswith(('.mp4', '.mov')):
                        with open(file_path, 'rb') as video:
                            await context.bot.send_video(chat_id=user.id, video=video)
                    logger.info(f"Отправлен файл {file} пользователю {user.id}")  # Добавляем логирование
                except Exception as e:
                    logger.exception(f'Error sending media {file}')
                    await context.bot.send_message(
                        chat_id=user.id,
                        text=f'Error sending {file}: {e}')
            # Отправляем оставшиеся файлы из media
            if media:
                await context.bot.send_media_group(chat_id=user.id, media=media)
        else:
            await update.message.reply_text("Урок не найден!")
        await send_status_message(user.id, context)

async def get_lesson_after_code(update: Update, context: CallbackContext, course_type):
    user = update.effective_user

    # Посылаем урок
    await send_lesson(update, context, user, course_type, lesson_number=1)  # Первый урок

async def show_main_menu(update: Update, context: CallbackContext):
    user = update.effective_user
    cursor.execute('SELECT main_course, auxiliary_course FROM users WHERE user_id = ?', (user.id,))
    main_course, auxiliary_course = cursor.fetchone()

    keyboard = [
        [InlineKeyboardButton("🚀 Получить следующий урок (основной курс)", callback_data='get_lesson_main')],
        [InlineKeyboardButton("📸 Отправить ДЗ (основной курс)", callback_data='send_hw_main')],
    ]

    # Проверяем наличие вспомогательного курса
    if auxiliary_course:
        keyboard.append(
            [InlineKeyboardButton("🚀 Получить следующий урок (вспомогательный курс)", callback_data='get_lesson_auxiliary')]
        )
        keyboard.append(
            [InlineKeyboardButton("📸 Отправить ДЗ (вспомогательный курс)", callback_data='send_hw_auxiliary')]
        )

        # Добавляем кнопки для доступа к прошлым урокам (максимум 9 уроков)
        aux_lessons_buttons = [InlineKeyboardButton(f"{i} 🔍", callback_data=f'view_lesson_aux_{i}') for i in range(1, 10)]
        keyboard.append(aux_lessons_buttons)

    # Общие кнопки
    keyboard += [
        [InlineKeyboardButton("📚 Материалы", callback_data='materials')],
        [InlineKeyboardButton("📊 Статистика", callback_data='stats')],
        [InlineKeyboardButton("🆘 Поддержка", callback_data='support')],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Главное меню:", reply_markup=reply_markup)

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
        await update.message.reply_text("Здравствуйте! ВВЕДИТЕ КОДОВОЕ СЛОВО или \n Выберите основной и вспомогательный курсы:",
                                         reply_markup=InlineKeyboardMarkup(keyboard))

async def course_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    print('course_selection')
    await query.answer()

    user_id = update.effective_user.id
    course_type, course = query.data.split('_')[0], query.data.split('_')[1]

    # Обновляем данные пользователя в базе данных
    cursor.execute(f'UPDATE users SET {course_type}_course = ? WHERE user_id = ?', (course, user_id))
    conn.commit()

    # Отправляем сообщение о выборе курса
    await query.message.reply_text(f"Вы выбрали {course_type} курс: {course}")

    # Переходим к выбору тарифа
    await choose_tariff(update, context, course_type, course)

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
    print('button_handler')
    await query.answer()  # Always answer callback queries
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
    elif data == 'get_lesson_now':
        await get_lesson_now(update, context)
    elif data.startswith('review'):
        await show_homework(update, context)
    elif data.startswith('repeat_lesson_'):
        lesson_number = int(data.split('_')[2])
        user_id = update.effective_user.id
        cursor.execute('SELECT main_course, auxiliary_course FROM users WHERE user_id = ?', (user_id,))
        main_course, auxiliary_course = cursor.fetchone()
        course_type = 'main_course' if main_course else 'auxiliary_course'
        await send_lesson(update, context, update.effective_user, course_type, lesson_number=lesson_number)
    elif data.startswith('tariff_'):  # Обработка выбора тарифа
        await handle_tariff_selection(update, context)

async def handle_admin_approval(update: Update, context: CallbackContext):
    query = update.callback_query
    data_parts = query.data.split('_')
    user_id = int(data_parts[2])
    hw_id = int(data_parts[3])

    # Получаем информацию о домашней работе
    cursor.execute('SELECT course_type, lesson FROM homeworks WHERE hw_id = ?', (hw_id,))
    result = cursor.fetchone()
    if not result:
        await query.message.reply_text("Ошибка: Домашнее задание не найдено.")
        return

    course_type, current_lesson = result

    # Определяем поля для обновления в таблице users
    if course_type == 'main_course':
        lesson_field = 'main_current_lesson'
        homework_status_field = 'main_homework_status'
    else:
        lesson_field = 'auxiliary_current_lesson'
        homework_status_field = 'auxiliary_homework_status'

    try:
        # Обновляем статус ДЗ и увеличиваем номер урока
        cursor.execute(f'''
            UPDATE users 
            SET {homework_status_field} = 'approved', {lesson_field} = ?
            WHERE user_id = ?
        ''', (current_lesson + 1, user_id))
        conn.commit()

        # Обновляем статус ДЗ в таблице homeworks
        cursor.execute('''
            UPDATE homeworks 
            SET status = "approved", approval_time = ? 
            WHERE hw_id = ?
        ''', (datetime.now(), hw_id))
        conn.commit()

        # Редактируем сообщение с ДЗ
        await query.edit_message_caption(caption="✅ ДЗ одобрено!")

        # Отправляем уведомление пользователю
        keyboard = [
            [InlineKeyboardButton("💰 Повысить тариф", callback_data='tariffs'),
             InlineKeyboardButton("📸 Отправить ДЗ", callback_data='send_hw')],
            [InlineKeyboardButton("📚 Получить урок", callback_data=f'get_lesson_{course_type.split("_")[0]}'),
             InlineKeyboardButton("👥 Галерея работ", callback_data='gallery')],
            [InlineKeyboardButton("🆘 Поддержка", callback_data='support'),
             InlineKeyboardButton("Случайный анекдот", callback_data='random_joke')]
        ]

        await context.bot.send_message(
            chat_id=user_id,
            text="🎉 Спасибо, домашнее задание принято! "
                 f"Текущий урок: {current_lesson + 1}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # Автоматически показываем галерею работ по этому уроку
        await show_gallery_for_lesson(update, context)

        # Отправляем статусное сообщение
        await send_status_message(user_id, context)

    except Exception as e:
        logger.error(f"Ошибка при обработке одобрения ДЗ: {e}")
        await query.message.reply_text("Произошла ошибка при обработке одобрения.")

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
        [InlineKeyboardButton("💰 Без проверки ДЗ - 3000 р.", callback_data='tariff_роза')],
        [InlineKeyboardButton("📚 С проверкой ДЗ - 5000 р.", callback_data='tariff_фиалка')],
        [InlineKeyboardButton("🌟 Премиум (личный куратор) - 12000 р.", callback_data='tariff_лепесток')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.reply_text("Выберите тариф:", reply_markup=reply_markup)

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

#========================================================
# Функция для выбора тарифа
async def choose_tariff(update: Update, context: CallbackContext, course_type: str, course: str):
    query = update.callback_query
    print('choose_tariff')
    await query.answer()

    # Создаем кнопки для выбора тарифа
    keyboard = [
        [InlineKeyboardButton("Без проверки д/з - 3000 р.", callback_data=f'tariff_{course_type}_роза')],
        [InlineKeyboardButton("С проверкой д/з - 5000 р.", callback_data=f'tariff_{course_type}_фиалка')],
        [InlineKeyboardButton("Личное сопровождение - 12000 р.", callback_data=f'tariff_{course_type}_лепесток')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем сообщение с выбором тарифа
    await query.message.reply_text(
        f"Выберите тариф для курса '{course}':",
        reply_markup=reply_markup
    )
#===========================================================

async def handle_tariff_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    print('handle_tariff_selection:', query.data)  # Отладочный вывод

    user_id = update.effective_user.id

    try:
        # Разбиваем callback_data на части
        parts = query.data.split('_')
        if len(parts) != 3:
            await query.message.reply_text("Ошибка: Некорректный формат данных.")
            return

        _, course_type, tariff_code = parts
        print(f"Extracted parts: course_type={course_type}, tariff_code={tariff_code}")

        # Проверяем, существует ли tariff_code в CODE_WORDS
        if tariff_code not in CODE_WORDS:
            await query.message.reply_text(f"Неверный выбор тарифа. Получен tariff_code: {tariff_code}")
            return

        # Получаем данные из CODE_WORDS
        course_type_full, course, tariff_type = CODE_WORDS[tariff_code]
        tariff_field = f"{course_type_full.split('_')[0]}_paid"  # Например, main_paid или auxiliary_paid

        # Обновляем данные пользователя в базе данных
        cursor.execute(f'''
            UPDATE users 
            SET {course_type_full} = ?, {tariff_field} = 'pending' 
            WHERE user_id = ?
        ''', (course, user_id))
        conn.commit()

        # Отправляем инструкции по оплате
        keyboard = [
            [InlineKeyboardButton("Оплачено", callback_data=f'payment_done_{course_type}_{tariff_code}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.reply_text(
            f"Для оплаты тарифа '{tariff_type}' переведите сумму на номер +7 952 551 5554 (Сбербанк).\n"
            "После оплаты нажмите кнопку 'Оплачено'.",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Ошибка при обработке выбора тарифа: {e}")
        await query.message.reply_text("Произошла ошибка. Попробуйте снова.")

async def confirm_payment(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    _, user_id, course_type, tariff_code = query.data.split('_')
    user_id = int(user_id)

    # Получаем данные из CODE_WORDS
    course_type_full, course, tariff_type = CODE_WORDS.get(tariff_code, ("unknown", "unknown", "Неизвестный тариф"))

    # Обновляем статус оплаты в базе данных
    cursor.execute(f'''
        UPDATE users 
        SET {course_type}_paid = TRUE, 
            {course_type}_tariff = ? 
        WHERE user_id = ?
    ''', (tariff_type, user_id))
    conn.commit()

    # Уведомляем пользователя
    await context.bot.send_message(
        chat_id=user_id,
        text=f"Ваша оплата тарифа '{tariff_type}' подтверждена. Доступ к курсу открыт."
    )

    # Уведомляем администраторов
    await query.message.reply_text("Оплата подтверждена.")

async def reject_payment(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    _, user_id, course_type, tariff_code = query.data.split('_')
    user_id = int(user_id)

    # Получаем данные из CODE_WORDS
    course_type_full, course, tariff_type = CODE_WORDS.get(tariff_code, ("unknown", "unknown", "Неизвестный тариф"))

    # Обновляем статус оплаты в базе данных
    cursor.execute(f'''
        UPDATE users 
        SET {course_type}_paid = FALSE, 
            {course_type}_tariff = NULL 
        WHERE user_id = ?
    ''', (user_id,))
    conn.commit()

    # Уведомляем пользователя
    await context.bot.send_message(
        chat_id=user_id,
        text=f"Ваша оплата тарифа '{tariff_type}' отклонена. Пожалуйста, свяжитесь с поддержкой."
    )

    # Уведомляем администраторов
    await query.message.reply_text("Оплата отклонена.")

async def handle_payment_confirmation(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    _, course_type, tariff_code = query.data.split('_')

    # Получаем данные пользователя
    cursor.execute('SELECT full_name FROM users WHERE user_id = ?', (user_id,))
    full_name = cursor.fetchone()[0]

    # Определяем название тарифа
    tariff = CODE_WORDS.get(tariff_code, "Неизвестный тариф")

    # Отправляем запрос администраторам
    admin_chat_id = ADMIN_GROUP_ID # ID чата администраторов
    keyboard = [
        [InlineKeyboardButton("Подтвердить", callback_data=f'confirm_payment_{user_id}_{course_type}_{tariff_code}')],
        [InlineKeyboardButton("Отклонить", callback_data=f'reject_payment_{user_id}_{course_type}_{tariff_code}')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=admin_chat_id,
        text=f"Запрос на подтверждение оплаты:\n"
             f"Пользователь: {full_name}\n"
             f"Курс: {course_type}\n"
             f"Тариф: {tariff}",
        reply_markup=reply_markup
    )

    # Уведомляем пользователя о статусе проверки
    await query.message.reply_text("Ваша оплата отправлена на проверку. Ожидайте подтверждения.")

async def request_payment(update: Update, context: CallbackContext, course_type: str, tariff: str):
    query = update.callback_query
    print('request_payment')

    # Отправляем сообщение с инструкциями по оплате
    await query.message.reply_text(
        f"Для оплаты тарифа '{tariff}' переведите сумму на указанный счет.\n"
        "После оплаты отправьте чек в ответ на это сообщение."
    )

    # Сохраняем состояние ожидания чека
    context.user_data['awaiting_payment'] = True
    context.user_data['course_type'] = course_type
    context.user_data['tariff'] = tariff

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Регистрация обработчиков
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code_words))
    app.add_handler(CallbackQueryHandler(course_selection, pattern='^.+_course_.*'))  # Все виды выбора курса
    app.add_handler(MessageHandler(filters.PHOTO, handle_homework))
    app.add_handler(CallbackQueryHandler(button_handler, pattern='^((?!course).)*$'))  # Все остальные кнопки
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_code))
    app.add_handler(CallbackQueryHandler(send_preliminary_material, pattern=r'^preliminary_'))

    app.add_handler(CallbackQueryHandler(handle_payment_confirmation, pattern='^payment_done_.+'))
    app.add_handler(CallbackQueryHandler(confirm_payment, pattern='^confirm_payment_.+'))
    app.add_handler(CallbackQueryHandler(reject_payment, pattern='^reject_payment_.+'))

    app.add_handler(CallbackQueryHandler(handle_tariff_selection, pattern='^tariff_.+'))  # Выбор тарифа

    app.run_polling()


if __name__ == '__main__':
    main()
