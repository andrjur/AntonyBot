import logging
import re
from datetime import datetime
from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler
from database import DatabaseConnection
from utils import safe_reply

logger = logging.getLogger(__name__)

class ReminderManager:
    def __init__(self):
        self.db = DatabaseConnection()

    async def show_reminders(self, update: Update, context: CallbackContext):
        """Shows reminder settings."""
        user_id = update.effective_user.id
        cursor = self.db.get_cursor()
        
        cursor.execute(
            "SELECT morning_notification, evening_notification FROM user_settings WHERE user_id = ?",
            (user_id,)
        )
        settings = cursor.fetchone()
        
        if not settings:
            cursor.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
            self.db.get_connection().commit()
            settings = (None, None)

        morning, evening = settings
        text = "⏰ Настройка напоминаний:\n"
        text += f"🌅 Утреннее напоминание: {morning or 'не установлено'}\n"
        text += f"🌇 Вечернее напоминание: {evening or 'не установлено'}\n\n"
        text += "Чтобы установить или изменить время, используйте команды:\n"
        text += "/set_morning HH:MM — установить утреннее напоминание\n"
        text += "/set_evening HH:MM — установить вечернее напоминание\n"
        text += "/disable_reminders — отключить все напоминания"

        await safe_reply(update, context, text)

    async def set_reminder(self, update: Update, context: CallbackContext, reminder_type: str):
        """Sets morning or evening reminder."""
        user_id = update.effective_user.id
        try:
            time = context.args[0]
            if not re.match(r"^\d{2}:\d{2}$", time):
                raise ValueError
            
            column = f"{reminder_type}_notification"
            cursor = self.db.get_cursor()
            cursor.execute(
                f"UPDATE user_settings SET {column} = ? WHERE user_id = ?",
                (time, user_id)
            )
            self.db.get_connection().commit()

            emoji = "🌅" if reminder_type == "morning" else "🌇"
            message = f"{emoji} {reminder_type.capitalize()} напоминание установлено на {time}."
            await safe_reply(update, context, message)

        except (IndexError, ValueError):
            message = "Неверный формат времени. Используйте формат HH:MM."
            await safe_reply(update, context, message)

    async def disable_reminders(self, update: Update, context: CallbackContext):
        """Disables all reminders."""
        user_id = update.effective_user.id
        cursor = self.db.get_cursor()
        
        cursor.execute(
            """
            UPDATE user_settings
            SET morning_notification = NULL, evening_notification = NULL
            WHERE user_id = ?
            """,
            (user_id,)
        )
        self.db.get_connection().commit()
        await safe_reply(update, context, "Напоминания отключены.")

    async def send_reminders(self, context: CallbackContext):
        """Sends scheduled reminders to users."""
        now = datetime.now().strftime("%H:%M")
        cursor = self.db.get_cursor()
        
        cursor.execute("SELECT user_id, morning_notification, evening_notification FROM user_settings")
        for user_id, morning, evening in cursor.fetchall():
            if morning and now == morning:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🌅 Доброе утро! Посмотрите материалы курса."
                )
            if evening and now == evening:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🌇 Добрый вечер! Выполните домашнее задание."
                )