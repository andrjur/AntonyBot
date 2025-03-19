import os
from datetime import timedelta

# Bot Configuration
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", 0))
ADMIN_IDS = [int(id_) for id_ in os.getenv("ADMIN_IDS", "").split(",") if id_]

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


# Conversation States
CONVERSATION_STATES = {
    "WAIT_FOR_NAME": 1,
    "WAIT_FOR_CODE": 2,
    "ACTIVE": 3,
    "WAIT_FOR_SUPPORT": 4,
    "WAIT_FOR_PAYMENT": 5
}

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