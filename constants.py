#constants.py
import os
import logging
from datetime import timedelta
from dotenv import load_dotenv

class CustomFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        full_time = super().formatTime(record, datefmt)
        return full_time[-9:]

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),  # Указываем кодировку utf-8 для файла
        logging.StreamHandler()  # Для вывода в консоль
    ],
)

# Замена стандартного Formatter на пользовательский
for handler in logging.getLogger().handlers:
    handler.setFormatter(CustomFormatter('%(asctime)s - %(levelname)s - %(message)s'))

logger = logging.getLogger(__name__)

# Настройка уровня логирования для библиотеки httpx
logging.getLogger("httpx").setLevel(logging.WARNING)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))


ADMIN_IDS = [int(id_) for id_ in os.getenv("ADMIN_IDS", "").split(",") if id_]
logger.info(f"Admin IDs: {ADMIN_IDS}")
# Status Constants
HOMEWORK_STATUS = {
    "PENDING": "pending",
    "APPROVED": "approved",
    "REJECTED": "rejected"
}

# Course Settings
DEFAULT_LESSON_DELAY = 24
DEFAULT_LESSON_INTERVAL = 24
DEFAULT_LESSON_DELAY_HOURS = 3
HARD_CODE_DELAY = 5  # seconds for file sending delays

# File Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COURSES_DIR = os.path.join(BASE_DIR, "courses")
PERSISTENCE_FILE = "bot_data.pkl"

CONFIG_FILES = {
    "TARIFFS": os.path.join(BASE_DIR, "config", "tariffs.json"),
    "COURSES": os.path.join(BASE_DIR, "config", "courses.json"),
    "AD_CONFIG": os.path.join(BASE_DIR, "config", "ad_config.json"),
    "BONUSES": os.path.join(BASE_DIR, "config", "bonuses.json"),
    "PAYMENT_INFO": os.path.join(BASE_DIR, "config", "payment_info.json"),
    "DELAY_MESSAGES": os.path.join(BASE_DIR, "config", "delay_messages.txt"),
}

CONFIG_FILES = {
    "TARIFFS": "tariffs.json",
    "COURSES": "courses.json",
    "AD_CONFIG": "ad_config.json",
    "BONUSES": "bonuses.json",
    "PAYMENT_INFO": "payment_info.json",
    "DELAY_MESSAGES": "delay_messages.txt",
}

# Database Settings
DB_FILE = os.path.join(BASE_DIR, "bot_database.db")

# Business Logic
TOKEN_TO_RUB_RATE = 100
MAX_TOKENS_PER_DAY = 1000
DEFAULT_TOKENS = 100

# Message Delays
MIN_DELAY_BETWEEN_MESSAGES = 1  # seconds
MAX_DELAY_BETWEEN_MESSAGES = 3600  # 1 hour

# Course Types
COURSE_TYPES = {
    "MAIN": "main",
    "AUXILIARY": "auxiliary",
    "PREMIUM": "premium"
}

# Chat Links
COMMUNITY_CHAT_URL = "https://t.me/+PZM8JZ93eewzZWNi"

# Regular Expressions
DELAY_PATTERN = r"_(\d+)(hour|min|m|h)(?:\.|$)"

# Define states as constants
(
    WAIT_FOR_NAME,
    WAIT_FOR_CODE,
    ACTIVE,
    COURSE_SETTINGS,
    WAIT_FOR_SUPPORT_TEXT,
    WAIT_FOR_SELFIE,
    WAIT_FOR_DESCRIPTION,
    WAIT_FOR_CHECK,
    WAIT_FOR_GIFT_USER_ID,
    WAIT_FOR_PHONE_NUMBER,
) = range(10)

# Logging Configuration
LOG_FILE = os.path.join(BASE_DIR, "bot.log")
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

# Reminder Settings
REMINDER_INTERVALS = {
    "morning": "09:00",
    "evening": "20:00"
}

# Job Queue Settings
JOB_QUEUE_FIRST_RUN = 10.0  # seconds
JOB_QUEUE_INTERVAL = timedelta(minutes=1)

# File Extensions
ALLOWED_LESSON_EXTENSIONS = ['.md', '.html', '.txt']
ALLOWED_HOMEWORK_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.pdf', '.doc', '.docx']

# Default Values
DEFAULT_USER_NAME = 'ЧЕБУРАШКА'
DEFAULT_MIME_TYPE = 'application/octet-stream'