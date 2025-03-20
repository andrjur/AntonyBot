import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from database import DatabaseConnection
from utils import safe_reply
import random

logger = logging.getLogger(__name__)

class GalleryManager:
    def __init__(self):
        self.db = DatabaseConnection()

    async def get_gallery_count(self) -> int:
        """Counts the number of approved works in the gallery."""
        cursor = self.db.get_cursor()
        cursor.execute('SELECT COUNT(*) FROM homeworks WHERE status = "approved"')
        logger.info("get_gallery_count -------------<")
        return cursor.fetchone()[0]

    async def show_gallery(self, update: Update, context: CallbackContext):
        """Shows gallery of homework submissions."""
        logger.info("show_gallery -------------< и сразу ныряем в get_random_homework")
        await self.get_random_homework(update, context)

    async def get_random_homework(self, update: Update, context: CallbackContext):

        """Get a random homework."""
        user_id = update.effective_user.id if update.effective_user else None
        logger.info(f"get_random_homework -------------< for user_id {user_id}")
        
        if user_id is None:
            logger.error("Could not get user ID - effective_user is None")
            return

        cursor = self.db.get_cursor()
        try:
            # Get the course_id associated with the user
            cursor.execute(
                """
                SELECT uc.course_id
                FROM user_courses uc
                WHERE uc.user_id = ?
                """,
                (user_id,),
            )
            user_course_data = cursor.fetchone()
            if not user_course_data:
                logger.warning("Пользователь не имеет активного курса.")
                await safe_reply(update, context, "У вас нет активного курса. Активируйте курс через кодовое слово.")
                return

            course_id = user_course_data[0]

            # Get a random homework submission for the course
            cursor.execute(
                """
                SELECT hw_id, file_id, file_type
                FROM homeworks
                WHERE course_id = ? AND file_type in ('photo','document')
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (course_id,),
            )

            homework = cursor.fetchone()
            if homework:
                hw_id, file_id, file_type = homework
                logger.info(f"file_id={file_id} and hw_id {hw_id}")

                try:
                    if file_type == "photo":
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=file_id,
                            caption=f"Домашняя работа - hw_id {hw_id}"
                        )
                    elif file_type == "document":
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=file_id,
                            caption=f"Домашняя работа - hw_id {hw_id}"
                        )
                except Exception as e:
                    logger.error(f"Ошибка при отправке файла: {e}")
                    await safe_reply(update, context, "Произошла ошибка при загрузке работы. Попробуйте позже.")
            else:
                await safe_reply(update, context, "К сожалению, работы пока не загружены. Будьте первым!")

        except Exception as e:
            logger.exception(f"Ошибка при получении случайной работы")
            await safe_reply(update, context, "Произошла ошибка при загрузке работы. Попробуйте позже.")

gallery_manager=GalleryManager()


