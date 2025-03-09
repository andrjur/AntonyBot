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


def get_lesson_text(lesson_number):
    try:
        with open(f'lessons/lesson{lesson_number}.txt', 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        return "Урок не найден."


async def start(update: Update, context: CallbackContext):
    logger.info(f"User {update.message.from_user.id} started the bot")
    global bot
    bot = context.bot
    user_id = update.message.from_user.id
    username = update.message.from_user.username
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
    conn.commit()

    cursor.execute('SELECT paid, tariff, start_date, last_lesson FROM users WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()

    if not user_data or not user_data[0]:  # Если не оплачено
        logger.info(f"User {user_id} is not paid")
        keyboard = [
            [InlineKeyboardButton("Выбрать тариф", callback_data='choose_tariff')],
            [InlineKeyboardButton("Отправить чек об оплате", callback_data='send_payment')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Добро пожаловать! Выберите тариф или отправьте чек об оплате.",
                                          reply_markup=reply_markup)
    else:
        paid, tariff, start_date_str, last_lesson = user_data
        logger.info(f"User {user_id} is paid. Tariff: {tariff}, start_date: {start_date_str}, last_lesson: {last_lesson}")

        if start_date_str is None or start_date_str == "":
            start_date = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('UPDATE users SET start_date = ? WHERE user_id = ?', (start_date, user_id))
            conn.commit()
            logger.info(f"User {user_id} start_date updated to {start_date}")
        else:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            except ValueError:
                start_date = datetime.now().strftime('%Y-%m-%d')
                cursor.execute('UPDATE users SET start_date = ? WHERE user_id = ?', (start_date, user_id))
                conn.commit()
                logger.warning(f"Invalid start_date for user {user_id}. Updated to {start_date}")

        days_passed = (datetime.now() - start_date).days
        available_lesson = min(days_passed // 3 + 1, 11)

        if last_lesson < available_lesson:
            logger.info(f"User {user_id} has a new lesson available: {available_lesson}")
            keyboard = [
                [InlineKeyboardButton("Получить новый урок", callback_data='get_lesson')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"У вас доступен новый урок {available_lesson}. Нажмите кнопку для получения урока.",
                reply_markup=reply_markup)
        else:
            logger.info(f"User {user_id} has already received the current lesson {last_lesson}")
            await update.message.reply_text(f"Вы уже получили доступ к текущему уроку {last_lesson}.")

        if tariff in ["С проверкой д/з", "Личное сопровождение"]:
            await update.message.reply_text(
                "Вы можете отправить домашнее задание. Просто загрузите фото с выполненным заданием.")

        if tariff == "Личное сопровождение":
            await update.message.reply_text(
                "Вы записаны на личную консультацию. Используйте команду /support для записи на консультацию.")


async def choose_tariff(update: Update, context: CallbackContext):
    logger.info(f"User {update.effective_user.id} is choosing a tariff")
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
    logger.info(f"User {user_id} pressed button: {action}")

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
            logger.info(f"User {user_id} chose tariff: {tariff}")
        else:
            await query.edit_message_text("Неверный выбор тарифа")
            logger.warning(f"User {user_id} made an invalid tariff choice")
    elif action == 'send_payment':
        await query.edit_message_text("Пришлите скрин чека об оплате")
        logger.info(f"User {user_id} is sending a payment proof")
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
    logger.info(f"User {user_id} is requesting a lesson. Specific lesson: {lesson_number}")
    cursor.execute('SELECT paid, last_lesson FROM users WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()

    if not user_data or not user_data[0]:
        await update.message.reply_text("Пожалуйста, оплатите доступ к урокам.")
        logger.warning(f"User {user_id} requested a lesson but is not paid")
        return

    current_lesson = user_data[1] if user_data[1] else 0
    if lesson_number is not None:
        next_lesson = lesson_number
    else:
        next_lesson = current_lesson + 1

    if next_lesson > 11:
        await update.message.reply_text("Вы завершили все уроки!")
        logger.info(f"User {user_id} has completed all lessons")
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
    logger.info(f"User {user_id} received lesson {next_lesson}")


async def personal_support(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    logger.info(f"User {user_id} is requesting personal support")
    cursor.execute('SELECT tariff FROM users WHERE user_id = ?', (user_id,))
    tariff = cursor.fetchone()[0]

    if tariff != "Личное сопровождение":
        await update.message.reply_text("Для консультации выберите тариф 'Личное сопровождение'")
        logger.warning(f"User {user_id} requested support but does not have the correct tariff")
        return

    await update.message.reply_text("Вы записаны на консультацию. Мы свяжемся с вами в ближайшее время.")
    logger.info(f"User {user_id} has been scheduled for a consultation")


async def homework(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    logger.info(f"User {user_id} is submitting homework")
    cursor.execute('SELECT last_lesson, tariff FROM users WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()

    if user_data[0] == 0:
        await update.message.reply_text("Вы еще не начали обучение.")
        logger.warning(f"User {user_id} submitted homework before starting lessons")
        return

    file_id = update.message.photo[-1].file_id
    await update.message.reply_text(f"Домашнее задание к уроку {user_data[0]} принято!")

    if user_data[1] in ["С проверкой д/з", "Личное сопровождение"]:
        await update.message.reply_text("Проверяю ваше задание...")
        logger.info(f"Homework submitted by user {user_id} is being reviewed")


async def handle_message(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    message_text = update.message.text.lower()
    logger.info(f"User {user_id} sent a message: {message_text}")

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
        logger.info(f"User {user_id} successfully paid for tariff: {tariff}")
    else:
        await update.message.reply_text("Неопознанное сообщение")
        logger.warning(f"User {user_id} sent an unrecognized message: {message_text}")


async def auto_send_lessons(context: CallbackContext):
    logger.info("Checking for users to send new lessons...")
    cursor.execute('SELECT user_id, last_lesson FROM users WHERE paid = TRUE')
    users = cursor.fetchall()
    for user_id, last_lesson in users:
        next_lesson = last_lesson + 1
        if next_lesson <= 11:
            lesson_text = get_lesson_text(next_lesson)
            logger.info(f"Sending lesson {next_lesson} to user {user_id}")
            try:
                await context.bot.send_message(chat_id=user_id, text=lesson_text)
                cursor.execute('UPDATE users SET last_lesson = ? WHERE user_id = ?', (next_lesson, user_id))
                conn.commit()
                logger.info(f"Successfully sent lesson {next_lesson} to user {user_id}")
            except Exception as e:
                logger.error(f"Failed to send lesson {next_lesson} to user {user_id}: {e}")
        else:
            logger.info(f"User {user_id} has completed all lessons")


async def random_joke(update: Update, context: CallbackContext):
    logger.info(f"User {update.effective_user.id} requested a random joke")
    rss_url = "https://anekdotov-mnogo.ru/anekdoty_rss.xml"
    try:
        feed = feedparser.parse(rss_url)
        if len(feed.entries) > 0:
            random_entry = feed.entries[0]
            joke = random_entry.title + "\n\n" + random_entry.description
            await update.message.reply_text(joke)
            logger.info(f"Sent a random joke to user {update.effective_user.id}")
        else:
            await update.message.reply_text("Не удалось получить анекдот.")
            logger.warning("Failed to fetch a joke from the RSS feed")
    except Exception as e:
        await update.message.reply_text("Не удалось получить анекдот.")
        logger.error(f"Failed to fetch a joke from the RSS feed: {e}")


if __name__ == '__main__':
    # Убрали .job_queue(True) из ApplicationBuilder
    application = ApplicationBuilder().token(telegram_bot_token).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("tariff", choose_tariff))
    application.add_handler(CommandHandler("support", personal_support))
    application.add_handler(MessageHandler(filters.PHOTO, homework))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button))

    # Убрали дублирующуюся функцию auto_send_lessons (она уже определена выше)

    # Настройка планировщика
    application.job_queue.run_repeating(
        auto_send_lessons,
        interval=180,
        first=10
    )

    application.run_polling()

