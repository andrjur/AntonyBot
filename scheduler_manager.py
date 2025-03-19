import logging
from database import DatabaseConnection
from telegram.ext import CallbackContext
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

class SchedulerManager:
    def __init__(self):
        self.db = DatabaseConnection()

    def add_user_to_scheduler(self, user_id: int, time2: datetime, context: CallbackContext, scheduler):
        """Add user to send_lesson_by_timer with specific time."""
        try:
            scheduler.add_job(
                send_lesson_by_timer,
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