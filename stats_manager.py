import logging
from database import DatabaseConnection
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

logger = logging.getLogger(__name__)

class StatsManager:
    def __init__(self, admin_ids):
        self.db = DatabaseConnection()
        self.admin_ids = admin_ids

    def get_average_homework_time(self, user_id):
        """Calculate average time between homework submission and approval."""
        cursor = self.db.get_cursor()
        cursor.execute(
            """
            SELECT AVG((JULIANDAY(approval_time) - JULIANDAY(submission_time)) * 24 * 60 * 60)
            FROM homeworks
            WHERE user_id = ? AND status = 'approved'
            """,
            (user_id,),
        )
        result = cursor.fetchone()[0]

        logger.info(f"{result} - get_average_homework_time")

        if result:
            average_time_seconds = int(result)
            hours, remainder = divmod(average_time_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours} часов {minutes} минут"
        else:
            return "Нет данных"

    async def show_statistics(self, update, context: CallbackContext):
        """Shows statistics for administrator."""
        cursor = self.db.get_cursor()
        admin_id = update.effective_user.id

        # Check if the user is an admin
        if str(admin_id) not in self.admin_ids:
            await update.message.reply_text("У вас нет прав для выполнения этой команды.")
            return

        try:
            # Get total number of users
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]

            # Get number of active courses
            cursor.execute("SELECT COUNT(DISTINCT course_id) FROM user_courses")
            total_courses = cursor.fetchone()[0]

            # Format statistics message
            stats_message = (
                f"📊 Статистика:\n\n"
                f"👥 Пользователей: {total_users}\n"
                f"📚 Активных курсов: {total_courses}\n"
            )

            await update.message.reply_text(stats_message)

        except Exception as e:
            logger.error(f"Error showing statistics: {e}")
            await update.message.reply_text("Произошла ошибка при получении статистики.")

    async def get_homework_status_text(self, user_id, course_id):
        """Returns homework check status text."""
        cursor = self.db.get_cursor()

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

        if status == "pending":
            return f"Домашка к {lesson} уроку на самопроверке"
        elif status == "approved":
            return f"Домашка к {lesson} уроку принята"
        else:
            return "Статус домашки неизвестен странен и загадочен"

    async def show_token_statistics(self, update: Update, context: CallbackContext):
        """Shows token-related statistics for administrators."""
        if str(update.effective_user.id) not in self.admin_ids:
            return
            
        cursor = self.db.get_cursor()
        cursor.execute("""
            SELECT 
                COUNT(*) as total_transactions,
                SUM(CASE WHEN action = 'spend' THEN amount ELSE 0 END) as total_spent,
                SUM(CASE WHEN action = 'earn' THEN amount ELSE 0 END) as total_earned
            FROM transactions
        """)
        stats = cursor.fetchone()
        
        message = (
            "📊 Token Statistics:\n"
            f"Total Transactions: {stats[0]}\n"
            f"Total Tokens Spent: {abs(stats[1] or 0)}\n"
            f"Total Tokens Earned: {stats[2] or 0}"
        )
        await safe_reply(update, context, message)