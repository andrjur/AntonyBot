# database.py
import sqlite3
import logging
import json  # Import json
from telegram import Update
from telegram.ext import CallbackContext

# Импортируем функции из utils.py
from utils import safe_reply

DATABASE_FILE = "bot_db.sqlite"
BONUSES_FILE = "bonuses.json"
COURSE_DATA_FILE = "courses.json"
AD_CONFIG_FILE = "ad_config.json"
DELAY_MESSAGES_FILE = "delay_messages.txt"

logger = logging.getLogger(__name__)

class DatabaseConnection:
    _instance = None

    def __new__(cls, db_file=DATABASE_FILE):
        if cls._instance is None:
            cls._instance = super(DatabaseConnection, cls).__new__(cls)
            try:
                cls._instance.conn = sqlite3.connect(db_file)
                cls._instance.cursor = cls._instance.conn.cursor()
                logger.info(f"DatabaseConnection: Подключение к {db_file}")
            except sqlite3.Error as e:
                logger.error(f"DatabaseConnection: Ошибка при подключении к базе данных: {e}")
                cls._instance.conn = None
                cls._instance.cursor = None
        return cls._instance

    def get_connection(self):
        return self.conn

    def get_cursor(self):
        return self.cursor

    def close(self):
        if self.conn:
            self.conn.close()
            logger.info("DatabaseConnection: Соединение с базой данных закрыто.")
            self.conn = None
            self.cursor = None

def create_all_tables():
    """Создает все необходимые таблицы, если они еще не существуют."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    logger.info("Таблицы SQL создаются или проверяются на существование...")

    try:
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL DEFAULT 'ЧЕБУРАШКА',
                birthday TEXT,
                registration_date TEXT,
                referral_count INTEGER DEFAULT 0,
                penalty_task TEXT,
                preliminary_material_index INTEGER DEFAULT 0,
                tariff TEXT,
                continuous_flow BOOLEAN DEFAULT 0,
                next_lesson_time DATETIME,
                active_course_id TEXT,
                user_code TEXT,
                awards TEXT,
                last_bonus_date TEXT,
                coins REAL DEFAULT 13.0,
                trust_credit REAL DEFAULT 1.0,
                invited_by INTEGER, 
                support_requests INTEGER DEFAULT 0,
                morning_time TEXT,   
                evening_time TEXT,
                FOREIGN KEY(invited_by) REFERENCES users(user_id)     
            );

            CREATE TABLE IF NOT EXISTS homeworks (
                hw_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                course_id TEXT,  
                lesson INTEGER,
                file_id TEXT,
                file_type TEXT,
                message_id INTEGER,
                status TEXT DEFAULT 'pending',
                feedback TEXT,
                timestamp TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
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
                action TEXT, 
                amount INTEGER,
                reason TEXT, 
                timestamp TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS lootboxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                box_type TEXT, 
                reward TEXT, 
                probability REAL 
            );

            CREATE TABLE IF NOT EXISTS admins (
                admin_id INTEGER PRIMARY KEY,
                level INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS admin_codes (
                code_id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                code TEXT,
                created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
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

            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY,
                product_name TEXT NOT NULL,
                price INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS referrals (
                referrer_id INTEGER, -- ID пользователя, который пригласил
                referred_user_id INTEGER, -- ID реферрала
                referral_date TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                PRIMARY KEY (referrer_id, referred_user_id),
                FOREIGN KEY(referrer_id) REFERENCES users(user_id),
                FOREIGN KEY(referred_user_id) REFERENCES users(user_id)
);

            CREATE TABLE IF NOT EXISTS user_courses (
                user_id INTEGER,
                course_id TEXT,
                course_type TEXT CHECK(course_type IN ('main', 'auxiliary')),
                progress INTEGER DEFAULT 0,
                purchase_date TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                tariff TEXT,
                PRIMARY KEY (user_id, course_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            """
        )
        conn.commit()
        logger.info("Таблицы успешно созданы или уже существовали.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при создании таблиц: {e}")

USER_CACHE = {}

def get_user_data(user_id: int):
    """Получает данные пользователя из базы данных."""
    if user_id in USER_CACHE:
        logger.info(f" в кэше нашли ")
        return USER_CACHE[user_id]
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    data = cursor.fetchone()
    if data:
        logger.info(f" запишем ка в кэш")
        USER_CACHE[user_id] = data
        return data
    logger.warning(f" нету нихрена")
    return None

def clear_user_cache(user_id: int):
    """Очищает кэш для указанного пользователя."""
    logger.info(f" clear_user_cache {user_id} очистили")
    if user_id in USER_CACHE:
        del USER_CACHE[user_id]

async def handle_error(update: Update, context: CallbackContext, error: Exception):
    """Handles errors that occur in the bot."""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()

    logger.error(f"Произошла ошибка:: {error}")

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

def load_bonuses():
    """Загружает настройки бонусов из файла."""
    try:
        with open(BONUSES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Файл {BONUSES_FILE} не найден. Используются значения по умолчанию.")
        return {
            "monthly_bonus": 1,
            "birthday_bonus": 5,
            "referral_bonus": 2,
            "bonus_check_interval": 86400,  # 24 hours
        }
    except json.JSONDecodeError:
        logger.error(f"Ошибка при чтении JSON из файла {BONUSES_FILE}. Используются значения по умолчанию.")
        return {
            "monthly_bonus": 1,
            "birthday_bonus": 5,
            "referral_bonus": 2,
            "bonus_check_interval": 86400,  # 24 hours
        }

def load_courses():
    """Загружает список курсов из файла."""
    try:
        with open(COURSE_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Файл {COURSE_DATA_FILE} не найден.")
        return []
    except json.JSONDecodeError:
        logger.error(f"Ошибка при чтении JSON из файла {COURSE_DATA_FILE}.")
        return []

def load_ad_config():
    """Загружает конфигурацию рекламы из файла."""
    try:
        with open(AD_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Файл {AD_CONFIG_FILE} не найден. Используются значения по умолчанию.")
        return {"ad_percentage": 0.3}  # Default 5% ad percentage
    except json.JSONDecodeError:
        logger.error(f"Ошибка при чтении JSON из файла {AD_CONFIG_FILE}. Используются значения по умолчанию.")
        return {"ad_percentage": 0.3}

def load_course_data(filename):
    """Загружает данные о курсах из JSON файла."""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Файл с данными о курсах не найден: {filename}")
        return {}
    except json.JSONDecodeError:
        logger.error(f"Ошибка при чтении JSON файла: {filename}")
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке данных о курсах: {e}")
        return {}

def load_delay_messages(file_path=DELAY_MESSAGES_FILE):
    """Загружает список фраз из текстового файла."""
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            messages = [line.strip() for line in file if line.strip()]
            logger.info(f"Загружено {len(messages)} фразочек")
        return messages
    except FileNotFoundError:
        logger.error(f"Файл c фразами не найден: {file_path}")
        return ["Сообщение не найдено."]
    except Exception as e:
        logger.error(f"Ошибка при загрузке фраз: {e}")
        return ["Ошибка загрузки сообщения."]
