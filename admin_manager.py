import logging
from telegram import Update
from telegram.ext import CallbackContext
from database import DatabaseConnection
from utils import safe_reply

logger = logging.getLogger(__name__)

class AdminManager:
    def __init__(self, admin_ids):
        self.admin_ids = admin_ids
        self.db = DatabaseConnection()

    async def save_admin_comment(self, update: Update, context: CallbackContext):
        """Saves admin comment and updates homework status."""
        user_id = update.effective_user.id
        cursor = self.db.get_cursor()

        # Check if user is admin
        cursor.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (user_id,))
        if not cursor.fetchone():
            logger.info(f"Non-admin attempt to use admin command: {user_id}")
            await safe_reply(update, "⛔ Admin-only command")
            return

        try:
            # Handle both callback queries and direct messages
            if update.callback_query:
                hw_id = update.callback_query.data.split("_")[2]
                status = "rejected"
                comment = "Homework rejected"
            else:
                hw_id = context.user_data.get("awaiting_comment")
                status = context.user_data.pop("approval_status", None)
                comment = update.message.text

            if not hw_id or not status:
                await safe_reply(update, "Missing homework ID or status. Please try again.")
                return

            # Update homework status and comment
            cursor.execute(
                """
                UPDATE homeworks 
                SET status = ?, 
                    feedback = ?, 
                    approval_time = DATETIME('now'), 
                    admin_comment = ?
                WHERE hw_id = ?
                """,
                (status, comment, comment, hw_id)
            )

            # Get homework details for notification
            cursor.execute(
                "SELECT user_id, course_id, lesson FROM homeworks WHERE hw_id = ?",
                (hw_id,)
            )
            homework_data = cursor.fetchone()
            
            self.db.get_connection().commit()

            if homework_data:
                student_id, course_id, lesson = homework_data
                message = f"Your homework for lesson {lesson} was {status}."
                if comment:
                    message += f"\nComment: {comment}"
                await context.bot.send_message(chat_id=student_id, text=message)

            response = f"Homework {status}. Comment saved."
            if update.callback_query:
                await update.callback_query.answer(response)
            else:
                await safe_reply(update, response)

        except Exception as e:
            logger.error(f"Error in save_admin_comment: {e}")
            await safe_reply(update, "Error processing admin command")



