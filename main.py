import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext, \
    CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import sqlite3
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
import os

load_dotenv()  # Загружает переменные из .env
telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")

# Словарь с кодовыми словами и соответствующими тарифами
CODE_WORDS = {
    "роза": "Без проверки д/з",
    "фиалка": "С проверкой д/з",
    "лепесток": "Личное сопровождение"
}

# Инициализация базы данных
conn = sqlite3.connect('users.db', check_same_thread=False)
cursor = conn.cursor()

# Создание таблицы пользователей
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

# Команда /start
async def start(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    username = update.message.from_user.username
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
    conn.commit()

    # Проверяем, есть ли пользователь в базе данных
    cursor.execute('SELECT paid, tariff, start_date, last_lesson FROM users WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()

    if not user_data or not user_data[0]:  # Если не оплачено
        keyboard = [
            [InlineKeyboardButton("Выбрать тариф", callback_data='choose_tariff')],
            [InlineKeyboardButton("Отправить чек об оплате", callback_data='send_payment')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Добро пожаловать! Выберите тариф или отправьте чек об оплате.", reply_markup=reply_markup)
    else:
        paid, tariff, start_date_str, last_lesson = user_data

        if start_date_str is None or start_date_str == "":
            start_date = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('UPDATE users SET start_date = ? WHERE user_id = ?', (start_date, user_id))
            conn.commit()
        else:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            except ValueError:
                start_date = datetime.now().strftime('%Y-%m-%d')
                cursor.execute('UPDATE users SET start_date = ? WHERE user_id = ?', (start_date, user_id))
                conn.commit()

        days_passed = (datetime.now() - start_date).days
        available_lesson = min(days_passed // 3 + 1, 11)

        if last_lesson < available_lesson:
            keyboard = [
                [InlineKeyboardButton("Получить новый урок", callback_data='get_lesson')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(f"У вас доступен новый урок {available_lesson}. Нажмите кнопку для получения урока.", reply_markup=reply_markup)
        else:
            await update.message.reply_text(f"Вы уже получили доступ к текущему уроку {last_lesson}.")

        if tariff == "С проверкой д/з" or tariff == "Личное сопровождение":
            await update.message.reply_text("Вы можете отправить домашнее задание. Просто загрузите фото с выполненным заданием.")

        if tariff == "Личное сопровождение":
            await update.message.reply_text("Вы записаны на личную консультацию. Используйте команду /support для записи на консультацию.")
# Выбор тарифа

async def choose_tariff(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("Без проверки д/з - 3000 р.", callback_data='tariff_роза')],
        [InlineKeyboardButton("С проверкой д/з - 5000 р.", callback_data='tariff_фиалка')],
        [InlineKeyboardButton("Личное сопровождение - 12000 р.", callback_data='tariff_лепесток')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите тариф:", reply_markup=reply_markup)

# Обработка нажатий на кнопки
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
            cursor.execute('UPDATE users SET paid = TRUE, start_date = ?, tariff = ? WHERE user_id = ?',
                           (datetime.now().strftime('%Y-%m-%d'), tariff, user_id))
            conn.commit()
            await query.edit_message_text(text=f"Оплата принята! Вы выбрали тариф '{tariff}'. Вы можете начать обучение.")
        else:
            await query.edit_message_text(text="Неверный выбор. Пожалуйста, попробуйте снова.")
    elif action == 'send_payment':
        await query.edit_message_text(text="Пожалуйста, отправьте чек об оплате.")
    elif action == 'get_lesson':
        await lessons(query, context)



# Обработка кодовых слов
async def handle_message(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    message_text = update.message.text.lower()  # Преобразуем текст в нижний регистр для удобства сравнения

    if message_text in CODE_WORDS:
        tariff = CODE_WORDS[message_text]
        cursor.execute('UPDATE users SET paid = TRUE, start_date = ?, tariff = ? WHERE user_id = ?',
                       (datetime.now().strftime('%Y-%m-%d'), tariff, user_id))
        conn.commit()
        await update.message.reply_text(f"Оплата принята! Вы выбрали тариф '{tariff}'. Вы можете начать обучение.")
    else:
        # Если сообщение не является кодовым словом, проверяем другие условия или игнорируем его
        pass

# Логика выдачи уроков
async def lessons(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    cursor.execute('SELECT paid, start_date, last_lesson FROM users WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()

    if not user_data or not user_data[0]:  # Если не оплачено
        await update.message.reply_text("Пожалуйста, оплатите доступ к урокам.")
        return

    start_date = datetime.strptime(user_data[1], '%Y-%m-%d')
    days_passed = (datetime.now() - start_date).days
    available_lesson = min(days_passed // 3 + 1, 11)  # Максимум 11 уроков

    if user_data[2] >= available_lesson:  # Если уже выдан последний доступный урок
        await update.message.reply_text("Вы уже получили доступ к текущему уроку.")
        return

    lesson_text = get_lesson_text(available_lesson)
    await update.message.reply_text(lesson_text)

    cursor.execute('UPDATE users SET last_lesson = ? WHERE user_id = ?', (available_lesson, user_id))
    conn.commit()

def get_lesson_text(lesson_number):
    lessons = {
        1: "Задание 1. Арт-терапия...",
        2: "Задание 2. Медитация от чувства вины...",
        # Добавьте остальные уроки
    }
    return lessons.get(lesson_number, "Урок не найден.")

# Обработка домашних заданий
async def homework(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    cursor.execute('SELECT last_lesson, tariff FROM users WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()

    if user_data[0] == 0:
        await update.message.reply_text("Вы еще не начали обучение.")
        return

    file_id = update.message.photo[-1].file_id
    await update.message.reply_text(f"Домашнее задание к уроку {user_data[0]} принято!")

    if user_data[1] == "С проверкой д/з" or user_data[1] == "Личное сопровождение":
        await update.message.reply_text(f"За проверку уплочено - Проверяю")

# Личное сопровождение
async def personal_support(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    cursor.execute('SELECT tariff FROM users WHERE user_id = ?', (user_id,))
    tariff = cursor.fetchone()[0]

    if tariff != "Личное сопровождение":
        await update.message.reply_text("Для записи на консультацию необходимо выбрать тариф 'Личное сопровождение'.")
        return

    await update.message.reply_text("Вы записаны на консультацию. Ожидайте деталей.")

# Основная функция
if __name__ == '__main__':
    application = ApplicationBuilder().token(telegram_bot_token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("lessons", lessons))
    application.add_handler(CommandHandler("tariff", choose_tariff))
    application.add_handler(CommandHandler("support", personal_support))
    application.add_handler(MessageHandler(filters.PHOTO, homework))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # Добавьте обработчик для кнопок
    application.add_handler(CallbackQueryHandler(button))


    application.run_polling()