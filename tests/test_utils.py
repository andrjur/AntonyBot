import unittest
from datetime import date
from unittest.mock import MagicMock, patch
from telegram import Update, InlineKeyboardMarkup, User, Message, Chat, CallbackQuery
from telegram.ext import CallbackContext
from telegram.error import TelegramError
import logging
import re
import os
import mimetypes
from io import BytesIO  # Import BytesIO for in-memory file handling
import sys
import os

# Добавьте путь к корневой директории проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Assuming your utils.py is in the same directory as your test
from utils import (
    safe_reply,
    handle_telegram_errors,
    is_admin,
    escape_markdown_v2,
    parse_delay_from_filename,
    send_file,
    get_date,
    format_date,
    get_ad_message,
    maybe_add_ad
)
from database import DatabaseConnection, load_ad_config, load_courses, load_bonuses

# Mocking the logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock constants
DELAY_PATTERN = re.compile(r"_(\d+)(hour|min|m|h)(?:\.|$)")

# Mock DatabaseConnection and related methods
class MockDatabaseConnection:
    def __init__(self):
        self.cursor = MagicMock()
        self.connection = MagicMock()

    def get_connection(self):
        return self.connection

    def get_cursor(self):
        return self.cursor

# Mock load_courses, load_bonuses, and load_ad_config
def mock_load_courses():
    return [
        {"course_name": "Test Course 1", "bonus_price": 100},
        {"course_name": "Test Course 2"}
    ]

def mock_load_bonuses():
    return {"bonus_percentage": 0.2}

def mock_load_ad_config():
    return {"ad_percentage": 0.5}

# Patch these functions
@patch('utils.load_courses', side_effect=mock_load_courses)
@patch('utils.load_bonuses', side_effect=mock_load_bonuses)
@patch('utils.load_ad_config', side_effect=mock_load_ad_config)
class TestUtils(unittest.IsolatedAsyncioTestCase):  # Use IsolatedAsyncioTestCase

    async def asyncSetUp(self):
        """Set up method to create mock objects for testing."""
        self.mock_update = MagicMock(spec=Update)
        self.mock_context = MagicMock(spec=CallbackContext)
        self.mock_user = MagicMock(spec=User)
        self.mock_chat = MagicMock(spec=Chat)
        self.mock_message = MagicMock(spec=Message)
        self.mock_callback_query = MagicMock(spec=CallbackQuery)

        # Set up basic attributes
        self.mock_update.effective_user = self.mock_user
        self.mock_update.effective_chat = self.mock_chat
        self.mock_update.effective_message = self.mock_message
        self.mock_user.id = 12345
        self.mock_chat.id = 54321

        # Set up bot attribute for mock_context
        self.mock_context.bot = MagicMock()
        self.mock_context.user_data = {}

    async def test_safe_reply_new_message(self):
        await safe_reply(self.mock_update, self.mock_context, "Test message")
        self.mock_context.bot.send_message.assert_called_once_with(chat_id=54321, text="Test message", reply_markup=None)

    async def test_safe_reply_callback_query_with_message(self):
        # Simulate a callback query with a message
        self.mock_update.callback_query = self.mock_callback_query
        self.mock_callback_query.message = self.mock_message

        await safe_reply(self.mock_update, self.mock_context, "Test message")

        # Check that answer was called on the callback query
        self.mock_update.callback_query.answer.assert_called_once()

        # Check that reply_text was called on the message
        self.mock_update.callback_query.message.reply_text.assert_called_once_with("Test message", reply_markup=None)

        # Reset callback_query.message for other tests
        self.mock_update.callback_query.message = None

    @patch('utils.DatabaseConnection', return_value=MockDatabaseConnection())
    def test_is_admin(self, MockDatabaseConnection):
        # Mocking the database connection and cursor
        mock_db = MockDatabaseConnection()
        mock_cursor = mock_db.get_cursor()
        mock_cursor.fetchone.return_value = (1,)  # Simulating an admin user

        result = is_admin(12345)
        self.assertTrue(result)

        mock_cursor.fetchone.return_value = None  # Simulating a non-admin user
        result = is_admin(54321)
        self.assertFalse(result)

    def test_escape_markdown_v2(self):
        test_string = r"*_[]()~`>#+-=|{}.!"
        escaped_string = escape_markdown_v2(test_string)
        self.assertEqual(escaped_string, r"\*\_\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!")

    def test_parse_delay_from_filename(self):
        self.assertEqual(parse_delay_from_filename("file_10m.txt"), 600)
        self.assertEqual(parse_delay_from_filename("file_1h.txt"), 3600)
        self.assertIsNone(parse_delay_from_filename("file.txt"))

    @patch('os.path.exists', return_value=True)
    @patch('mimetypes.guess_type', return_value=('image/jpeg', None))
    async def test_send_file_image(self, mock_guess_type, mock_exists):
        mock_bot = MagicMock()
        file_path = "path/to/image.jpg"
        chat_id = 12345
        file_name = "image.jpg"

        # Create a dummy file for testing
        with patch("builtins.open", return_value=BytesIO(b"test data")):
            await send_file(mock_bot, chat_id, file_path, file_name)

        # Assert that send_photo was called with the correct arguments
        mock_bot.send_photo.assert_called_once()
        args, kwargs = mock_bot.send_photo.call_args
        self.assertEqual(args[0], chat_id)
        self.assertIsInstance(kwargs['photo'], BytesIO)

    def test_get_date(self):
        self.assertEqual(get_date("2025-03-21"), date(2025, 3, 21))
        self.assertIsNone(get_date("invalid-date"))

    def test_format_date(self):
        test_date = date(2025, 3, 21)
        self.assertEqual(format_date(test_date), "2025-03-21")

    def test_get_ad_message(self, mock_load_ad_config, mock_load_bonuses, mock_load_courses):
        # Test when there are courses with bonus prices
        courses_with_bonus = [{"course_name": "Bonus Course", "bonus_price": 50}]
        mock_load_courses.return_value = courses_with_bonus
        ad_message = get_ad_message()
        self.assertIn("Хотите больше контента?", ad_message)
        self.assertIn("Курс 'Bonus Course'", ad_message)

        # Test when there are no courses with bonus prices
        mock_load_courses.return_value = [{"course_name": "Regular Course"}]
        ad_message = get_ad_message()
        self.assertEqual(ad_message, "У нас много интересного! Узнайте больше о доступных курсах и возможностях.")

    def test_maybe_add_ad(self, mock_load_ad_config, mock_load_bonuses, mock_load_courses):
        message_list = ["Message 1", "Message 2"]
        mock_load_ad_config.return_value = {"ad_percentage": 1.0}  # Always add ad
        ad_message = "Ad message"
        with patch('utils.get_ad_message', return_value=ad_message):
            updated_list = maybe_add_ad(message_list)
        self.assertIn(ad_message, updated_list)

if __name__ == '__main__':
    unittest.main()
