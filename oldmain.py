import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext, \
    CallbackQueryHandler
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import feedparser

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")

CODE_WORDS = {
    "роза": "Без проверки д/з",
    "фиалка": "С проверкой д/з",
    "лепесток": "Личное сопровождение"
}

# Инициализация базы данных
conn = sqlite3.connect('users.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    tariff TEXT,
    paid BOOLEAN DEFAULT FALSE,
    start_date TEXT,
    last_lesson INTEGER DEFAULT 0
)
''')
conn.commit()

bot = None  # Глобальная переменная для хранения экземпляра бота
FIRST_LESSON_NUMBER = 1
HOMEWORK_WAIT_TIME = 25  # seconds
TARGET_USER_ID = 954230772  # Замените на ваш user_id


def get_lesson_text(lesson_number):
    try:
        with open(f'courses/lessons/lesson{lesson_number}.txt', 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        return "Урок не найден."


async def send_lesson(context: CallbackContext, user_id: int, lesson_number: int):
    lesson_text = get_lesson_text(lesson_number)
    if lesson_text:
        try:
            await context.bot.send_message(chat_id=user_id, text=lesson_text)
            logger.info(f"Sent lesson {lesson_number} to user {user_id}")
            cursor.execute('UPDATE users SET last_lesson = ? WHERE user_id = ?', (lesson_number, user_id))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to send lesson {lesson_number} to user {user_id}: {e}")
    else:
        logger.warning(f"Lesson {lesson_number} not found")


async def start(update: Update, context: CallbackContext):
    global bot
    bot = context.bot
    user_id = update.message.from_user.id
    username = update.message.from_user.username
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
    conn.commit()

    cursor.execute('SELECT paid, tariff, start_date, last_lesson FROM users WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()

    if not user_data or not user_data[0]:  # Если не оплачено
        keyboard = [
            [InlineKeyboardButton("Выбрать тариф", callback_data='choose_tariff')],
            [InlineKeyboardButton("Отправить чек об оплате", callback_data='send_payment')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Добро пожаловать! Выберите тариф или отправьте чек об оплате.",
                                        reply_markup=reply_markup)
    else:
        paid, tariff, start_date_str, last_lesson = user_data
        if last_lesson == 0:
            await update.message.reply_text(
                "Привет! Для начала обучения, пожалуйста, отправь фотографию для первого урока.")
            context.user_data['awaiting_homework'] = True
        else:
            keyboard = [
                [InlineKeyboardButton("Получить новый урок", callback_data='get_lesson')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("У вас есть новый урок. Нажмите кнопку.",
                                            reply_markup=reply_markup)


async def choose_tariff(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("Без проверки д/з - 3000 р.", callback_data='tariff_роза')],
        [InlineKeyboardButton("С проверкой д/з - 5000 р.", callback_data='tariff_фиалка')],
        [InlineKeyboardButton("Личное сопровождение - 12000 р.", callback_data='tariff_лепесток')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите тариф:", reply_markup=reply_markup)


async def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    action = query.data

    if action == 'choose_tariff':
        await choose_tariff(query, context)
    elif action.startswith('tariff_'):
        tariff_code = action.split('_')[1]
        if tariff_code in CODE_WORDS:
            tariff = CODE_WORDS[tariff_code]
            cursor.execute('''
                UPDATE users 
                SET paid = TRUE, 
                    start_date = ?,
                    tariff = ?
                WHERE user_id = ?
            ''', (datetime.now().strftime('%Y-%m-%d'), tariff, user_id))
            conn.commit()
            await query.edit_message_text(text=f"Оплата принята! Тариф: {tariff}")
        else:
            await query.edit_message_text("Неверный выбор тарифа")
    elif action == 'send_payment':
        await query.edit_message_text("Пришлите скрин чека об оплате")
    elif action == 'get_lesson':
        await lessons(query, context)
    elif action.startswith('next_lesson_'):
        lesson_number = int(action.split('_')[2])
        await lessons(update, context, lesson_number)
    elif action == 'settings':
        await query.edit_message_text("Настройки (функция в разработке)")
    elif action == 'upgrade_tariff':
        await query.edit_message_text("Повышение тарифа (функция в разработке)")
    elif action == 'consultation':
        await query.edit_message_text("Запись на консультацию (функция в разработке)")
    elif action == 'random_joke':
        await random_joke(update, context)


async def lessons(update: Update, context: CallbackContext, lesson_number=None):
    user_id = update.effective_user.id
    cursor.execute('SELECT paid, last_lesson FROM users WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()

    if not user_data or not user_data[0]:
        await update.message.reply_text("Пожалуйста, оплатите доступ к урокам.")
        return

    current_lesson = user_data[1] if user_data[1] else 0
    if lesson_number is not None:
        next_lesson = lesson_number
    else:
        next_lesson = current_lesson + 1

    if next_lesson > 11:
        await update.message.reply_text("Вы завершили все уроки!")
        return

    lesson_text = get_lesson_text(next_lesson)
    keyboard = [
        [InlineKeyboardButton("Следующий урок", callback_data=f'next_lesson_{next_lesson + 1}')],
        [InlineKeyboardButton("Настройки", callback_data='settings')],
        [InlineKeyboardButton("Повысить тариф", callback_data='upgrade_tariff')],
        [InlineKeyboardButton("Заказать консультацию", callback_data='consultation')],
        [InlineKeyboardButton("Случайный анекдот", callback_data='random_joke')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(lesson_text, reply_markup=reply_markup)
    cursor.execute('UPDATE users SET last_lesson = ? WHERE user_id = ?', (next_lesson, user_id))
    conn.commit()


async def personal_support(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    cursor.execute('SELECT tariff FROM users WHERE user_id = ?', (user_id,))
    tariff = cursor.fetchone()[0]

    if tariff != "Личное сопровождение":
        await update.message.reply_text("Для консультации выберите тариф 'Личное сопровождение'")
        return

    await update.message.reply_text("Вы записаны на консультацию. Мы свяжемся с вами в ближайшее время.")


async def homework(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id

    if context.user_data.get('awaiting_homework'):
        photo_file = await update.message.photo[-1].get_file()
        await photo_file.download_as_bytearray()  # <- Это чтобы не ругался

        # пересылаем фото вам
        try:
            await context.bot.forward_message(chat_id=TARGET_USER_ID, from_chat_id=user_id,
                                              message_id=update.message.message_id)
            await update.message.reply_text("Спасибо за ДЗ! Отправил на проверку")
        except Exception as e:
            logger.error(f"Error forwarding message: {e}")
            await update.message.reply_text("Что-то пошло не так :(")
        context.user_data['awaiting_homework'] = False

        #  через минуту - следующий урок
        context.job_queue.run_once(
            callback=send_next_lesson,
            when=HOMEWORK_WAIT_TIME,
            user_id=user_id
        )
    else:
        await update.message.reply_text("Я не жду от вас сейчас домашку")


async def handle_message(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    message_text = update.message.text.lower()
    if context.user_data.get('awaiting_homework'):
        await update.message.reply_text("Я жду от тебя фотографию")
        return

    if message_text in CODE_WORDS:
        tariff = CODE_WORDS[message_text]
        cursor.execute('''
            UPDATE users 
            SET paid = TRUE, 
                start_date = ?,
                tariff = ?
            WHERE user_id = ?
        ''', (datetime.now().strftime('%Y-%m-%d'), tariff, user_id))
        conn.commit()
        await update.message.reply_text(
            f"Оплата принята! Вы выбрали тариф '{tariff}'. Вы можете начать обучение.")
    else:
        await update.message.reply_text("Неопознанное сообщение")


async def auto_send_lessons(context: CallbackContext):
    cursor.execute('SELECT user_id, last_lesson FROM users WHERE paid = TRUE')
    users = cursor.fetchall()
    for user_id, last_lesson in users:
        next_lesson = last_lesson + 1
        if next_lesson <= 11:
            lesson_text = get_lesson_text(next_lesson)
            logger.info(f"Sending lesson {next_lesson} to user {user_id}")
            await context.bot.send_message(chat_id=user_id, text=lesson_text)
            cursor.execute('UPDATE users SET last_lesson = ? WHERE user_id = ?', (next_lesson, user_id))
            conn.commit()


async def send_next_lesson(context: CallbackContext):
    job = context.job
    user_id = job.user_id
    cursor.execute('SELECT last_lesson FROM users WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()

    if user_data:
        current_lesson = user_data[0]
        next_lesson = current_lesson + 1
        if next_lesson <= 11:
            await send_lesson(context, user_id, next_lesson)


async def random_joke(update: Update, context: CallbackContext):
    rss_url = "https://anekdotov-mnogo.ru/anekdoty_rss.xml"
    feed = feedparser.parse(rss_url)
    if len(feed.entries) > 0:
        random_entry = feed.entries[0]
        joke = random_entry.title + "\n\n" + random_entry.description
        await update.message.reply_text(joke)
    else:
        await update.message.reply_text("Не удалось получить анекдот.")


if __name__ == '__main__':
    application = ApplicationBuilder().token(telegram_bot_token).build()

    # Добавили JobQueue
    jq = application.job_queue

    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("tariff", choose_tariff))
    application.add_handler(CommandHandler("support", personal_support))
    application.add_handler(MessageHandler(filters.PHOTO, homework))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button))

    # auto send every 3 mins
    jq.run_repeating(auto_send_lessons, interval=3 * 60, first=10)

    application.run_polling()
