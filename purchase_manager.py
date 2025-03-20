#purchase_manager.py
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from database import DatabaseConnection
from utils import safe_reply
from database import load_tariffs

logger = logging.getLogger(__name__)

class PurchaseManager:
    def __init__(self, admin_group_id, admin_ids):
        self.db = DatabaseConnection()
        self.admin_group_id = admin_group_id
        self.admin_ids = admin_ids

    async def buy_tariff(self, update: Update, context: CallbackContext):
        """Handles tariff purchase process."""
        user_id = update.effective_user.id
        try:
            if not context.user_data.get("selected_tariff"):
                await safe_reply(update, context, "Пожалуйста, сначала выберите тариф.")
                return
        
            tariff = context.user_data["selected_tariff"]
            cursor = self.db.get_cursor()
            
            # Create purchase record
            cursor.execute("""
                INSERT INTO purchases (user_id, tariff_id, amount, status)
                VALUES (?, ?, ?, 'pending')
                RETURNING id
            """, (user_id, tariff['id'], tariff['price']))
            
            purchase_id = cursor.fetchone()[0]
            self.db.get_connection().commit()
        
            # Send notification to admin
            admin_message = (
                f"🛍 Новая покупка!\n"
                f"Покупатель: {user_id}\n"
                f"Тариф: {tariff['title']}\n"
                f"Сумма: {tariff['price']} руб."
            )
            keyboard = [
                [
                    InlineKeyboardButton("✅ Подтвердить", callback_data=f"admin_approve_purchase_{purchase_id}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_reject_purchase_{purchase_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=self.admin_group_id,
                text=admin_message,
                reply_markup=reply_markup
            )
        
            await safe_reply(update, context, "Ваша заявка на покупку отправлена администратору. Ожидайте подтверждения.")
        
        except Exception as e:
            logger.error(f"Error in buy_tariff: {e}")
            await safe_reply(update, context, "Произошла ошибка при оформлении покупки. Попробуйте позже.")
    
    async def gift_tariff(self, update: Update, context: CallbackContext):
        """Handles gifting a tariff to another user."""
        user_id = update.effective_user.id
        try:
            if not context.user_data.get("selected_tariff"):
                await safe_reply(update, context, "Пожалуйста, сначала выберите тариф для подарка.")
                return
    
            await safe_reply(update, context, "Введите ID пользователя, которому хотите подарить тариф:")
            context.user_data['gifting'] = True
            return ConversationHandler.WAIT_FOR_GIFT_USER_ID
    
        except Exception as e:
            logger.error(f"Error in gift_tariff: {e}")
            await safe_reply(update, context, "Произошла ошибка при оформлении подарка. Попробуйте позже.")
    
    async def admin_approve_purchase(self, update: Update, context: CallbackContext):
        """Handles purchase approval by admin."""
        try:
            query = update.callback_query
            purchase_id = query.data.split('_')[-1]
            cursor = self.db.get_cursor()
    
            # Update purchase status
            cursor.execute("""
                UPDATE purchases 
                SET status = 'approved', approval_time = datetime('now')
                WHERE id = ? AND status = 'pending'
                RETURNING user_id, tariff_id
            """, (purchase_id,))
            
            result = cursor.fetchone()
            if not result:
                await query.answer("Purchase not found or already processed")
                return
    
            user_id, tariff_id = result
            self.db.get_connection().commit()
    
            # Notify user
            await context.bot.send_message(
                chat_id=user_id,
                text="🎉 Ваша покупка подтверждена! Доступ к тарифу активирован."
            )
    
            await query.answer("Purchase approved")
            await query.edit_message_reply_markup(reply_markup=None)
    
        except Exception as e:
            logger.error(f"Error in admin_approve_purchase: {e}")
            await query.answer("Error processing approval")
    
    async def admin_reject_purchase(self, update: Update, context: CallbackContext):
        """Handles purchase rejection by admin."""
        try:
            query = update.callback_query
            purchase_id = query.data.split('_')[-1]
            cursor = self.db.get_cursor()
    
            cursor.execute("""
                UPDATE purchases 
                SET status = 'rejected', rejection_time = datetime('now')
                WHERE id = ? AND status = 'pending'
                RETURNING user_id
            """, (purchase_id,))
            
            result = cursor.fetchone()
            if not result:
                await query.answer("Purchase not found or already processed")
                return
    
            user_id = result[0]
            self.db.get_connection().commit()
    
            # Notify user
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Ваша покупка отклонена. Пожалуйста, свяжитесь с поддержкой для уточнения деталей."
            )
    
            await query.answer("Purchase rejected")
            await query.edit_message_reply_markup(reply_markup=None)
    
        except Exception as e:
            logger.error(f"Error in admin_reject_purchase: {e}")
            await query.answer("Error processing rejection")
    
    async def admin_approve_discount(self, update: Update, context: CallbackContext):
        """Handles discount approval by admin."""
        try:
            query = update.callback_query
            discount_id = query.data.split('_')[-1]
            cursor = self.db.get_cursor()
    
            cursor.execute("""
                UPDATE discount_requests 
                SET status = 'approved', approval_time = datetime('now')
                WHERE id = ? AND status = 'pending'
                RETURNING user_id, discount_amount
            """, (discount_id,))
            
            result = cursor.fetchone()
            if not result:
                await query.answer("Discount request not found or already processed")
                return
    
            user_id, discount_amount = result
            self.db.get_connection().commit()
    
            # Add discount to user's account
            cursor.execute("""
                INSERT INTO user_discounts (user_id, amount, expiry_date)
                VALUES (?, ?, datetime('now', '+30 days'))
            """, (user_id, discount_amount))
            self.db.get_connection().commit()
    
            # Notify user
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 Ваша скидка {discount_amount}% одобрена! Она действительна в течение 30 дней."
            )
    
            await query.answer("Discount approved")
            await query.edit_message_reply_markup(reply_markup=None)
    
        except Exception as e:
            logger.error(f"Error in admin_approve_discount: {e}")
            await query.answer("Error processing discount approval")
    
    async def admin_reject_discount(self, update: Update, context: CallbackContext):
        """Handles discount rejection by admin."""
        try:
            query = update.callback_query
            discount_id = query.data.split('_')[-1]
            cursor = self.db.get_cursor()
    
            cursor.execute("""
                UPDATE discount_requests 
                SET status = 'rejected', rejection_time = datetime('now')
                WHERE id = ? AND status = 'pending'
                RETURNING user_id
            """, (discount_id,))
            
            result = cursor.fetchone()
            if not result:
                await query.answer("Discount request not found or already processed")
                return
    
            user_id = result[0]
            self.db.get_connection().commit()
    
            # Notify user
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Ваш запрос на скидку отклонен. Вы можете попробовать снова позже."
            )
    
            await query.answer("Discount rejected")
            await query.edit_message_reply_markup(reply_markup=None)
    
        except Exception as e:
            logger.error(f"Error in admin_reject_discount: {e}")
            await query.answer("Error processing discount rejection")
    
    # Обрабатывает селфи для получения скидки. *
    async def process_selfie(self, update: Update, context: CallbackContext):
        """Processes selfie for discount request."""
        user_id = update.effective_user.id
        photo = update.message.photo[-1]
        file_id = photo.file_id
        context.user_data["selfie_file_id"] = file_id

        await update.message.reply_text("Теперь отправьте описание, почему вы хотите получить эту скидку:")
        return ConversationHandler.WAIT_FOR_DESCRIPTION
    
    # Обрабатывает описание для получения скидки.*
    async def process_description(self, update: Update, context: CallbackContext):
        """Processes description for discount request."""
        user_id = update.effective_user.id
        tariff = context.user_data.get("tariff")
        description = update.message.text
        context.user_data["description"] = description
        photo = context.user_data.get("selfie_file_id")

        caption = f"Запрос на скидку!\nUser ID: {user_id}\nТариф: {tariff['title']}\nОписание: {description}"
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Подтвердить скидку",
                    callback_data=f'admin_approve_discount_{user_id}_{tariff["id"]}',
                ),
                InlineKeyboardButton(
                    "❌ Отклонить скидку",
                    callback_data=f'admin_reject_discount_{user_id}_{tariff["id"]}',
                ),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_photo(
            chat_id=self.admin_group_id,
            photo=photo,
            caption=caption,
            reply_markup=reply_markup
        )
        await update.message.reply_text("Ваш запрос отправлен на рассмотрение администраторам.")
        return ConversationHandler.END

    async def process_check(self, update: Update, context: CallbackContext):
        """Processes payment check photo."""
        try:
            user_id = update.effective_user.id
            tariff = context.user_data.get("tariff")
            photo = update.message.photo[-1]
            file_id = photo.file_id

            caption = f"Новый запрос на покупку!\nUser ID: {user_id}\nТариф: {tariff['title']}"
            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ Подтвердить покупку",
                        callback_data=f'admin_approve_purchase_{user_id}_{tariff["id"]}',
                    ),
                    InlineKeyboardButton(
                        "❌ Отклонить покупку",
                        callback_data=f'admin_reject_purchase_{user_id}_{tariff["id"]}',
                    ),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_photo(
                chat_id=self.admin_group_id,
                photo=file_id,
                caption=caption,
                reply_markup=reply_markup,
            )

            await safe_reply(update, context, "Чек отправлен на проверку администраторам. Ожидайте подтверждения.")
            context.user_data.clear()
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"process_check error {e}")
            await safe_reply(update, context, "Ошибка при обработке чека. Попробуйте позже.")
            return ConversationHandler.END

    async def process_gift_user_id(self, update: Update, context: CallbackContext):
        """Processes recipient's user ID for gift purchase."""
        try:
            gift_user_id = update.message.text
            if not gift_user_id or not gift_user_id.isdigit():
                await safe_reply(update, context, "Пожалуйста, введите корректный User ID, состоящий только из цифр.")
                return ConversationHandler.WAIT_FOR_GIFT_USER_ID

            context.user_data["gift_user_id"] = gift_user_id
            tariff = context.user_data.get("tariff")
            text = f"Для оформления подарка, пожалуйста, переведите {tariff['price']} рублей на номер [номер] и загрузите чек сюда в этот диалог."
            await safe_reply(update, context, text)
            return ConversationHandler.WAIT_FOR_CHECK
        except Exception as e:
            logger.error(f"process_gift_user_id error {e}")
            await safe_reply(update, context, "Пожалуйста, введите корректный User ID, состоящий только из цифр.")
            return ConversationHandler.WAIT_FOR_GIFT_USER_ID

    # просим номерок *
    async def process_phone_number(self, update: Update, context: CallbackContext):
        """Processes user's phone number for purchase."""
        contact = update.message.contact
        phone_number = contact.phone_number
        context.user_data["phone_number"] = phone_number

        user_id = update.effective_user.id
        tariff = context.user_data.get("tariff")
        caption = f"Новый запрос на покупку!\nUser ID: {user_id}\nТариф: {tariff['title']}\nНомер телефона: {phone_number}"
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Подтвердить покупку",
                    callback_data=f'admin_approve_purchase_{user_id}_{tariff["id"]}',
                ),
                InlineKeyboardButton(
                    "❌ Отклонить покупку",
                    callback_data=f'admin_reject_purchase_{user_id}_{tariff["id"]}',
                ),
            ]
        ]
        photo = context.user_data.get("selfie_file_id")
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if photo:
            await context.bot.send_photo(
                chat_id=self.admin_group_id,
                photo=photo,
                caption=caption,
                reply_markup=reply_markup,
            )
        else:
            await context.bot.send_message(
                chat_id=self.admin_group_id,
                text=caption,
                reply_markup=reply_markup
            )

        await update.message.reply_text("Ваш запрос отправлен на рассмотрение администраторам.")
        context.user_data.clear()
        return ConversationHandler.END