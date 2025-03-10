import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext, \
    CallbackQueryHandler
import sqlite3
from datetime import datetime
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

# Инициализация БД
conn = sqlite3.connect('bot_db.sqlite', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
cursor.executescript('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    full_name TEXT,
    tariff TEXT,
    paid BOOLEAN DEFAULT 0,
    current_lesson INTEGER DEFAULT 0,
    homework_status TEXT DEFAULT 'none'
);

CREATE TABLE IF NOT EXISTS homeworks (
    hw_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    lesson INTEGER,
    file_id TEXT,
    status TEXT DEFAULT 'pending',
    feedback TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS admins (
    admin_id INTEGER PRIMARY KEY,
    level INTEGER DEFAULT 1
);
''')
conn.commit()

async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    cursor.execute('INSERT OR IGNORE INTO users (user_id, full_name) VALUES (?, ?)',
                   (user.id, user.full_name))
    conn.commit()

    # Получаем информацию о пользователе
    cursor.execute('''
        SELECT tariff, paid, current_lesson, homework_status 
        FROM users WHERE user_id = ?
    ''', (user.id,))
    data = cursor.fetchone()

    # Формируем сообщение
    status = "✅ Оплачено" if data[1] else "❌ Не оплачено"
    homework_status = {
        'none': "Не требуется",
        'pending': "⏳ Ожидает проверки",
        'approved': "✅ Принято",
        'rejected': "❌ Требует доработки"
    }.get(data[3], "Неизвестный статус")

    text = f"""👋 Привет, {user.full_name}!

📚 Ваш курс: {data[0] or 'Не выбран'}
{status}
📖 Текущий урок: {data[2]}
📝 Статус ДЗ: {homework_status}"""

    keyboard = [
        [InlineKeyboardButton("💰 Выбрать тариф", callback_data='tariffs'),
         InlineKeyboardButton("📸 Отправить ДЗ", callback_data='send_hw')],
        [InlineKeyboardButton("📚 Получить урок", callback_data='get_lesson'),
         InlineKeyboardButton("👥 Галерея работ", callback_data='gallery')],
        [InlineKeyboardButton("🆘 Поддержка", callback_data='support'),
         InlineKeyboardButton("👨‍💻 Админ-меню", callback_data='admin_menu')]
    ]

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_homework(update: Update, context: CallbackContext):
    user = update.effective_user
    photo = update.message.photo[-1]

    # Сохраняем file_id в БД
    cursor.execute('''
        INSERT INTO homeworks (user_id, lesson, file_id)
        VALUES (?, (SELECT current_lesson FROM users WHERE user_id = ?), ?)
    ''', (user.id, user.id, photo.file_id))
    conn.commit()

    # Уведомление админов
    await context.bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=f"📸 Новое ДЗ от {user.full_name}\nУрок: {cursor.lastrowid}\n",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Проверить", callback_data=f"review_{user.id}")]])
    )

    await update.message.reply_text("📌 Ваше ДЗ сохранено и отправлено на проверку!")

async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data

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
    elif data == 'admin_menu':
        await show_admin_menu(update, context)
    elif data.startswith('admin'):
        data_split = data.split('_')
        if len(data_split) > 1:
            if data_split[1] == 'approve':
                await handle_admin_approval(update, context)
            elif data_split[1] == 'reject':
                await handle_admin_rejection(update, context)
            elif data_split[0] == 'review':
                await show_homework(update, context)

async def handle_admin_approval(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = int(query.data.split('_')[2])

    cursor.execute('''
        UPDATE users 
        SET homework_status = 'approved', current_lesson = current_lesson + 1
        WHERE user_id = ?
    ''', (user_id,))
    conn.commit()

    await query.edit_message_text("✅ ДЗ одобрено!")
    await context.bot.send_message(user_id, "🎉 Ваше ДЗ принято! Можете получить следующий урок.")

async def handle_admin_rejection(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = int(query.data.split('_')[2])

    cursor.execute("UPDATE users SET homework_status = 'rejected' WHERE user_id = ?", (user_id,))
    conn.commit()

    await query.edit_message_text("❌ ДЗ отклонено. Ожидайте обратной связи.")
    await context.bot.send_message(user_id, "📛 Ваше ДЗ требует доработки. Ожидайте комментариев от куратора.")

async def show_homework(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = int(query.data.split('_')[1])

    cursor.execute('SELECT file_id FROM homeworks WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1', (user_id,))
    file_id = cursor.fetchone()[0]

    await context.bot.send_photo(
        chat_id=query.message.chat_id,
        photo=file_id,
        caption=f"Домашняя работа пользователя {user_id}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Принять", callback_data=f'admin_approve_{user_id}'),
             InlineKeyboardButton("❌ Отклонить", callback_data=f'admin_reject_{user_id}')]
        ])
    )

async def show_tariffs(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("💰 Без проверки ДЗ", callback_data='tariff_no_check')],
        [InlineKeyboardButton("📚 С проверкой ДЗ", callback_data='tariff_with_check')],
        [InlineKeyboardButton("🌟 Премиум (личный куратор)", callback_data='tariff_premium')]
    ]
    await update.callback_query.message.reply_text("Выберите тариф:", reply_markup=InlineKeyboardMarkup(keyboard))

async def request_homework(update: Update, context: CallbackContext):
    await update.callback_query.message.reply_text("Отправьте фото вашего домашнего задания:")

async def get_lesson(update: Update, context: CallbackContext):
    user = update.effective_user
    cursor.execute('SELECT current_lesson FROM users WHERE user_id = ?', (user.id,))
    lesson = cursor.fetchone()[0] + 1  # Следующий урок
    lesson_text = get_lesson_text(lesson)
    if lesson_text:
        await update.callback_query.message.reply_text(lesson_text)
    else:
        await update.callback_query.message.reply_text("Урок не найден!")

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

def get_lesson_text(lesson_number):
    try:
        with open(f'lessons/lesson{lesson_number}.txt', 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        return None

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Регистрация обработчиков
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_homework))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()

if __name__ == '__main__':
    main()
