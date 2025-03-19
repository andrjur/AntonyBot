from datetime import datetime, date
import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from database import DatabaseConnection
from utils import safe_reply
from datetime import datetime

logger = logging.getLogger(__name__)

class TokenManager:
    def __init__(self, admin_ids):
        self.admin_ids = admin_ids
        self.db = DatabaseConnection()
        self.shop_manager = None
        self.bonuses_config = None

    async def roll_lootbox(self, box_type: str):
        """Determines the reward from a lootbox."""
        db = DatabaseConnection()
        conn = db.get_connection()
        cursor = db.get_cursor()

        try:
            cursor.execute("SELECT reward, probability FROM lootboxes WHERE box_type = ?", (box_type,))
            rewards = cursor.fetchall()

            # Generate random number
            rand = random.random()

            cumulative_probability = 0.0
            for reward, probability in rewards:
                cumulative_probability += probability
                if rand <= cumulative_probability:
                    logger.info(f"Reward {reward} dropped from lootbox {box_type}")
                    return reward
            return "nothing"  # If nothing dropped
        except sqlite3.Error as e:
            logger.error(f"Error while determining reward from lootbox {box_type}: {e}")
            return "error"

    async def show_token_balance(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        tokens, trust_credit, monthly_increase = self.get_balance_info(user_id)
        
        message = (
            f"💰 Ваш баланс:\n"
            f"AntCoins: {tokens}\n"
            f"Кредит доверия: {trust_credit}\n"
            f"Ежемесячное увеличение: {monthly_increase}"
        )
        await safe_reply(update, context, message)

    async def buy_lootbox(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        tokens, _, _ = self.get_balance_info(user_id)
        
        LOOTBOX_COST = 10  # Define the cost of a lootbox
        
        try:
            if tokens < LOOTBOX_COST:
                await safe_reply(update, context, "Недостаточно AntCoins для покупки лутбокса!")
                return
            
            # Deduct tokens first
            if not await self.spend_tokens(user_id, LOOTBOX_COST, "Покупка лутбокса"):
                await safe_reply(update, context, "Ошибка при покупке лутбокса")
                return
                
            # Roll the lootbox and get reward
            reward = await self.roll_lootbox("light")  # Using "light" as default box type
            
            # Process the reward
            reward_message = f"🎉 Вы открыли лутбокс и получили: {reward}!"
            await safe_reply(update, context, reward_message)
            
            # Handle the reward (implement reward processing logic)
            if reward == "скидка":
                # Add discount processing
                pass
            elif reward == "товар":
                # Add item processing
                pass
                
        except Exception as e:
            logger.error(f"Error in buy_lootbox: {e}")
            await safe_reply(update, context, "Произошла ошибка при покупке лутбокса")
            return
            
    # Add these methods to TokenManager class
    def add_tokens(self, user_id: int, amount: int, reason: str, update: Update, context: CallbackContext):

        """Начисляет жетоны пользователю, включая различные бонусы."""
        db = DatabaseConnection()
        conn = db.get_connection()
        cursor = db.get_cursor()

        try:
            global bonuses_config
            if bonuses_config is None:  # Load only if not initialized
                bonuses_config = load_bonuses()
                
            with conn:
                today = date.today()

                # Keep your existing user data query
                cursor.execute(
                    """
                    SELECT birthday, registration_date, referral_count FROM users WHERE user_id = ?
                    """,
                    (user_id,),
                )
                user_data = cursor.fetchone()

                if not user_data:
                    logger.warning(f"Не найден пользователь {user_id} при попытке начисления бонусов.")
                    await safe_reply(update, context, "Пользователь не найден.")
                    return

                # Keep your existing data processing
                birthday_str, registration_date_str, referral_count = user_data
                birthday = datetime.strptime(birthday_str, "%Y-%m-%d").date() if birthday_str else None
                registration_date = datetime.strptime(registration_date_str, "%Y-%m-%d").date() if registration_date_str else None
                referral_count = referral_count if referral_count else 0

                # Your existing bonus calculations
                monthly_bonus_amount = bonuses_config.get("monthly_bonus", 1)
                last_bonus_date = get_last_bonus_date(cursor, user_id)
                if not last_bonus_date or (last_bonus_date.year != today.year or last_bonus_date.month != today.month):
                    amount += monthly_bonus_amount
                    reason += f" + Ежемесячный бонус ({monthly_bonus_amount})"
                    set_last_bonus_date(cursor, user_id, today)
                    logger.info(f"Начислен ежемесячный бонус пользователю {user_id}")

                # Keep your birthday bonus logic
                birthday_bonus_amount = bonuses_config.get("birthday_bonus", 5)
                if birthday and birthday.month == today.month and birthday.day == today.day:
                    amount += birthday_bonus_amount
                    reason += f" + Бонус на день рождения ({birthday_bonus_amount})"
                    logger.info(f"Начислен бонус на день рождения пользователю {user_id}")

                # Keep your referral bonus logic
                referral_bonus_amount = bonuses_config.get("referral_bonus", 2)
                if referral_count > 0:
                    amount += referral_bonus_amount * referral_count
                    reason += f" + Бонус за рефералов ({referral_bonus_amount * referral_count})"
                    logger.info(f"Начислен бонус за рефералов пользователю {user_id}")

                # Update tokens
                cursor.execute(
                    """
                    INSERT INTO user_tokens (user_id, tokens)
                    VALUES (?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET tokens = tokens + ?
                    """,
                    (user_id, amount, amount),
                )

                # Log transaction
                cursor.execute(
                    """
                    INSERT INTO transactions (user_id, action, amount, reason)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, "earn", amount, reason),
                )
                
                conn.commit()
                logger.info(f"Начислено {amount} жетонов пользователю {user_id} по причине: {reason}")
                
                if update and context:
                    await safe_reply(update, context, f"Начислено {amount} АнтКоинов!")
                    
        except sqlite3.Error as e:
            logger.error(f"Ошибка при начислении жетонов пользователю {user_id}: {e}")
            if update and context:
                await safe_reply(update, context, f"Произошла ошибка при начислении жетонов пользователю {user_id}: {e}")
            conn.rollback()
            raise
        
    def get_balance_info(self, user_id: int):
        """Retrieves user's token balance, trust credit, and monthly trust increase."""
        cursor = self.db.get_cursor()
        
        cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
        tokens_data = cursor.fetchone()
        tokens = tokens_data[0] if tokens_data else 0

        cursor.execute("SELECT trust_credit FROM users WHERE user_id = ?", (user_id,))
        credit_data = cursor.fetchone()
        trust_credit = credit_data[0] if credit_data else 0

        monthly_trust_increase = 2  # Default value

        return tokens, trust_credit, monthly_trust_increase

    def get_token_balance(self, user_id: int) -> int:
        """Returns user's current token balance."""
        cursor = self.db.get_cursor()
        try:
            cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
            balance_data = cursor.fetchone()
            return balance_data[0] if balance_data else 0
        except sqlite3.Error as e:
            logger.error(f"Error getting token balance for user {user_id}: {e}")
            return 0

    def spend_tokens(self, user_id: int, amount: int, reason: str):
        """Deducts tokens from user's balance."""
        conn = self.db.get_connection()
        cursor = self.db.get_cursor()
        try:
            with conn:
                # Check balance
                cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
                balance_data = cursor.fetchone()
                if not balance_data or balance_data[0] < amount:
                    raise ValueError("Insufficient tokens")

                # Deduct tokens
                cursor.execute(
                    "UPDATE user_tokens SET tokens = tokens - ? WHERE user_id = ?",
                    (amount, user_id)
                )

                # Log transaction
                cursor.execute(
                    """
                    INSERT INTO transactions (user_id, action, amount, reason)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, "spend", amount, reason)
                )
            logger.info(f"Deducted {amount} tokens from user {user_id} for: {reason}")
        except sqlite3.Error as e:
            logger.error(f"Error deducting tokens from user {user_id}: {e}")
            raise

    def get_last_bonus_date(self, user_id: int) -> date:
        """Gets the date of last monthly bonus payment."""
        cursor = self.db.get_cursor()
        
        cursor.execute("SELECT last_bonus_date FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        last_bonus_date_str = result[0] if result else None
        
        if last_bonus_date_str:
            return datetime.strptime(last_bonus_date_str, "%Y-%m-%d").date()
        return None

    def set_last_bonus_date(self, user_id: int, bonus_date: date):
        """Sets the date of last monthly bonus payment."""
        conn = self.db.get_connection()
        cursor = self.db.get_cursor()
        
        cursor.execute(
            "UPDATE users SET last_bonus_date = ? WHERE user_id = ?",
            (bonus_date.strftime("%Y-%m-%d"), user_id)
        )
        conn.commit()




