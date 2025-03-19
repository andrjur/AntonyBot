import logging
import os
import asyncio
import random
from datetime import datetime
from telegram import Update, ParseMode
from telegram.ext import CallbackContext
from telegram.error import TelegramError
from database import DatabaseConnection
from utils import handle_telegram_errors
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

class Course:
    def __init__(self, course_id, course_name, course_type, code_word, price_rub=None, price_tokens=None):
        self.course_id = course_id
        self.course_name = course_name
        self.course_type = course_type
        self.code_word = code_word

        # Extract tariff from course_id
        self.tariff = course_id.split('_')[1] if '_' in course_id else 'default'
        self.price_rub = price_rub
        self.price_tokens = price_tokens

    def __str__(self):
        return f"Course(id={self.course_id}, name={self.course_name}, type={self.course_type}, code={self.code_word}, price_rub={self.price_rub}, price_tokens={self.price_tokens})"



class CourseManager:
    def __init__(self):
        self.db = DatabaseConnection()
        self.DEFAULT_LESSON_DELAY_HOURS = 24
        self.DEFAULT_LESSON_INTERVAL = 24
        self.ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
        self.stats_manager = None  # Will be set after initialization
        self.admin_manager = None  # Will be set after initialization

    async def handle_homework(self, update: Update, context: CallbackContext):
        """Handles homework submission."""
        user_id = update.effective_user.id
        logger.info(f"Handling homework from user {user_id}")

        # Check file type
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            file_type = "photo"
        elif update.message.document and update.message.document.mime_type.startswith("image/"):
            file_id = update.message.document.file_id
            file_type = "document"
        else:
            await update.message.reply_text("⚠️ Please send a picture or photo.")
            return

        cursor = self.db.get_cursor()
        # Get active course
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await update.message.reply_text("Please activate a course first.")
            return

        active_course_id_full = active_course_data[0]
        await self._process_homework_submission(update, context, user_id, active_course_id, file_id, file_type)

    async def course_management(self, update: Update, context: CallbackContext):
        """Course management menu."""
        cursor = self.db.get_cursor()
        user_id = update.effective_user.id
        logger.info(f"Course management menu accessed by user {user_id}")

        cursor.execute(
            "SELECT active_course_id FROM users WHERE user_id = ?",
            (user_id,)
        )
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await update.message.reply_text("У вас не активирован ни один курс.")
            return

        keyboard = [
            [InlineKeyboardButton("Сменить $$$ тариф", callback_data="change_tariff")],
            [InlineKeyboardButton("Мои курсы", callback_data="my_courses")],
            [InlineKeyboardButton("История ДЗ", callback_data="hw_history")],
        ]
        await update.message.reply_text(
            "Управление курсом:", 
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def get_current_lesson(self, update: Update, context: CallbackContext):
        """Gets current lesson for user."""
        user_id = update.effective_user.id
        cursor = self.db.get_cursor()
        
        cursor.execute(
            "SELECT active_course_id FROM users WHERE user_id = ?",
            (user_id,)
        )
        course_data = cursor.fetchone()
        
        if not course_data:
            await safe_reply(update, context, "Курс не найден.")
            return

        active_course_id = course_data[0]
        return await self.format_progress(user_id, active_course_id)

    async def calculate_time_to_next_lesson(self, user_id, active_course_id_full):
        """Calculates time remaining until next lesson."""
        cursor = self.db.get_cursor()
        logger.info("calculate_time_to_next_lesson")
        
        cursor.execute(
            """
            SELECT submission_time FROM homeworks
            WHERE user_id = ? AND course_id = ?
            ORDER BY submission_time DESC
            LIMIT 1
            """,
            (user_id, active_course_id_full)
        )
        last_submission_data = cursor.fetchone()

        if not last_submission_data:
            next_lesson_time = datetime.now() + timedelta(hours=self.DEFAULT_LESSON_INTERVAL)
            return next_lesson_time - datetime.now()

        last_submission_time = datetime.strptime(last_submission_data[0], "%Y-%m-%d %H:%M:%S")
        next_lesson_time = last_submission_time + timedelta(hours=self.DEFAULT_LESSON_INTERVAL)
        return next_lesson_time - datetime.now()

    # Remove duplicate format_progress method and keep the complete version

    async def show_lesson(self, update: Update, context: CallbackContext):
        """Shows lesson text and materials."""
        user_id = update.effective_user.id
        logger.info(f"show_lesson {user_id} - Current state")

        cursor = self.db.get_cursor()  # Use class's db connection
        try:
            # Получаем active_course_id из users
            cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
            active_course_data = cursor.fetchone()

            if not active_course_data or not active_course_data[0]:
                await safe_reply(update, context, "Активируйте курс через кодовое слово.")
                return

            active_course_id_full = active_course_data[0]
            active_course_id = active_course_id_full.split("_")[0]
            logger.info(f"active_course_id {active_course_id} +")

            # Получаем progress (номер урока) из user_courses
            cursor.execute(
                "SELECT progress FROM user_courses WHERE user_id = ? AND course_id = ?",
                (user_id, active_course_id_full),
            )
            progress_data = cursor.fetchone()

            lesson = progress_data[0] if progress_data else 1
            if not progress_data:
                await safe_reply(update, context, "Начинаем с первого урока.")

            # 1. Отправляем текст урока
            lesson_text = get_lesson_text(lesson, active_course_id)
            if lesson_text:
                await safe_reply(update, context, lesson_text)
            else:
                await safe_reply(update, context, "Текст урока не найден.")
                return  # Выходим из функции, если текст урока не найден

            # 2. Отправляем файлы урока (аудио, видео, изображения)
            lesson_files = get_lesson_files(user_id, lesson, active_course_id)
            if lesson_files:
                for file_info in lesson_files:
                    file_path = file_info["path"]
                    delay = file_info["delay"]
                    file_type = file_info["type"]

                    if delay > 0:
                        logger.info(f"на  {file_path} задержка {delay}  asyncio.sleep ===============================")
                        await asyncio.sleep(delay)

                    try:
                        with open(file_path, "rb") as file:
                            if file_type == "photo":
                                await context.bot.send_photo(chat_id=user_id, photo=file, caption=f"Фото к уроку {lesson}")
                            elif file_type == "audio":
                                await context.bot.send_audio(chat_id=user_id, audio=file, caption=f"Аудио к уроку {lesson}")
                            elif file_type == "video":
                                await context.bot.send_video(chat_id=user_id, video=file, caption=f"Видео к уроку {lesson}")
                            elif file_type == "document":
                                await context.bot.send_document(chat_id=user_id, document=file,
                                                                caption=f"Документ к уроку {lesson}")
                            else:
                                logger.warning(f"Неизвестный тип файла: {file_type}, {file_path}")

                    except FileNotFoundError as e:
                        logger.error(f"Файл не найден: {file_path} - {e}")
                        await safe_reply(update, context, f"Файл {os.path.basename(file_path)} не найден.")
                    except TelegramError as e:
                        logger.error(f"Ошибка при отправке файла {file_path}: {e}")
                        await safe_reply(update, context,
                                        f"Произошла ошибка при отправке файла {os.path.basename(file_path)}.")
                    except Exception as e:
                        logger.error(f"Неожиданная ошибка при отправке файла {file_path}: {e}")
                        await safe_reply(update, context,
                                        f"Произошла непредвиденная ошибка при отправке файла {os.path.basename(file_path)}.")

            else:
                await safe_reply(update, context, "Файлы к этому уроку не найдены.")

            await show_main_menu (update, context)  # Показываем меню, даже если файлов нет
            homework_status = await get_homework_status_text(user_id, active_course_id_full)
            await safe_reply(update, context, f"Напоминаем: {homework_status}")

        except Exception as e:  # это часть show_lesson
            logger.error(f"Ошибка при получении материалов урока: {e}")
            await safe_reply(update, context, "Ошибка при получении материалов урока. Попробуйте позже.")

    def get_available_lessons(self, course_id):
        """Get all existing lessons by course."""
        lesson_dir = f"courses/{course_id}/"
        lessons = [
            int(f.replace("lesson", "").replace(".txt", ""))
            for f in os.listdir(lesson_dir)
            if f.startswith("lesson") and f.endswith(".txt")
        ]
        lessons.sort()
        return lessons

    def generate_lesson_keyboard(self, lessons, items_per_page=10):
        """Generate buttons with page"""
        keyboard = []
        for lesson in lessons:
            keyboard.append([InlineKeyboardButton(f"Lesson {lesson}", callback_data=f"lesson_{lesson}")])
        return keyboard

    async def course_completion_actions(self, update: Update, context: CallbackContext):
        """Actions to perform upon course completion."""
        user_id = update.effective_user.id
        logger.info(f"course_completion_actions {user_id}")
        
        cursor = self.db.get_cursor()
        
        # Get active_course_id from user
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
        active_course_data = cursor.fetchone()
        active_course_id_full = active_course_data[0]
        
        # Inform user
        await update.message.reply_text("Congratulations, you have finished the course")

        if self.stats_manager:
            await self.stats_manager.show_statistics(update, context)

        # Update to aux
        cursor.execute(
            """
            UPDATE user_courses
            SET course_type = 'auxiliary'
            WHERE user_id = ? AND course_id = ?
            """,
            (user_id, active_course_id_full)
        )
        self.db.get_connection().commit()

        # End homeworks
        cursor.execute(
            """
            DELETE FROM homeworks
            WHERE user_id = ? AND course_id = ?
            """,
            (user_id, active_course_id_full)
        )
        self.db.get_connection().commit()

        # Generate button to watch every lesson
        available_lessons = self.get_available_lessons(active_course_id_full)
        keyboard = self.generate_lesson_keyboard(available_lessons)
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text("All finished.", reply_markup=reply_markup)


    # домашка ???
    async def get_homework_status_text(self, user_id, course_id):
        """Возвращает текст статуса проверки домашнего задания."""
        db = DatabaseConnection()
        conn = db.get_connection()
        cursor = db.get_cursor()

        # Проверяем статус домашнего задания
        cursor.execute(
            """
            SELECT hw_id, lesson, status
            FROM homeworks
            WHERE user_id = ? AND course_id = ?
            ORDER BY lesson DESC LIMIT 1
        """,
            (user_id, course_id),
        )
        homework_data = cursor.fetchone()

        if not homework_data:
            # Если домашки еще не отправлялись
            cursor.execute(
                """
                SELECT progress
                FROM user_courses
                WHERE user_id = ? AND course_id = ?
            """,
                (user_id, course_id),
            )
            progress_data = cursor.fetchone()
            if progress_data:
                lesson = progress_data[0]
                return f"Жду домашку к {lesson} уроку"
            else:
                return "Информация о прогрессе недоступна"

        hw_id, lesson, status = homework_data

        # Формируем текст в зависимости от статуса
        if status == "pending":
            return f"Домашка к {lesson} уроку на самопроверке"
        elif status == "approved":
            return f"Домашка к {lesson} уроку принята"
        else:
            return "Статус домашки неизвестен странен и загадочен"

    
    # вычисляем время следующего урока *
    async def update_next_lesson_time(self, user_id, course_id):
        """Обновляет время следующего урока для пользователя."""
        db = DatabaseConnection()
        conn = db.get_connection()
        cursor = db.get_cursor()

        try:
            # Получаем текущее время
            now = datetime.now()

            # Вычисляем время следующего урока
            next_lesson_time = now + timedelta(hours=DEFAULT_LESSON_DELAY_HOURS)
            next_lesson_time_str = next_lesson_time.strftime("%Y-%m-%d %H:%M:%S")

            # Обновляем время в базе данных
            cursor.execute(
                """
                UPDATE users 
                SET next_lesson_time = ? 
                WHERE user_id = ?
            """,
                (next_lesson_time_str, user_id),
            )
            conn.commit()

            logger.info(f"Для пользователя {user_id} установлено время следующего урока: {next_lesson_time_str}")

        except Exception as e:
            logger.error(f"Ошибка при обновлении времени следующего урока: {e}")

        # Qwen 15 марта Замена get_lesson_after_code
    async def get_lesson_after_code(self, update: Update, context: CallbackContext, course_type: str):
        db = DatabaseConnection()
        conn = db.get_connection()
        cursor = db.get_cursor()

        user = update.effective_user
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user.id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await update.message.reply_text("Пожалуйста, активируйте курс.")
            return

        active_course_id_full = active_course_data[0]
        cursor.execute(
            """
            SELECT progress
            FROM user_courses
            WHERE user_id = ? AND course_id = ?
        """,
            (user.id, active_course_id_full),
        )
        progress_data = cursor.fetchone()

        lesson_number = 1 if not progress_data else progress_data[0]
        await process_lesson(user.id, lesson_number, active_course_id_full.split("_")[0], context)

        #  Qwen 15  Замена send_lesson_by_timer
    async def send_lesson_by_timer(self,  user_id: int, context: CallbackContext):
        """Send lesson to users by timer."""
        db = DatabaseConnection()
        conn = db.get_connection()
        cursor = db.get_cursor()
        logger.info(f"Sending lesson to user {user_id} at {datetime.now()}")

        # Get active_course_id and progress
        cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
        active_course_data = cursor.fetchone()

        if not active_course_data or not active_course_data[0]:
            await context.bot.send_message(chat_id=user_id, text="Пожалуйста, активируйте курс.")
            return

        active_course_id_full = active_course_data[0]
        cursor.execute(
            """
            SELECT progress
            FROM user_courses
            WHERE user_id = ? AND course_id = ?
        """,
            (user_id, active_course_id_full),
        )
        progress_data = cursor.fetchone()

        if not progress_data:
            await context.bot.send_message(chat_id=user_id, text="Не найден прогресс курса.")
            return

        lesson = progress_data[0]

        # Update lesson_sent_time in the database
        lesson_sent_time = datetime.now()
        cursor.execute(
            """
            INSERT INTO homeworks (user_id, course_id, lesson, lesson_sent_time)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, course_id, lesson) DO UPDATE SET lesson_sent_time = excluded.lesson_sent_time
        """,
            (user_id, active_course_id_full, lesson, lesson_sent_time),
        )
        conn.commit()

        # Process the lesson
        await process_lesson(user_id, lesson, active_course_id_full.split("_")[0], context)

        # Add admin approval buttons
        if self.admin_manager and user_id in self.admin_manager.admin_ids:
            keyboard = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"hw_approve_{hw_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"hw_reject_{hw_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Admin: Approve or reject homework?", reply_markup=reply_markup)

