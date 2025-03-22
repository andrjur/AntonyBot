#course_manager.py
import os
import asyncio
import random
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
from telegram.constants import ParseMode

from constants import (
    DEFAULT_LESSON_INTERVAL,
    ADMIN_IDS
)
from utils import safe_reply, handle_telegram_errors, db_handler
from lessons import get_lesson_text, get_lesson_files
from database import load_delay_messages, DELAY_MESSAGES_FILE, DatabaseConnection  # Add this import

logger = logging.getLogger(__name__)

# Load delay messages at module level
DELAY_MESSAGES = load_delay_messages(DELAY_MESSAGES_FILE)

class Course:
    def __init__(self, course_id, course_name, course_type, code_word, price_rub=None, price_tokens=None):
        self.course_id = course_id
        self.course_name = course_name
        self.course_type = course_type
        self.code_word = code_word
        self.tariff = course_id.split('_')[1] if '_' in course_id else 'default'
        self.price_rub = price_rub
        self.price_tokens = price_tokens

    def __str__(self):
        return f"Course(id={self.course_id}, name={self.course_name}, type={self.course_type}, code={self.code_word}, price_rub={self.price_rub}, price_tokens={self.price_tokens})"

class CourseManager:
    def __init__(self, db):
        self.token_manager = None
        self.stats_manager = None
        self.db = db

    @handle_telegram_errors
    async def handle_homework(self, update: Update, context: CallbackContext):
        """
        Обрабатывает отправку домашнего задания (фото/документ) и сохраняет его в БД.
        """
        user_id = update.effective_user.id
        try:
            # Определяем тип файла
            file_type = None
            file_id = None

            if update.message.photo:
                file_type = "photo"
                file_id = update.message.photo[-1].file_id
            elif update.message.document:
                mime_type = update.message.document.mime_type
                if mime_type.startswith("image/"):
                    file_type = "photo"
                else:
                    file_type = "document"
                file_id = update.message.document.file_id

            if not file_type:
                await safe_reply(update, context, "Формат файла не поддерживается. Отправьте фото или документ.")
                return

            # Сохраняем в БД
            cursor = self.db.get_cursor()
            conn = self.db.get_connection()

            cursor.execute(
                """
                INSERT INTO homeworks (user_id, course_id, lesson, file_id, file_type, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (
                    user_id,
                    context.user_data.get("active_course_id"),
                    context.user_data.get("current_lesson"),
                    file_id,
                    file_type
                )
            )
            conn.commit()

            # Уведомляем администраторов
            for admin_id in ADMIN_IDS:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"Пользователь {user_id} отправил домашнее задание к уроку {context.user_data.get('current_lesson')}."
                )

            await safe_reply(update, context, "Домашнее задание отправлено на проверку!")

        except Exception as e:
            logger.error(f"Ошибка при отправке домашнего задания: {e}")
            await safe_reply(update, context, "Произошла ошибка. Попробуйте позже.")

    # Отображает настройки курса *
    async def show_course_settings(self, update: Update,context: CallbackContext):
        """Отображает настройки курса."""
        conn = self.db.get_connection()
        cursor = self.db.get_cursor()
        logger.info("388 получили conn  и cursor")

        user = update.effective_user if update.effective_user else None
        if user is None:
            logger.error("Could not get user - effective_user is None")
            return ConversationHandler.END

        logger.info("389 получили user")

        user_id = user.id

        logger.error(f"show_course_settings {user_id}")
        try:
            # Получаем времена уведомлений из базы данных
            cursor.execute(
                "SELECT morning_notification, evening_notification FROM user_settings WHERE user_id = ?",
                (user_id,),
            )
            settings = cursor.fetchone()
            morning_time = settings[0] if settings else "Не установлено"
            evening_time = settings[1] if settings else "Не установлено"

            # Формируем сообщение с настройками
            text = (
                f"Ваши текущие настройки:\n\n"
                f"⏰ Утреннее напоминание: {morning_time}\n"
                f"🌙 Вечернее напоминание: {evening_time}\n\n"
                f"Вы можете изменить эти настройки через соответствующие команды."
            )

            await safe_reply(update, context, text)

        except Exception as e:
            logger.error(f"Ошибка при отображении настроек курса для пользователя {user_id}: {e}")
            await safe_reply(update, context, "Произошла ошибка при загрузке настроек. Попробуйте позже.")

    async def handle_course_callback(self, update: Update, context: CallbackContext):
        """
        Обрабатывает callback-запросы, связанные с курсами (например, переход к следующему уроку).
        """
        query = update.callback_query
        if not query:
            logger.warning("Callback query is None")
            return

        data = query.data
        try:
            if data == "next_lesson":
                await self._handle_next_lesson(update, context)
            elif data == "show_homework_status":
                await self._show_homework_status(update, context)
            # Добавьте другие callback'ы по аналогии
            else:
                await query.answer("Неизвестная команда")

        except Exception as e:
            logger.error(f"Ошибка в handle_course_callback: {e}")
            await safe_reply(update, context, "Произошла ошибка. Попробуйте позже.")

    async def course_management(self, update: Update, context: CallbackContext):
        """
        Управление курсами (для администраторов):
        показ статистики, редактирование курсов, начисление бонусов.
        """
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            await safe_reply(update, context, "Доступ запрещен.")
            return

        # Пример команд для управления курсами
        text = update.message.text.lower()
        if text.startswith("/stats"):
            await self.stats_manager.show_stats(update, context)
        elif text.startswith("/bonus"):
            await self._admin_add_bonus(update, context)
        else:
            await safe_reply(update, context, "Неизвестная команда управления курсами.")

    async def _admin_add_bonus(self, update: Update, context: CallbackContext):
        # Начисление бонусов
        args = context.args
        if len(args) < 2:
            await safe_reply(update, context, "Используйте: /bonus [user_id] [amount]")
            return

        target_user_id = int(args[0])
        amount = int(args[1])
        await self.token_manager.add_tokens(target_user_id, amount, "admin_bonus", update, context)
        await safe_reply(update, context, f"Бонус {amount} начислен пользователю {target_user_id}")

    # В course_manager.py
    async def get_current_lesson(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        logger.info(f"777 get_current_lesson: user_id={user_id} {context=}")
        try:
            # Определяем источник вызова
            if update.message:  # Если это команда
                user_id = update.message.from_user.id
                logger.info(f" 111 update.message.from_user.id={user_id} ")
                message = update.message
            elif update.callback_query:  # Если это callback
                user_id = update.callback_query.from_user.id
                logger.info(f" 222 update.callback_query.from_user.id={user_id} ")
                message = update.callback_query.message
                await update.callback_query.answer()  # Подтверждаем получение callback
            else:
                logger.error("555 Неизвестный источник вызова get_current_lesson")
                return

            # Получаем active_course_id из базы данных
            cursor = self.db.cursor()
            cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
            active_course_data = cursor.fetchone()

            if not active_course_data or not active_course_data[0]:
                await safe_reply(update, context, "Активируйте курс через кодовое слово.")
                return

            active_course_id_full = active_course_data[0]
            active_course_id = active_course_id_full.split("_")[0]

            # Получаем progress (номер урока) из user_courses
            cursor.execute(
                "SELECT progress FROM user_courses WHERE user_id = ? AND course_id = ?",
                (user_id, active_course_id_full),
            )
            progress_data = cursor.fetchone()
            lesson = progress_data[0] if progress_data else 1

            if not progress_data:
                await safe_reply(update, context, "Начинаем с первого урока.")

            # Отправляем материалы урока
            await self.process_lesson(user_id, lesson, active_course_id, context)

            # Рассчитываем время следующего урока
            next_lesson = lesson + 1
            next_lesson_release_time = datetime.now() + timedelta(hours=DEFAULT_LESSON_INTERVAL)
            next_lesson_release_str = next_lesson_release_time.strftime("%d-%m-%Y %H:%M:%S")

            await safe_reply(
                update,
                context,
                f"Следующий урок {next_lesson} будет доступен {next_lesson_release_str}.",
            )

        except Exception as e:
            logger.error(f"22 Ошибка при получении текущего урока: {e}")
            await safe_reply(update, context, "Ошибка при получении урока. Попробуйте позже.")

    async def old_get_current_lesson(self, update: Update, context: CallbackContext):
        """Отправляет все материалы текущего урока."""
        user_id = update.effective_user.id
        logger.info(f"777 get_current_lesson: user_id={user_id} {context=}")
        logger.info(f"Проверка db: {self.db}")

        try:
            # Get active_course_id from users
            logger.info(f"11 пе")
            logger.info(f"12 пробуем context.bot_data {context.bot_data}")

            logger.info(f"13 пробуем self.db {self.db=}")
            cursor = self.db.cursor()
            logger.info(f"14 зато cursor {cursor=}")


            logger.info(f" до запроса {cursor=}")
            cursor.execute("SELECT active_course_id FROM users WHERE user_id = ?", (user_id,))
            active_course_data = cursor.fetchone()
            logger.info(f"пока норм: получили длина {len(active_course_data)} сама дата: {active_course_data}")

            if not active_course_data or not active_course_data[0]:
                await safe_reply(update, context, "Активируйте курс через кодовое слово.")
                return

            active_course_id_full = active_course_data[0]
            active_course_id = active_course_id_full.split("_")[0]
            logger.info(f"active_course_id: {active_course_id}")

            # Get progress from user_courses
            cursor.execute(
                "SELECT progress FROM user_courses WHERE user_id = ? AND course_id = ?",
                (user_id, active_course_id_full),
            )
            progress_data = cursor.fetchone()

            # If no progress found, start with lesson 1
            if not progress_data:
                lesson = 1
                cursor.execute(
                    "INSERT INTO user_courses (user_id, course_id, course_type, progress, tariff) VALUES (?, ?, ?, ?, ?)",
                    (user_id, active_course_id_full, context.user_data.get("course_type", "main"), lesson, context.user_data.get("tariff", "self_check")),
                )
                await context.bot_data['db'].commit()
                await safe_reply(update, context, "Вы начинаете курс с первого урока.")
            else:
                lesson = progress_data[0]

            await self.process_lesson(user_id, lesson, active_course_id, context)

            # Calculate next lesson time
            next_lesson = lesson + 1
            next_lesson_release_time = datetime.now() + timedelta(hours=DEFAULT_LESSON_INTERVAL)
            next_lesson_release_str = next_lesson_release_time.strftime("%d-%m-%Y %H:%M:%S")
            await safe_reply(
                update, 
                context,
                f"Следующий урок {next_lesson} будет доступен {next_lesson_release_str}."
            )

        except Exception as e:
            logger.error(f"Ошибка при получении текущего урока: {e}")
            await safe_reply(update, context, "Ошибка при получении текущего урока. Попробуйте позже.")

    async def process_lesson(self, user_id, lesson_number, active_course_id, context):
        """Обрабатывает текст урока и отправляет связанные файлы."""
        try:
            # Get lesson text
            lesson_data = get_lesson_text(lesson_number, active_course_id)
            if lesson_data:
                lesson_text, parse_mode = lesson_data
                try:
                    await context.bot.send_message(
                        chat_id=user_id, 
                        text=lesson_text, 
                        parse_mode=parse_mode
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке текста урока: {e}")
                    await context.bot.send_message(
                        chat_id=user_id, 
                        text="Ошибка при отправке текста урока."
                    )
            else:
                await context.bot.send_message(
                    chat_id=user_id, 
                    text="Текст урока не найден."
                )

            # Get and send lesson files
            lesson_files = get_lesson_files(user_id, lesson_number, active_course_id)
            tasks = [self.send_file(file_info, user_id, context) for file_info in lesson_files]
            await asyncio.gather(*tasks)

        except Exception as e:
            logger.error(f"Ошибка при обработке урока: {e}")
            await context.bot.send_message(
                chat_id=user_id, 
                text="Произошла ошибка при обработке урока."
            )

    @db_handler
    async def send_file(self, update: Update, context: CallbackContext, conn, cursor, user, user_id, file_info):
        """Отправляет файл с учетом задержки."""
        file_path = file_info["path"]
        file_type = file_info["type"]
        delay = file_info["delay"]

        try:
            if delay > 0:
                delay_message = random.choice(DELAY_MESSAGES)
                logger.info(f"Ожидание {delay} секунд перед отправкой файла {file_path}")
                await context.bot.send_message(chat_id=user_id, text=delay_message)
                await asyncio.sleep(delay)

            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Файл не найден: {file_path}")

            with open(file_path, "rb") as file:
                if file_type == "photo":
                    await context.bot.send_photo(chat_id=user_id, photo=file)
                elif file_type == "video":
                    await context.bot.send_video(chat_id=user_id, video=file)
                elif file_type == "audio":
                    await context.bot.send_audio(chat_id=user_id, audio=file)
                else:
                    await context.bot.send_document(chat_id=user_id, document=file)

        except FileNotFoundError:
            logger.error(f"Файл не найден: {file_path}")
            await context.bot.send_message(
                chat_id=user_id, 
                text=f"Файл не найден: {file_path}"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке файла {file_path}: {e}")
            await context.bot.send_message(
                chat_id=user_id, 
                text=f"Ошибка при отправке файла: {e}"
            )

    @db_handler
    async def handle_homework_approval(self, update: Update, context: CallbackContext, conn, cursor, user, user_id):
        """  Обрабатывает подтверждение/отклонение домашнего задания администратором.
        Ожидаемый формат callback_data: hw_(approve|reject)_<hw_id> """
        query = update.callback_query
        if not query:
            logger.warning("Callback query is None in handle_homework_approval")
            return

        try:
            data = query.data.split("_")
            action, hw_id = data[1], int(data[2])
            new_status = "approved" if action == "approve" else "rejected"


            # Получаем информацию о пользователе и уроке
            cursor.execute("SELECT user_id, lesson FROM homeworks WHERE hw_id = ?", (hw_id,))
            result = cursor.fetchone()
            if not result:
                await query.answer("Домашнее задание не найдено.")
                return

            user_id, lesson = result

            # Обновляем статус в БД
            cursor.execute(
                """
                UPDATE homeworks 
                SET status = ?, approval_time = datetime('now')
                WHERE hw_id = ?
                """,
                (new_status, hw_id)
            )
            conn.commit()

            # Уведомляем пользователя
            user_message = (
                f"✅ Ваше домашнее задание к уроку {lesson} одобрено!"
                if new_status == "approved"
                else f"❌ Ваше домашнее задание к уроку {lesson} отклонено. Попробуйте отправить снова."
            )
            await context.bot.send_message(chat_id=user_id, text=user_message)

            # Уведомляем администратора
            await query.answer(f"Домашнее задание {new_status}!")
            await query.edit_message_text(f"Статус домашнего задания изменен на: {new_status}")

        except Exception as e:
            logger.error(f"Error in handle_homework_approval: {e}")
            await query.answer("Ошибка при обработке запроса. Попробуйте позже.")
            await safe_reply(update, context, "Произошла ошибка. Попробуйте позже.")

#course_manager = CourseManager()
