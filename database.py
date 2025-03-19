# database.py
import sqlite3
import logging
import json  # Import json
from telegram import Update
from telegram.ext import CallbackContext

# Импортируем функции из utils.py
from utils import safe_reply

# Configuration constants
DATABASE_FILE = "bot_db.sqlite"
BONUSES_FILE = "bonuses.json"
COURSE_DATA_FILE = "courses.json"
AD_CONFIG_FILE = "ad_config.json"
DELAY_MESSAGES_FILE = "delay_messages.txt"

logger = logging.getLogger(__name__)

# User data cache
USER_CACHE = {}

class DatabaseConnection:
    """Singleton class for database connection management"""
    _instance = None

    def __new__(cls, db_file=DATABASE_FILE):
        if cls._instance is None:
            cls._instance = super(DatabaseConnection, cls).__new__(cls)
            try:
                cls._instance.conn = sqlite3.connect(db_file)
                cls._instance.cursor = cls._instance.conn.cursor()
                logger.info(f"DatabaseConnection: Connected to {db_file}")
            except sqlite3.Error as e:
                logger.error(f"DatabaseConnection: Database connection error: {e}")
                cls._instance.conn = None
                cls._instance.cursor = None
        return cls._instance

    def get_connection(self):
        """Returns the SQLite connection object"""
        return self.conn

    def get_cursor(self):
        """Returns the SQLite cursor object"""
        return self.cursor

    def close(self):
        """Closes the database connection"""
        if self.conn:
            self.conn.close()
            logger.info("DatabaseConnection: Database connection closed")
            self.conn = None
            self.cursor = None

# Database schema management
def create_all_tables():
    """Creates all necessary tables if they don't exist"""
    db = DatabaseConnection()
    conn = db.get_connection()
    cursor = db.get_cursor()
    logger.info("Creating or verifying SQL tables...")

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
                tokens INTEGER DEFAULT 0,
                last_bonus_date TEXT
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
            CREATE TABLE IF NOT EXISTS user_bonuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                bonus_amount REAL NOT NULL,
                expiry_date DATETIME NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_discounts (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                amount INTEGER,
                expiry_date TEXT,
                used INTEGER DEFAULT 0
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
        if conn:  # Check if connection exists before committing
            conn.commit()
        logger.info("Tables successfully created or already existed")
    except sqlite3.Error as e:
        logger.error(f"Error creating tables: {e}")

# User data management
def get_user_data(user_id: int):
    """Gets user data from database with caching"""
    if user_id in USER_CACHE:
        logger.info("Found in cache")
        return USER_CACHE[user_id]
    
    db = DatabaseConnection()
    cursor = db.get_cursor()

    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    data = cursor.fetchone()
    if data:
        logger.info("Caching user data")
        USER_CACHE[user_id] = data
        return data
    logger.warning("User not found")
    return None

def clear_user_cache(user_id: int):
    """Clears cached data for specified user"""
    logger.info(f"Clearing cache for user {user_id}")
    if user_id in USER_CACHE:
        del USER_CACHE[user_id]

# Error handling
async def handle_error(update: Update, context: CallbackContext, error: Exception):
    """Handles bot errors"""
    logger.error(f"Error occurred: {error}")

# Configuration loaders
def load_payment_info(filename: str) -> dict:
    """Loads payment data from JSON file"""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            logger.info(f"Payment data file loaded: {filename}")
            return data
    except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
        logger.error(f"Error loading payment data: {e}")
        return {}

def load_bonuses() -> dict:
    """Loads bonus settings with defaults"""
    default_bonuses = {
        "monthly_bonus": 1,
        "birthday_bonus": 5,
        "referral_bonus": 2,
        "bonus_check_interval": 86400,  # 24 hours
    }
    
    try:
        with open(BONUSES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Error loading bonuses, using defaults: {e}")
        return default_bonuses

def load_courses() -> list:
    """Loads course list"""
    try:
        with open(COURSE_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Error loading courses: {e}")
        return []

def load_ad_config() -> dict:
    """Loads advertising configuration"""
    default_config = {"ad_percentage": 0.3}
    try:
        with open(AD_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Error loading ad config, using defaults: {e}")
        return default_config

def load_course_data(filename: str) -> dict:
    """Loads course data from JSON file"""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
        logger.error(f"Error loading course data: {e}")
        return {}

def load_delay_messages(file_path: str = DELAY_MESSAGES_FILE) -> list:
    """Loads delay messages from text file"""
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            messages = [line.strip() for line in file if line.strip()]
            logger.info(f"Loaded {len(messages)} messages")
            return messages
    except (FileNotFoundError, Exception) as e:
        logger.error(f"Error loading delay messages: {e}")
        return ["Message not found"]
