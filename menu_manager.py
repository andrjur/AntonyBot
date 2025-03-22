#menu_manager.py
import json
import logging
import mimetypes
import os
import sqlite3

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import CallbackContext, ConversationHandler
from database import DatabaseConnection
from utils import safe_reply, get_db_and_user, db_handler
from constants import ADMIN_IDS, DELAY_PATTERN
from datetime import date, datetime, time
from constants import CONFIG_FILES
 
logger = logging.getLogger(__name__)

class MenuManager:
    def __init__(self, db):
        self.db = db
        logger.info(f"MenuManager: init")

    def load_bonuses(self, update: Update, context: CallbackContext ):
        """Загружает настройки бонусов из файла."""
        try:
            BONUSES_FILE = CONFIG_FILES["BONUSES"]
            with open(BONUSES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Файл {BONUSES_FILE} не найден. Используются значения по умолчанию.")
            return {
                "monthly_bonus": 1,
                "birthday_bonus": 5,
                "referral_bonus": 2,
                "bonus_check_interval": 86400,  # 24 hours
            }
        except json.JSONDecodeError:
            logger.error(f"Ошибка при чтении JSON из файла {BONUSES_FILE}. Используются значения по умолчанию.")
            return {
                "monthly_bonus": 1,
                "birthday_bonus": 5,
                "referral_bonus": 2,
                "bonus_check_interval": 86400,  # 24 hours
            }

    @db_handler
    def get_last_bonus_date(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """Получает дату последнего начисления ежемесячного бонуса."""


        cursor.execute(
            """
            SELECT last_bonus_date FROM users WHERE user_id = ?
        """,
            (user_id,),
        )
        result = cursor.fetchone()
        last_bonus_date_str = result[0] if result else None
        if last_bonus_date_str:
            return datetime.strptime(last_bonus_date_str, "%Y-%m-%d").date()
        return None

    @db_handler
    async def get_next_bonus_info(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """Получает информацию о следующем и последнем начислении бонусов."""
        bonuses_config = MenuManager.load_bonuses(self)
        today = date.today()

        # 1. Monthly bonus
        last_bonus_date = MenuManager.get_last_bonus_date(self, cursor, user_id)
        if not last_bonus_date or (
                last_bonus_date.year != today.year or last_bonus_date.month != today.month
        ):
            next_bonus = f"+{bonuses_config.get('monthly_bonus', 1)} (Ежемесячный бонус)"
        else:
            next_bonus = "Ежемесячный бонус уже начислен в этом месяце"

        # 2. Birthday bonus
        cursor.execute("SELECT birthday FROM users WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()
        birthday_str = user_data[0] if user_data else None
        if birthday_str:
            birthday = datetime.strptime(birthday_str, "%Y-%m-%d").date()
            if birthday.month == today.month and birthday.day == today.day:
                next_bonus += f"\n+{bonuses_config.get('birthday_bonus', 5)} (Бонус на день рождения)"
            else:
                next_bonus += f"\nБонус на день рождения будет начислен {birthday_str}"

        return {"last_bonus": "За регистрацию", "next_bonus": next_bonus}  # Пример

    @db_handler
    async def get_available_products(self, update: Update, context: CallbackContext, conn, cursor, user, user_id, tokens):
        """Возвращает информацию о доступных продуктах в магазине."""
        #  Здесь надо подгрузить товары из бд

        # 1. Make a database query
        cursor.execute("SELECT product_name, price FROM products")  # WHERE price <= ? ORDER BY price ASC
        logger.info(f"  get_available_products  Начало выполнения функции с tokens={tokens}")  # Добавлено логирование
        products = cursor.fetchall()
        if not products:
            return "\nВ магазине пока нет товаров."

        logger.info(f" get_available_products  Найдено {len(products)} товаров.")  # Добавлено логирование
        # 2. Find the cheapest product
        affordable_products = []
        unaffordable_products = []
        for product in products:
            if product[1] <= tokens:
                affordable_products.append(product)
            else:
                unaffordable_products.append(product)
        if not affordable_products:
            return "\nУ вас недостаточно средств для покупки каких-либо товаров."
        # 3. Suggest Products
        products_str = ""
        if affordable_products:
            products_str += f"\nВы можете купить:\n"
            for product in affordable_products:
                products_str += f"- {product[0]} (Цена: {product[1]})\n"
        products_str = products_str[:-1] if products_str else products_str
        if unaffordable_products:
            products_str += f"\nВам немного не хватает для:\n"
            for product in unaffordable_products:
                if product[1] - tokens <= 10:
                    products_str += f"- {product[0]} (Цена: {product[1]})\n"
        products_str = products_str[:-1] if products_str else products_str
        return products_str


    # домашка ???
    @db_handler
    async def get_homework_status_text(self, update: Update, context: CallbackContext, conn, cursor, user, user_id, course_id ):
        """Возвращает текст статуса проверки домашнего задания."""

        # Проверяем статус домашнего задания
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
            # Если домашки еще не отправлялись
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

        # Формируем текст в зависимости от статуса
        if status == "pending":
            return f"Домашка к {lesson} уроку на самопроверке"
        elif status == "approved":
            return f"Домашка к {lesson} уроку принята"
        else:
            return "Статус домашки неизвестен странен и загадочен"

    # Функция для получения файлов урока ============== не оптимизировали safe
    @db_handler
    def get_lesson_files(self, update: Update, context: CallbackContext, conn, cursor, user, user_id, lesson_number, course_id):
        """Извлекает список файлов урока."""
        files = []
        directory = f"courses/{course_id}"  # Укажите правильный путь к директории с файлами
        logger.info(f"get_lesson_files {directory}")
        try:
            logger.info(f"внутри трая считываем всё из {os.listdir(directory)}")
            for filename in os.listdir(directory):
                # logger.info(f"for  {filename=}")
                if filename.startswith(f"lesson{lesson_number}_") and not filename.endswith(
                        ".html") and not filename.endswith(".txt") and not filename.endswith(".md"):
                    file_path = os.path.join(directory, filename)
                    mime_type, _ = mimetypes.guess_type(file_path)
                    file_type = "document"  # Тип по умолчанию
                    delay = 0  # Задержка по умолчанию

                    # Проверка типа файла на основе MIME-типа
                    if mime_type and mime_type.startswith('image'):
                        file_type = "photo"
                    elif mime_type and mime_type.startswith('video'):
                        file_type = "video"
                    elif mime_type and mime_type.startswith('audio'):
                        file_type = "audio"

                    # Извлечение информации о задержке из имени файла
                    match = DELAY_PATTERN.search(filename)
                    if match:
                        delay_value, delay_unit = match.groups()
                        delay_value = int(delay_value)

                        if delay_unit in ["min", "m"]:
                            delay = delay_value * 60  # Convert minutes to seconds
                        elif delay_unit in ["hour", "h"]:
                            delay = delay_value * 3600  # Convert hours to seconds
                        else:
                            delay = delay_value  # Default seconds

                    files.append({"path": file_path, "type": file_type, "delay": delay})
                    # logger.info(f"for  len (files)={len(files)}===========")

        except FileNotFoundError:
            logger.error(f"Directory not found: {directory}")
            return []
        except Exception as e:
            logger.error(f"Error reading lesson files: {e}")
            return []

        logger.info(f"  get_lesson_files {user_id=} - lesson_number={lesson_number}")
        return files

    # Функция для получения предварительных материалов строго ненадо  conn: sqlite3.Connection, cursor: sqlite3.Cursor,
    @db_handler
    def get_preliminary_materials(self, update: Update, context: CallbackContext, conn, cursor, user, user_id, course_id, lesson):
        """
        Возвращает список всех предварительных материалов для урока.
        """
        lesson_dir = f"courses/{course_id}/"
        materials = []
        logger.info(f" get_preliminary_materials {lesson_dir} ")
        for filename in os.listdir(lesson_dir):
            if filename.startswith(f"lesson{lesson}_p") and os.path.isfile(os.path.join(lesson_dir, filename)):
                materials.append(filename)
        materials.sort()  # Сортируем по порядку (p1, p2, ...)
        return materials

    async def show_menu(self, update: Update, context: CallbackContext):
        """Отображает главное меню с кнопками."""
        keyboard = [
            [
                InlineKeyboardButton("Текущий урок", callback_data="get_current_lesson"),
                InlineKeyboardButton("Галерея ДЗ", callback_data="gallery"),
            ],
            [
                InlineKeyboardButton("Тарифы", callback_data="tariffs"),
                InlineKeyboardButton("Настройки курса", callback_data="course_settings"),
            ],
            [
                InlineKeyboardButton("Статистика", callback_data="statistics"),
                InlineKeyboardButton("Поддержка", callback_data="support"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Главное меню:", reply_markup=reply_markup)

    @db_handler
    async def start(self, update: Update, context: CallbackContext, conn: sqlite3.Connection,
                    cursor: sqlite3.Cursor, user, user_id):
        """Обработчик команды /start."""

        logger.info(
            f"Начало разговора с пользователем {user_id} =================================================================")
        logger.info(f"Пользователь {user_id} запустил команду /start")

        # Fetch user info from the database
        user_data = None
        if cursor:
            cursor.execute("SELECT full_name, active_course_id FROM users WHERE user_id = ?", (user_id,))
            user_data = cursor.fetchone()

        if user_data:
            full_name = user_data[0]
            active_course_id = user_data[1]

            if full_name:
                if active_course_id:
                    logger.info(f"Пользователь {user_id} уже зарегистрирован и курс активирован.")
                    greeting = f"Приветствую, {full_name.split()[0]}! 👋"
                    await safe_reply(update, context, greeting)
                    logger.info(f"332 из Start вызываю menu ")
                    await context.bot_data['managers']['menu'].show_main_menu(update, context)
                    logger.info(f"333 после menu ")
                    return ACTIVE  # User is fully set up
                else:
                    logger.info(f"Пользователь {user_id} зарегистрирован, но курс не активирован.")
                    greeting = f"Приветствую, {full_name.split()[0]}! 👋"
                    await safe_reply(update, context, f"{greeting}\nДля активации курса, введите кодовое слово:")
                    return WAIT_FOR_CODE  # Ask for the code word
            else:
                logger.info(f"Пользователь {user_id} зарегистрирован, но имя отсутствует.")
                await safe_reply(update, context, "Пожалуйста, введите ваше имя:")
                return WAIT_FOR_NAME  # Ask for the name
        else:
            # Insert new user into the database
            cursor.execute("""
                    INSERT INTO users (user_id, full_name, registration_date) 
                    VALUES (?, ?, ?)
                """, (user_id, 'ЧЕБУРАШКА', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            logger.info(f"Новый пользователь {user_id} - запрашиваем имя")
            await safe_reply(update, context, "Привет! Пожалуйста, введите ваше имя:")
            return WAIT_FOR_NAME


    @db_handler
    async def show_main_menu(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """  Отображает главное меню с кнопками.   """
        logger.info("333 зашли в show_main_menu ")



        # 1. Получаем количество токенов пользователя
        cursor.execute("SELECT tokens FROM user_tokens WHERE user_id = ?", (user_id,))
        tokens_data = cursor.fetchone()
        tokens = tokens_data[0] if tokens_data else 0

        # 2. Получаем информацию о следующем бонусе
        next_bonus_info = await MenuManager.get_next_bonus_info(self.conn, cursor, user_id)

        # 3. Формируем сообщение
        # Преобразуем токены в монеты
        bronze_coins = tokens % 10  # 1 BRONZE_COIN = 1 токен
        tokens //= 10  # остались десятки
        silver_coins = tokens % 10  # 1 SILVER_COIN = 10 токенов
        tokens //= 10  # остались сотки
        gold_coins = tokens % 10  # 1 GOLD_COIN = 100 токенов
        tokens //= 10  # остались тыщи
        platinum_coins = tokens  # 1 GEM_COIN = 1000 токенов

        # Coin emojis
        BRONZE_COIN = "🟤"  # Bronze coin
        SILVER_COIN = "⚪️"  # Silver coin
        GOLD_COIN = "🟡"  # Gold coin
        PLATINUM_COIN = "💎"  # Platinum Coin

        # Формируем строку с монетами
        coins_display = (
            f"{PLATINUM_COIN}x{platinum_coins}"
            f"{GOLD_COIN}x{gold_coins}"
            f"{SILVER_COIN}x{silver_coins}"
            f"{BRONZE_COIN}x{bronze_coins}"
        )
        tokens = tokens_data[0] if tokens_data else 0  # просто считали заново

        message = f"Ваши antCoins: {tokens}   {coins_display}\n"
        message += f"Последнее начисление: {next_bonus_info['last_bonus']}\n"
        message += f"Следующее начисление: {next_bonus_info['next_bonus']}\n"

        # 4. Получаем доступные товары для покупки
        products_message = await MenuManager.get_available_products(self, conn, cursor, tokens)
        message += products_message
        try:
            # Get data of course
            cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user.id,))
            active_course_data = cursor.fetchone()
            logger.info(f" active_course_data= {active_course_data} ---- ")
            if not active_course_data or not active_course_data[0]:
                message_text = "Активируйте курс с помощью кодового слова."
                await safe_reply(update, context, message_text)
                return ConversationHandler.END

            active_course_id_full = active_course_data[0]
            # Short name
            active_course_id = active_course_id_full.split("_")[0]
            active_tariff = active_course_id_full.split("_")[1] if len(
                active_course_id_full.split("_")) > 1 else "default"

            # Получаем данные о типе курса и прогрессе
            cursor.execute(
                """
                SELECT course_type, progress
                FROM user_courses
                WHERE user_id = ? AND course_id = ?
            """,
                (user.id, active_course_id_full),
            )
            course_data = cursor.fetchone()
            logger.info(f" course_data= {course_data} ----- ")

            if not course_data:
                logger.warning(f"Не найден course_type для user_id={user.id} и course_id={active_course_id_full}")
                course_type, progress = "unknown", 0  # Установите значения по умолчанию
            else:
                course_type, progress = course_data

            logger.info(f" Тип курса: {course_type=} Прогресс: {progress=} ------ ")

            logger.info(f" {course_type=} {progress=} ------ ")

            # Notifications
            cursor.execute(
                "SELECT morning_notification, evening_notification FROM user_settings WHERE user_id = ?",
                (user.id,),
            )
            settings = cursor.fetchone()

            logger.info(f"Настройки уведомлений:  {settings=}  ------- ")
            morning_time = settings[0] if settings and len(settings) > 0 else "Not set"  # CHECK LENGHT
            evening_time = settings[1] if settings and len(settings) > 1 else "Not set"  # CHECK LENGHT

            # Получаем имя пользователя
            cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user.id,))
            name_data = cursor.fetchone()
            logger.info(f" Имя пользователя:  {name_data=}  -------- ")

            logger.info(f" {settings=}  ------- ")
            morning_time = settings[0] if settings and len(settings) > 0 else "Not set"  # CHECK LENGHT
            evening_time = settings[1] if settings and len(settings) > 1 else "Not set"  # CHECK LENGHT

            # Get username
            cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user.id,))
            name_data = cursor.fetchone()
            logger.info(f" {name_data=}  -------- ")

            if name_data and len(name_data) > 0:
                full_name = name_data[0]
            else:
                full_name = "Пользователь"
                logger.warning(f"Не найдено имя пользователя {user.id} в базе данных")
            logger.info(f" {full_name=}  --------- ")

            # Получаем статус домашнего задания
            homework = await MenuManager.get_homework_status_text(self, conn, cursor, user.id, active_course_id_full)

            logger.info(f" {homework=}  --------- ")

            lesson_files = MenuManager.get_lesson_files(self, user.id, progress, active_course_id)
            logger.info(f" {lesson_files=}  --------- ")

            # Removing this as it should happen only on "lesson" button press
            # last_lesson = await check_last_lesson(conn, cursor, update, context)
            # logger.info(f" {last_lesson=}  --------- ")

            # Debug state
            if context.user_data and context.user_data.get("waiting_for_code"):
                state_emoji = "🔑"  # Key emoji for 'waiting_for_code' state
            else:
                state_emoji = "✅"  # Checkmark for other states

            progress_text = f"Текущий урок: {progress}" if progress else "--"
            greeting = f"""Приветствую, {full_name.split()[0]}! {state_emoji}
                Курс: {active_course_id} ({course_type}) {active_tariff}
                Прогресс: {progress_text}
                Домашка: {homework}     Для СамоОдобрения введи потом  /self_approve_{progress}"""


            # Make buttons
            keyboard = [
                [
                    InlineKeyboardButton("📚 Текущий Урок - повтори всё", callback_data="get_current_lesson"),
                    InlineKeyboardButton("🖼 Галерея ДЗ", callback_data="gallery"),
                ],
                [
                    InlineKeyboardButton(
                        f"⚙ Настройка Курса ⏰({morning_time}, {evening_time})",
                        callback_data="course_settings",
                    )
                ],
                [
                    InlineKeyboardButton("💰 Тарифы и Бонусы <- тут много", callback_data="tariffs"),
                ],
                [InlineKeyboardButton("🙋 ПоДдержка", callback_data="support")],
            ]

            # ADD DYNAMIC BUTTON для предварительных материалов
            # Find lesson
            next_lesson = progress + 1

            # If lesson available add it
            lessons = MenuManager.get_preliminary_materials(self, active_course_id, next_lesson)
            if len(lessons) > 0 and not (homework.startswith("есть")):
                keyboard.insert(
                    0,
                    [
                        InlineKeyboardButton(
                            "🙇🏼Предварительные материалы к след. уроку",
                            callback_data="preliminary_tasks",
                        )
                    ],
                )

            # Кнопка самоодобрения для тарифа self_check
            if active_tariff == "self_check":
                keyboard.insert(
                    0,
                    [
                        InlineKeyboardButton(
                            "✅ Самоодобрение ДЗ",
                            callback_data=f"self_approve_{progress}"
                        )
                    ],
                )

            reply_markup = InlineKeyboardMarkup(keyboard)

            logger.info(f" pre #Send menu  ---------- ")
            # Send menu
            try:
                await safe_reply(update, context, greeting, reply_markup=reply_markup)
            except TelegramError as e:
                logger.error(f"Telegram API error: {e}")
                await context.bot.send_message(user.id, "Произошла ошибка. Попробуйте позже.")

        except Exception as e:
            logger.error(f"time {time.strftime('%H:%M:%S')} Error in show_main_menu: {str(e)}")
            await safe_reply(update, context, "Error display menu. Try later.")
            return ConversationHandler.END


        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_reply(update, context, "Главное меню:", reply_markup=reply_markup)

    @db_handler
    async def handle_gallery(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """
        Обработчик кнопки 'Галерея работ'.
        """
        query = update.callback_query
        await query.answer()  # Подтверждаем получение callback
        await safe_reply(update, context, "Здесь будет галерея работ.")

    @db_handler
    async def handle_tariffs(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """
        Обработчик кнопки 'Тарифы'.
        """
        query = update.callback_query
        await query.answer()
        await safe_reply(update, context, "Здесь будет информация о тарифах.")

    @db_handler
    async def handle_course_settings(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """
        Обработчик кнопки 'Настройки курса'.
        """
        query = update.callback_query
        await query.answer()
        await safe_reply(update, context, "Здесь будут настройки курса.")

    @db_handler
    async def handle_statistics(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """
        Обработчик кнопки 'Статистика'.
        """
        query = update.callback_query
        await query.answer()
        await safe_reply(update, context, "Здесь будет статистика обучения.")

    @db_handler
    async def handle_support(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """
        Обработчик кнопки 'Поддержка'.
        """
        query = update.callback_query
        await query.answer()
        await safe_reply(update, context, "Если у вас есть вопросы, свяжитесь с поддержкой.")

    @db_handler
    async def info_command(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """Shows bot information."""
        info_text = (
            "ℹ️ Информация о боте:\n\n"
            "Этот бот поможет вам в обучении и управлении курсами.\n"
            "Используйте /help для просмотра доступных команд."
        )
        await safe_reply(update, context, info_text)

    @db_handler
    async def admins_command(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """
        Команда /admins — показывает контакты администраторов.
        """
        logger.info(f"Отображение списка администраторов: {ADMIN_IDS}")

        if not ADMIN_IDS:
            await safe_reply(update, context, "Список администраторов пуст.")
            return

        admin_text = "👨‍💼 Контакты администраторов:\n"
        for admin_id in ADMIN_IDS:
            admin_text += f"@{admin_id}\n"

        await safe_reply(update, context, admin_text)

    @db_handler
    async def reminders(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """Shows reminder settings."""
        reminder_text = (
            "⏰ Настройки напоминаний:\n\n"
            "Используйте следующие команды:\n"
            "/set_morning - установить утреннее напоминание\n"
            "/set_evening - установить вечернее напоминание\n"
            "/disable_reminders - отключить напоминания"
        )
        await safe_reply(update, context, reminder_text)

    @db_handler
    async def set_morning(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """Sets morning reminder time."""
        # Implementation for setting morning reminder
        await safe_reply(update, context, "Утреннее напоминание установлено на 9:00")

    @db_handler
    async def set_evening(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """Sets evening reminder time."""
        # Implementation for setting evening reminder
        await safe_reply(update, context, "Вечернее напоминание установлено на 20:00")

    @db_handler
    async def disable_reminders(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """Disables all reminders."""
        # Implementation for disabling reminders
        await safe_reply(update, context, "Все напоминания отключены")

    @db_handler
    async def show_course_settings(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """Shows course settings menu."""
        keyboard = [
            [InlineKeyboardButton("🔔 Напоминания", callback_data="reminders")],
            [InlineKeyboardButton("📱 Уведомления", callback_data="notifications")],
            [InlineKeyboardButton("Назад", callback_data="menu_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_reply(update, context, "⚙️ Настройки курса:", reply_markup=reply_markup)

    @db_handler
    async def show_statistics(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
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

    @db_handler
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

    @db_handler
    async def handle_homework_actions(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
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

    @db_handler
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

    @db_handler
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

    @db_handler
    async def send_homework_feedback(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
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

