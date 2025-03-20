#menu_manager.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from database import DatabaseConnection
from utils import safe_reply
from constants import ADMIN_IDS
 
logger = logging.getLogger(__name__)

class MenuManager:
    def __init__(self):
        self.db = DatabaseConnection()

    async def show_main_menu(self, update: Update, context: CallbackContext):
        """Shows the main menu."""
        keyboard = [
            [InlineKeyboardButton("📚 Текущий урок", callback_data="get_current_lesson")],
            [InlineKeyboardButton("🖼 Галерея работ", callback_data="gallery")],
            [InlineKeyboardButton("💰 Тарифы", callback_data="tariffs")],
            [InlineKeyboardButton("⚙️ Настройки курса", callback_data="course_settings")],
            [InlineKeyboardButton("📊 Статистика", callback_data="statistics")],
            [InlineKeyboardButton("❓ Поддержка", callback_data="support")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_reply(update, context, "Главное меню:", reply_markup=reply_markup)

    async def info_command(self, update: Update, context: CallbackContext):
        """Shows bot information."""
        info_text = (
            "ℹ️ Информация о боте:\n\n"
            "Этот бот поможет вам в обучении и управлении курсами.\n"
            "Используйте /help для просмотра доступных команд."
        )
        await safe_reply(update, context, info_text)

    async def admins_command(self, update: Update, context: CallbackContext):
        """Shows admin contact information."""
        admin_text = "👨‍💼 Контакты администраторов:\n@admin1\n@admin2"
        await safe_reply(update, context, admin_text)

    async def reminders(self, update: Update, context: CallbackContext):
        """Shows reminder settings."""
        reminder_text = (
            "⏰ Настройки напоминаний:\n\n"
            "Используйте следующие команды:\n"
            "/set_morning - установить утреннее напоминание\n"
            "/set_evening - установить вечернее напоминание\n"
            "/disable_reminders - отключить напоминания"
        )
        await safe_reply(update, context, reminder_text)

    async def set_morning(self, update: Update, context: CallbackContext):
        """Sets morning reminder time."""
        # Implementation for setting morning reminder
        await safe_reply(update, context, "Утреннее напоминание установлено на 9:00")

    async def set_evening(self, update: Update, context: CallbackContext):
        """Sets evening reminder time."""
        # Implementation for setting evening reminder
        await safe_reply(update, context, "Вечернее напоминание установлено на 20:00")

    async def disable_reminders(self, update: Update, context: CallbackContext):
        """Disables all reminders."""
        # Implementation for disabling reminders
        await safe_reply(update, context, "Все напоминания отключены")

    async def show_course_settings(self, update: Update, context: CallbackContext):
        """Shows course settings menu."""
        keyboard = [
            [InlineKeyboardButton("🔔 Напоминания", callback_data="reminders")],
            [InlineKeyboardButton("📱 Уведомления", callback_data="notifications")],
            [InlineKeyboardButton("Назад", callback_data="menu_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_reply(update, context, "⚙️ Настройки курса:", reply_markup=reply_markup)

    async def show_statistics(self, update: Update, context: CallbackContext):
        """Shows user statistics."""
        user_id = update.effective_user.id
        cursor = self.db.get_cursor()
        
        try:
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_homeworks,
                    SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved_homeworks,
                    coins,
                    trust_credit
                FROM homeworks h
                JOIN users u ON h.user_id = u.user_id
                WHERE h.user_id = ?
                GROUP BY h.user_id
            """, (user_id,))
            
            stats = cursor.fetchone()
            if stats:
                total_hw, approved_hw, coins, trust = stats
                message = (
                    "📊 Ваша статистика:\n\n"
                    f"📚 Всего домашних работ: {total_hw}\n"
                    f"✅ Одобрено работ: {approved_hw}\n"
                    f"💰 Монет: {coins}\n"
                    f"⭐️ Уровень доверия: {trust}"
                )
            else:
                message = "У вас пока нет статистики."
                
            await safe_reply(update, context, message)
            
        except Exception as e:
            logger.error(f"Error showing statistics: {e}")
            await safe_reply(update, context, "Произошла ошибка при загрузке статистики.")

    async def build_admin_homework_keyboard(self, hw_id: int):
        """Creates keyboard for homework approval."""
        keyboard = [
            [InlineKeyboardButton("✅ Просто одобрить", callback_data=f"approve_hw_{hw_id}")],
            [
                InlineKeyboardButton(f"✅ +1 🥉", callback_data=f"approve_hw_{hw_id}_reward_1"),
                InlineKeyboardButton(f"✅ +2 🥉", callback_data=f"approve_hw_{hw_id}_reward_2"),
                InlineKeyboardButton(f"✅ +3 🥉", callback_data=f"approve_hw_{hw_id}_reward_3")
            ],
            [InlineKeyboardButton(f"✅ +10 🥈", callback_data=f"approve_hw_{hw_id}_reward_10")],
            [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_hw_{hw_id}")],
            [InlineKeyboardButton("📝 Добавить комментарий", callback_data=f"feedback_hw_{hw_id}")]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def handle_homework_actions(self, update: Update, context: CallbackContext):
        """Handles admin actions with homework (approval, rejection, rewards)."""
        query = update.callback_query
        await query.answer()
        data = query.data

        if data.startswith("approve_hw_") or data.startswith("reject_hw_"):
            parts = data.split("_")
            hw_id = int(parts[2])
            reward_amount = 0

            if len(parts) > 3 and parts[3] == "reward":
                reward_amount = int(parts[4])

            if data.startswith("approve_hw_"):
                await self.approve_homework(update, context, hw_id, reward_amount)
            elif data.startswith("reject_hw_"):
                await self.reject_homework(update, context, hw_id)
        elif data.startswith("feedback_hw_"):
            hw_id = data.split("_")[2]
            context.user_data['awaiting_feedback_for'] = hw_id
            await query.message.reply_text("Введите ваш комментарий к домашнему заданию:")
            return "WAIT_FOR_HOMEWORK_FEEDBACK"
        else:
            await safe_reply(update, context, "Unknown command.")

    async def approve_homework(self, update: Update, context: CallbackContext, hw_id: int, reward_amount: int = 0):
        """Approves homework with optional reward."""
        cursor = self.db.get_cursor()
        conn = self.db.get_connection()

        try:
            cursor.execute("""
                SELECT user_id, lesson, course_id 
                FROM homeworks 
                WHERE hw_id = ? AND status = 'pending'
            """, (hw_id,))
            homework_data = cursor.fetchone()

            if not homework_data:
                await safe_reply(update, context, "Домашнее задание не найдено или уже проверено.")
                return

            user_id, lesson, course_id = homework_data

            cursor.execute("""
                UPDATE homeworks 
                SET status = 'approved', 
                    approval_time = strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'),
                    reward_amount = ?
                WHERE hw_id = ?
            """, (reward_amount, hw_id))
            conn.commit()

            # Notify admin
            reward_text = f" с наградой {reward_amount} 🥉" if reward_amount > 0 else ""
            admin_message = f"✅ Домашнее задание пользователя {user_id} (урок {lesson}){reward_text} одобрено."
            await safe_reply(update, context, admin_message)

            # Notify user
            user_message = f"Поздравляем! Ваше задание по курсу {course_id} (урок {lesson}) принято администратором."
            if reward_amount > 0:
                user_message += f"\nВы получаете {reward_amount} 🥉 за отличную работу!"
            await context.bot.send_message(chat_id=user_id, text=user_message)

        except Exception as e:
            logger.error(f"Error in approve_homework: {e}")
            await safe_reply(update, context, "Произошла ошибка при проверке домашнего задания.")

    async def reject_homework(self, update: Update, context: CallbackContext, hw_id: int):
        """Rejects homework."""
        cursor = self.db.get_cursor()
        conn = self.db.get_connection()

        try:
            cursor.execute("""
                UPDATE homeworks 
                SET status = 'rejected',
                    rejection_time = strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')
                WHERE hw_id = ?
                RETURNING user_id, lesson, course_id
            """, (hw_id,))
            result = cursor.fetchone()
            conn.commit()

            if result:
                user_id, lesson, course_id = result
                await safe_reply(update, context, f"Домашнее задание {hw_id} отклонено.")
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Ваше домашнее задание по курсу {course_id} (урок {lesson}) отклонено. Пожалуйста, проверьте комментарии и отправьте работу повторно."
                )
            else:
                await safe_reply(update, context, "Домашнее задание не найдено.")

        except Exception as e:
            logger.error(f"Error in reject_homework: {e}")
            await safe_reply(update, context, "Произошла ошибка при отклонении домашнего задания.")

    async def send_homework_feedback(self, update: Update, context: CallbackContext):
        """Sends feedback for homework."""
        hw_id = context.user_data.get('awaiting_feedback_for')
        if not hw_id:
            await safe_reply(update, context, "Ошибка: не найдено домашнее задание для отправки комментария.")
            return

        feedback = update.message.text
        cursor = self.db.get_cursor()

        try:
            cursor.execute("SELECT user_id FROM homeworks WHERE hw_id = ?", (hw_id,))
            result = cursor.fetchone()
            if result:
                user_id = result[0]
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Комментарий преподавателя к вашему домашнему заданию:\n\n{feedback}"
                )
                await safe_reply(update, context, "Комментарий отправлен студенту.")
            else:
                await safe_reply(update, context, "Домашнее задание не найдено.")

            del context.user_data['awaiting_feedback_for']

        except Exception as e:
            logger.error(f"Error sending homework feedback: {e}")
            await safe_reply(update, context, "Произошла ошибка при отправке комментария.")

# Create a single instance to be used throughout the application
menu_manager = MenuManager()