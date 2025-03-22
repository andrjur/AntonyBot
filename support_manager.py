#Support_manager.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from database import DatabaseConnection
from utils import safe_reply
from constants import ADMIN_GROUP_ID, ADMIN_IDS
from constants import ADMIN_GROUP_ID

logger = logging.getLogger(__name__)

class SupportManager:
    def __init__(self, db):
        self.db = db
        self.admin_group_id = ADMIN_GROUP_ID
        logger.info(f"85 SupportManager: init")

    async def show_support(self, update: Update, context: CallbackContext):
        """Shows support menu with options."""
        keyboard = [
            [InlineKeyboardButton("Написать в поддержку", callback_data="support_write")],
            [InlineKeyboardButton("Назад", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_reply(
            update, 
            context,
            "Выберите действие:",
            reply_markup=reply_markup
        )

    async def handle_support_callback(self, update: Update, context: CallbackContext):
        """Handle support-related callback queries."""
        query = update.callback_query
        await query.answer()

        if query.data == "support_write":
            return await self.start_support_request(update, context)
        elif query.data == "back_to_menu":
            # You'll need to implement this or use menu_manager's method
            return "ACTIVE"

    async def start_support_request(self, update: Update, context: CallbackContext):
        """Starts a support request."""
        await safe_reply(
            update, 
            context,
            "Пожалуйста, опишите вашу проблему или вопрос. Вы также можете прикрепить фотографию."
        )
        return "WAIT_FOR_SUPPORT_TEXT"

    async def get_support_text(self, update: Update, context: CallbackContext):
        """Gets the support request text and sends it to the admin."""
        user_id = update.effective_user.id
        logger.info(f"get_support_text for user {user_id}")

        try:
            if update.message:
                text = update.message.text
                context.user_data["support_text"] = text
            else:
                logger.warning("This function only works with text messages.")
                await safe_reply(update, context, "This function only works with text messages.")
                return

            # Check for photo
            if update.message.photo:
                file_id = update.message.photo[-1].file_id
                context.user_data["support_photo"] = file_id
            else:
                context.user_data["support_photo"] = None

            await self.send_support_request_to_admin(update, context)
            return ConversationHandler.END

        except Exception as e:
            logger.error(f"Error in get_support_text: {e}")
            await safe_reply(update, context, "An error occurred while processing your request. Please try again later.")
            return ConversationHandler.END

    async def process_support_request(self, update: Update, context: CallbackContext):

        """Process the support request and send it to admins."""
        user_id = update.effective_user.id
        
        try:
            if update.message:
                text = update.message.text
                context.user_data["support_text"] = text
            else:
                logger.warning("This function only works with text messages.")
                await safe_reply(update, context, "Эта функция работает только с текстовыми сообщениями.")
                return

            # Check for photo
            if update.message.photo:
                file_id = update.message.photo[-1].file_id
                context.user_data["support_photo"] = file_id
            else:
                context.user_data["support_photo"] = None

            # Send to admin group
            support_text = context.user_data.get("support_text", "No text provided")
            support_photo = context.user_data.get("support_photo")
            
            caption = f"Новый запрос в поддержку!\nUser ID: {user_id}\nТекст: {support_text}"

            if support_photo:
                await context.bot.send_photo(
                    chat_id=self.admin_group_id, 
                    photo=support_photo, 
                    caption=caption
                )
            else:
                await context.bot.send_message(
                    chat_id=self.admin_group_id, 
                    text=caption
                )

            # Update support request counter
            cursor = self.db.get_cursor()
            cursor.execute(
                "UPDATE users SET support_requests = support_requests + 1 WHERE user_id = ?",
                (user_id,),
            )
            self.db.get_connection().commit()

            await safe_reply(update, context, "Ваш запрос в поддержку отправлен. Ожидайте ответа.")
            return "ACTIVE"

        except Exception as e:
            logger.error(f"Error in process_support_request: {e}")
            await safe_reply(update, context, "Произошла ошибка при обработке запроса. Попробуйте позже.")
            return "ACTIVE"

    async def send_support_request_to_admin(self, update: Update, context: CallbackContext):
        """Sends the support request to the administrator."""
        user_id = update.effective_user.id
        support_text = context.user_data.get("support_text", "No text provided")
        support_photo = context.user_data.get("support_photo")
        logger.info(f"Sending support request to admin from user {user_id}: Text='{support_text[:50]}...', Photo={support_photo}")

        try:
            # Construct message for the admin
            caption = f"New support request!\nUser ID: {user_id}\nText: {support_text}"

            # Send message to the administrator
            if support_photo:
                await context.bot.send_photo(chat_id=self.admin_group_id, photo=support_photo, caption=caption)
            else:
                await context.bot.send_message(chat_id=self.admin_group_id, text=caption)

            # Increase the support request counter
            cursor = self.db.get_cursor()
            cursor.execute(
                "UPDATE users SET support_requests = support_requests + 1 WHERE user_id = ?",
                (user_id,)
            )
            self.db.get_connection().commit()

            await safe_reply(update, context, "Your support request has been sent. Please wait for a response.")

        except Exception as e:
            logger.error(f"Error sending support request to admin: {e}")
            await safe_reply(update, context, "Произошла ошибка при отправке запроса. Попробуйте позже.")


