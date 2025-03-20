# shop_manager.py
import logging
import sqlite3
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from database import DatabaseConnection
from utils import safe_reply
from constants import ADMIN_GROUP_ID, CONFIG_FILES
from database import load_bonuses, load_payment_info



logger = logging.getLogger(__name__)

class ShopManager:
    def __init__(self, admin_group_id, tariffs_file, payment_info_file):
        self.admin_group_id = admin_group_id
        self.tariffs_file = tariffs_file
        self.payment_info_file = payment_info_file
        self.db = DatabaseConnection()
        self.token_manager = None  # Add this line
        self.init_lootboxes()  # Add this line
    
    def init_lootboxes(self):
        """Initialize lootboxes in the database."""
        db = DatabaseConnection()
        conn = db.get_connection()
        cursor = db.get_cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM lootboxes")
            count = cursor.fetchone()[0]
            if count == 0:
                cursor.execute(
                    """
                    INSERT INTO lootboxes (box_type, reward, probability) VALUES
                    ('light', 'скидка', 0.8),
                    ('light', 'товар', 0.2);
                    """
                )
                conn.commit()
                logger.info("Таблица lootboxes инициализирована.")
        except sqlite3.Error as e:
            logger.error(f"Ошибка при инициализации таблицы lootboxes: {e}")
        self.db = DatabaseConnection()
        self.admin_group_id = ADMIN_GROUP_ID
        self.tariffs_file = tariffs_file
        self.payment_info_file = payment_info_file
        self.bonuses = load_bonuses()  # Add this line

    async def apply_bonuses(self, user_id: int, price: float) -> float:
        """Applies available bonuses to the price."""
        try:
            cursor = self.db.get_cursor()
            cursor.execute("""
                SELECT bonus_amount 
                FROM user_bonuses 
                WHERE user_id = ? AND expiry_date > datetime('now')
                """, (user_id,))
            available_bonus = cursor.fetchone()

            if available_bonus and available_bonus[0] > 0:
                bonus_amount = min(available_bonus[0], price * 0.2)  # Max 20% discount
                return price - bonus_amount
            return price

        except Exception as e:
            logger.error(f"Error applying bonuses: {e}")
            return price

    # Отображает тарифы и акции. *
    async def show_tariffs(self, update: Update, context: CallbackContext):
        """Shows available tariffs."""
        try:
            with open(self.tariffs_file, "r", encoding="utf-8") as f:
                tariffs = json.load(f)

            message = "Доступные тарифы:\n\n"
            keyboard = []

            for tariff in tariffs:
                message += f"📌 {tariff['title']}\n{tariff['description']}\n\n"
                keyboard.append([InlineKeyboardButton(tariff['title'], callback_data=f"tariff_{tariff['id']}")])

            keyboard.append([InlineKeyboardButton("Назад в меню ↩️", callback_data="menu_back")])
            reply_markup = InlineKeyboardMarkup(keyboard)

            await safe_reply(update, context, message, reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Error showing tariffs: {e}")
            await safe_reply(update, context, "Произошла ошибка при загрузке тарифов. Попробуйте позже.")

    # выбор товара в магазине *
    async def handle_tariff_selection(self, update: Update, context: CallbackContext, tariff_id: str):
        """Handles the selection of a tariff."""
        try:
            with open(self.tariffs_file, "r", encoding="utf-8") as f:
                tariffs = json.load(f)

            selected_tariff = next((tariff for tariff in tariffs if tariff["id"] == tariff_id), None)
            if not selected_tariff:
                await safe_reply(update, context, "Выбранный тариф не найден.")
                return

            message = f"Вы выбрали: {selected_tariff['title']}\n\n{selected_tariff['description']}"
            if selected_tariff["type"] == "discount":
                message += f"\n\nСкидка: {int((1 - selected_tariff['price']) * 100)}%"
            elif selected_tariff["type"] == "payment":
                message += f"\n\nЦена: {selected_tariff['price']} руб."

            keyboard = [
                [InlineKeyboardButton("Купить", callback_data=f"buy_tariff_{tariff_id}")],
                [InlineKeyboardButton("Назад к тарифам", callback_data="tariffs")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await safe_reply(update, context, message, reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Error handling tariff selection: {e}")
            await safe_reply(update, context, "Произошла ошибка при выборе тарифа. Попробуйте позже.")

    async def handle_admin_action(self, update: Update, context: CallbackContext, data: str):
        """Handles admin-related shop actions."""
        if data.startswith("approve_payment_"):
            payment_id = data.split("_")[-1]
            await self.handle_approve_payment(update, context, payment_id)
        elif data.startswith("decline_payment_"):
            payment_id = data.split("_")[-1]
            await self.handle_decline_payment(update, context, payment_id)

    async def handle_shop_action(self, update: Update, context: CallbackContext, data: str):
        """Handles shop-related actions."""
        if data.startswith('tariff_'):
            tariff_id = data.split('_', 1)[1]
            await self.handle_tariff_selection(update, context, tariff_id)
        elif data.startswith('buy_tariff_'):
            tariff_id = data.split('_', 2)[2]
            await self.handle_buy_tariff(update, context, tariff_id)
        elif data.startswith('go_to_payment_'):
            tariff_id = data.split('_', 2)[2]
            await self.handle_go_to_payment(update, context, tariff_id)
        elif data.startswith('check_payment_'):
            try:
                tariff_id = data.split('_', 2)[1]
                await self.handle_check_payment(update, context, tariff_id)
            except IndexError:
                logger.error(f"Failed to extract tariff_id from data: {data}")
                await safe_reply(update, context, "Произошла ошибка. Попробуйте позже.")

    async def handle_approve_payment(self, update: Update, context: CallbackContext, payment_id: str):
        """Handles payment approval by admin."""
        try:
            cursor = self.db.get_cursor()
            cursor.execute(
                """
                UPDATE transactions 
                SET status = 'approved', approval_time = datetime('now')
                WHERE id = ? AND status = 'pending'
                RETURNING user_id, tariff_id
                """,
                (payment_id,)
            )
            payment_data = cursor.fetchone()
            
            if not payment_data:
                await safe_reply(update, context, "Payment not found or already processed.")
                return
                
            user_id, tariff_id = payment_data
            self.db.get_connection().commit()
            
            # Add the purchased course to user's profile
            await self.add_purchased_course(user_id, tariff_id, context)
            
            # Notify user about approved payment
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ Ваш платеж подтвержден! Тариф активирован."
            )
            
            logger.info(f"Payment {payment_id} approved for user {user_id}")
            await safe_reply(update, context, "Payment approved successfully.")
            
        except Exception as e:
            logger.error(f"Error approving payment: {e}")
            await safe_reply(update, context, "Error processing payment approval.")

    async def handle_decline_payment(self, update: Update, context: CallbackContext, payment_id: str):
        """Handles payment decline by admin."""
        try:
            cursor = self.db.get_cursor()
            cursor.execute(
                """
                UPDATE transactions 
                SET status = 'declined', decline_time = datetime('now')
                WHERE id = ? AND status = 'pending'
                RETURNING user_id, tariff_id
                """,
                (payment_id,)
            )
            payment_data = cursor.fetchone()
            
            if not payment_data:
                await safe_reply(update, context, "Payment not found or already processed.")
                return
                
            user_id, tariff_id = payment_data
            self.db.get_connection().commit()
            
            # Notify user about declined payment
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Ваш платеж отклонен. Пожалуйста, проверьте детали оплаты и попробуйте снова."
            )
            
            logger.info(f"Payment {payment_id} declined for user {user_id}")
            await safe_reply(update, context, "Payment declined successfully.")
            
        except Exception as e:
            logger.error(f"Error declining payment: {e}")
            await safe_reply(update, context, "Error processing payment decline.")

    # Update handle_buy_tariff to use bonuses
    async def handle_buy_tariff(self, update: Update, context: CallbackContext, tariff_id: str):
        """Handles the tariff purchase process."""
        try:
            with open(self.tariffs_file, "r", encoding="utf-8") as f:
                tariffs = json.load(f)

            selected_tariff = next((t for t in tariffs if t["id"] == tariff_id), None)
            if not selected_tariff:
                await safe_reply(update, context, "Тариф не найден.")
                return

            # Apply bonuses to price
            original_price = selected_tariff['price']
            final_price = await self.apply_bonuses(update.effective_user.id, original_price)
            
            message = (
                f"💳 Оплата тарифа: {selected_tariff['title']}\n"
                f"💰 Сумма: {original_price} руб."
            )
            
            if final_price < original_price:
                message += f"\n🎉 Цена с учетом бонусов: {final_price} руб."

            message += "\n\nДля оплаты нажмите кнопку 'Перейти к оплате'"

            keyboard = [
                [InlineKeyboardButton("Перейти к оплате", callback_data=f"go_to_payment_{tariff_id}")],
                [InlineKeyboardButton("Назад", callback_data="tariffs")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await safe_reply(update, context, message, reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Error in handle_buy_tariff: {e}")
            await safe_reply(update, context, "Произошла ошибка. Попробуйте позже.")

    async def handle_go_to_payment(self, update: Update, context: CallbackContext, tariff_id: str):
        """Handles the payment process initiation."""
        try:
            payment_info = load_payment_info(self.payment_info_file)
            if not payment_info:
                await safe_reply(update, context, "Ошибка загрузки информации об оплате.")
                return

            with open(self.tariffs_file, "r", encoding="utf-8") as f:
                tariffs = json.load(f)

            selected_tariff = next((t for t in tariffs if t["id"] == tariff_id), None)
            if not selected_tariff:
                await safe_reply(update, context, "Тариф не найден.")
                return

            # Create payment record
            cursor = self.db.get_cursor()
            cursor.execute(
                """
                INSERT INTO transactions (user_id, tariff_id, amount, status, created_at)
                VALUES (?, ?, ?, 'pending', datetime('now'))
                """,
                (update.effective_user.id, tariff_id, selected_tariff['price'])
            )
            self.db.get_connection().commit()

            message = (
                f"🏦 Реквизиты для оплаты:\n"
                f"Номер карты: {payment_info['card_number']}\n"
                f"Получатель: {payment_info['recipient_name']}\n"
                f"Сумма: {selected_tariff['price']} руб.\n\n"
                "После оплаты нажмите 'Я оплатил'"
            )

            keyboard = [
                [InlineKeyboardButton("Я оплатил", callback_data=f"check_payment_{tariff_id}")],
                [InlineKeyboardButton("Отмена", callback_data="tariffs")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await safe_reply(update, context, message, reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Error in handle_go_to_payment: {e}")
            await safe_reply(update, context, "Произошла ошибка. Попробуйте позже.")

    async def handle_check_payment(self, update: Update, context: CallbackContext, tariff_id: str):
        """Handles payment verification process."""
        try:
            user_id = update.effective_user.id
            
            # Get transaction ID
            cursor = self.db.get_cursor()
            cursor.execute(
                """
                SELECT id FROM transactions 
                WHERE user_id = ? AND tariff_id = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, tariff_id)
            )
            transaction = cursor.fetchone()
            if not transaction:
                await safe_reply(update, context, "Транзакция не найдена.")
                return
                
            transaction_id = transaction[0]
            
            # Notify admins about new payment
            admin_message = (
                f"💰 Новый платеж!\n"
                f"От пользователя: {user_id}\n"
                f"Тариф: {tariff_id}"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Подтвердить", callback_data=f"approve_payment_{transaction_id}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"decline_payment_{transaction_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=self.admin_group_id,
                text=admin_message,
                reply_markup=reply_markup
            )
            
            # Notify user
            await safe_reply(
                update,
                context,
                "✅ Спасибо! Ваш платеж находится на проверке. Мы уведомим вас о результате."
            )
            
        except Exception as e:
            logger.error(f"Error in handle_check_payment: {e}")
            await safe_reply(update, context, "Произошла ошибка при проверке платежа. Попробуйте позже.")

    async def add_purchased_course(self, user_id: int, tariff_id: str, context: CallbackContext):
        """Adds a purchased course to the user's profile."""
        logger.info(f"add_purchased_course: User {user_id} attempting to add course {tariff_id}")
        try:
            cursor = self.db.get_cursor()
            # Check if the course already exists for the user
            cursor.execute(
                """
                SELECT * FROM user_courses
                WHERE user_id = ? AND course_id = ?
                """,
                (user_id, tariff_id),
            )
            existing_course = cursor.fetchone()

            if existing_course:
                await safe_reply(context.update, context, "Этот курс уже есть в вашем профиле.")
                logger.info(f"add_purchased_course: Course {tariff_id} already exists for user {user_id}.")
                return

            # Load tariff data from tariffs.json
            with open(self.tariffs_file, "r", encoding="utf-8") as f:
                tariffs = json.load(f)
            tariff = next((t for t in tariffs if t["id"] == tariff_id), None)

            if not tariff:
                logger.error(f"add_purchased_course: Tariff with id {tariff_id} not found in tariffs.json")
                await safe_reply(context.update, context, "Произошла ошибка при добавлении курса. Попробуйте позже.")
                return

            course_type = tariff.get("course_type", "main")
            tariff_name = tariff_id.split("_")[1] if len(tariff_id.split("_")) > 1 else "default"

            # Add the course to user_courses
            cursor.execute(
                """
                INSERT INTO user_courses (user_id, course_id, course_type, progress, tariff)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, tariff_id, course_type, 1, tariff_name),
            )

            # Update active_course_id in users
            cursor.execute(
                """
                UPDATE users
                SET active_course_id = ?
                WHERE user_id = ?
                """,
                (tariff_id, user_id),
            )
            self.db.get_connection().commit()

            logger.info(f"add_purchased_course: Course {tariff_id} added to user {user_id}")
            await safe_reply(context.update, context, "Новый курс был добавлен вам в профиль.")

        except Exception as e:
            logger.error(f"add_purchased_course: An error occurred for user {user_id}: {e}")
            await safe_reply(context.update, context, "Произошла ошибка при добавлении курса. Попробуйте позже.")

    async def process_lootbox_reward(self, user_id: int, reward: str):
        """Process the reward from a lootbox."""
        if reward == "скидка":
            discount_amount = 10  # 10% discount
            cursor = self.db.get_cursor()
            cursor.execute(
                """INSERT INTO user_discounts (user_id, amount, expiry_date)
                VALUES (?, ?, datetime('now', '+7 days'))""",
                (user_id, discount_amount)
            )
            self.db.get_connection().commit()
            return f"Скидка {discount_amount}% на 7 дней!"
        elif reward == "товар":
            # Add logic for item rewards
            return "Предмет добавлен в ваш инвентарь!"
        return "Неизвестная награда"

tariffs_file=CONFIG_FILES["TARIFFS"]
payment_info_file=CONFIG_FILES["PAYMENT_INFO"]
shop_manager = ShopManager( ADMIN_GROUP_ID, tariffs_file, payment_info_file)
