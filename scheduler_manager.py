import logging
import sqlite3

from course_manager import CourseManager
from database import DatabaseConnection
from telegram.ext import CallbackContext
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

class SchedulerManager:
    def __init__(self, db):
        self.db = db

    #  Qwen 15  Замена send_lesson_by_timer
    async def send_lesson_by_timer(self, conn: sqlite3.Connection, cursor: sqlite3.Cursor, user_id: int,
                                   context: CallbackContext):
        """Send lesson to users by timer."""
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
        await CourseManager.process_lesson(self, user_id, lesson, active_course_id_full.split("_")[0], context)

    def add_user_to_scheduler(self, user_id: int, time2: datetime, context: CallbackContext, scheduler):
        """Add user to send_lesson_by_timer with specific time."""
        try:
            scheduler.add_job(
                SchedulerManager.send_lesson_by_timer,
                trigger="cron",
                hour=time2.hour,
                minute=time2.minute,
                start_date=datetime.now(),  # Fixed syntax error
                kwargs={"user_id": user_id, "context": context},
                id=f"lesson_{user_id}",
                )
        except Exception as e:
            logging.error(f"send_lesson_by_timer failed. {e}------------<<")

        # Move add_user_to_scheduler function here