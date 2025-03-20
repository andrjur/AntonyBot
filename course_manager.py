import logging
import os
import asyncio
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from telegram.constants import ParseMode

from constants import (
    DEFAULT_LESSON_INTERVAL,
)
from utils import safe_reply, handle_telegram_errors
from lessons import get_lesson_text, get_lesson_files
from database import load_delay_messages, DELAY_MESSAGES_FILE  # Add this import

logger = logging.getLogger(__name__)

# Load delay messages at module level
DELAY_MESSAGES = load_delay_messages(DELAY_MESSAGES_FILE)

class Course:
    def __init__(self, course_id, course_name, course_type, code_word, price_rub=None, price_tokens=None):
        self.course_id = course_id
        self.course_name = course_name
        self.course_type = course_type
        self.code_word = code_word
        self.tariff = course_id.split('_')[1] if '_' in course_id else 'default'
        self.price_rub = price_rub
        self.price_tokens = price_tokens

    def __str__(self):
        return f"Course(id={self.course_id}, name={self.course_name}, type={self.course_type}, code={self.code_word}, price_rub={self.price_rub}, price_tokens={self.price_tokens})"

class CourseManager:
    def __init__(self):
        self.token_manager = None
        self.stats_manager = None

    @handle_telegram_errors
    async def get_current_lesson(self, update: Update, context: CallbackContext):
        """Отправляет все материалы текущего урока."""
        user_id = update.effective_user.id
        logger.info(f"get_current_lesson: user_id={user_id}")

        try:
            # Get active_course_id from users
            cursor = context.bot_data['db'].cursor()
            cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
            active_course_data = cursor.fetchone()

            if not active_course_data or not active_course_data[0]:
                await safe_reply(update, context, "Активируйте курс через кодовое слово.")
                return

            active_course_id_full = active_course_data[0]
            active_course_id = active_course_id_full.split("_")[0]
            logger.info(f"active_course_id: {active_course_id}")

            # Get progress from user_courses
            cursor.execute(
                "SELECT progress FROM user_courses WHERE user_id = ? AND course_id = ?",
                (user_id, active_course_id_full),
            )
            progress_data = cursor.fetchone()

            # If no progress found, start with lesson 1
            if not progress_data:
                lesson = 1
                cursor.execute(
                    "INSERT INTO user_courses (user_id, course_id, course_type, progress, tariff) VALUES (?, ?, ?, ?, ?)",
                    (user_id, active_course_id_full, context.user_data.get("course_type", "main"), lesson, context.user_data.get("tariff", "self_check")),
                )
                await context.bot_data['db'].commit()
                await safe_reply(update, context, "Вы начинаете курс с первого урока.")
            else:
                lesson = progress_data[0]

            await self.process_lesson(user_id, lesson, active_course_id, context)

            # Calculate next lesson time
            next_lesson = lesson + 1
            next_lesson_release_time = datetime.now() + timedelta(hours=DEFAULT_LESSON_INTERVAL)
            next_lesson_release_str = next_lesson_release_time.strftime("%d-%m-%Y %H:%M:%S")
            await safe_reply(
                update, 
                context,
                f"Следующий урок {next_lesson} будет доступен {next_lesson_release_str}."
            )

        except Exception as e:
            logger.error(f"Ошибка при получении текущего урока: {e}")
            await safe_reply(update, context, "Ошибка при получении текущего урока. Попробуйте позже.")

    async def process_lesson(self, user_id, lesson_number, active_course_id, context):
        """Обрабатывает текст урока и отправляет связанные файлы."""
        try:
            # Get lesson text
            lesson_data = get_lesson_text(lesson_number, active_course_id)
            if lesson_data:
                lesson_text, parse_mode = lesson_data
                try:
                    await context.bot.send_message(
                        chat_id=user_id, 
                        text=lesson_text, 
                        parse_mode=parse_mode
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке текста урока: {e}")
                    await context.bot.send_message(
                        chat_id=user_id, 
                        text="Ошибка при отправке текста урока."
                    )
            else:
                await context.bot.send_message(
                    chat_id=user_id, 
                    text="Текст урока не найден."
                )

            # Get and send lesson files
            lesson_files = get_lesson_files(user_id, lesson_number, active_course_id)
            tasks = [self.send_file(file_info, user_id, context) for file_info in lesson_files]
            await asyncio.gather(*tasks)

        except Exception as e:
            logger.error(f"Ошибка при обработке урока: {e}")
            await context.bot.send_message(
                chat_id=user_id, 
                text="Произошла ошибка при обработке урока."
            )

    async def send_file(self, file_info, user_id, context):
        """Отправляет файл с учетом задержки."""
        file_path = file_info["path"]
        file_type = file_info["type"]
        delay = file_info["delay"]

        try:
            if delay > 0:
                delay_message = random.choice(DELAY_MESSAGES)
                logger.info(f"Ожидание {delay} секунд перед отправкой файла {file_path}")
                await context.bot.send_message(chat_id=user_id, text=delay_message)
                await asyncio.sleep(delay)

            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Файл не найден: {file_path}")

            with open(file_path, "rb") as file:
                if file_type == "photo":
                    await context.bot.send_photo(chat_id=user_id, photo=file)
                elif file_type == "video":
                    await context.bot.send_video(chat_id=user_id, video=file)
                elif file_type == "audio":
                    await context.bot.send_audio(chat_id=user_id, audio=file)
                else:
                    await context.bot.send_document(chat_id=user_id, document=file)

        except FileNotFoundError:
            logger.error(f"Файл не найден: {file_path}")
            await context.bot.send_message(
                chat_id=user_id, 
                text=f"Файл не найден: {file_path}"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке файла {file_path}: {e}")
            await context.bot.send_message(
                chat_id=user_id, 
                text=f"Ошибка при отправке файла: {e}"
            )

    async def handle_homework(self, update: Update, context: CallbackContext):
        """Handles homework submission."""
        # TODO: Implement homework handling logic
        pass

    async def handle_course_callback(self, update: Update, context: CallbackContext):
        """Handles course-related callback queries."""
        # TODO: Implement callback handling logic
        pass

    async def course_management(self, update: Update, context: CallbackContext):
        """Handles course management commands."""
        # TODO: Implement course management logic
        pass

course_manager = CourseManager()
