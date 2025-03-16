# tests/test_handlers.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from telegram import Update, Message, User, Chat
from .main import (  # Используем относительный импорт
    handle_homework_submission,
    handle_code_words,
    activate_course,
    self_approve_homework,
    COURSE_DATA,  # Импортируем COURSE_DATA
    Course,  # Импортируем Course
)
from .main import Course, COURSE_DATA  # Import Course and COURSE_DATA


@pytest.mark.asyncio
async def test_activate_course_success(mocker, mock_db_connection):
    """Тест успешной активации курса."""
    mock_conn, mock_cursor = mock_db_connection
    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}
    user_id = 123
    user_code = "роза"  # Убедитесь, что это кодовое слово есть в ваших тестовых данных

    # Мокируем COURSE_DATA (используем MagicMock для имитации Course-объекта)
    COURSE_DATA["роза"] = Course(
        course_id="femininity_self_check",
        course_name="Femininity",
        course_type="main",
        tariff="self_check",
        code_word="роза",
    )

    # Мокируем базу данных (устанавливаем возвращаемое значение для SELECT)
    mock_cursor.fetchone.return_value = (
        None,
    )  # имитируем отсутствие пользователя в базе данных

    # Мокируем функции add_tokens и get_token_balance
    mocker.patch("tests.main.add_tokens", return_value=None)
    mocker.patch("tests.main.get_token_balance", return_value=0)
    mocker.patch("tests.main.get_current_lesson", new_callable=AsyncMock)

    # Вызываем функцию
    from .main import activate_course

    result = await activate_course(update, context, user_id, user_code)

    # Проверяем результат
    assert result == "ACTIVE"
    update.message.reply_text.assert_awaited_once_with(
        "Курс активирован! Вы переходите в главное меню."
    )


@pytest.mark.asyncio
async def test_activate_course_invalid_code(mocker, mock_db_connection):
    """Тест активации курса с неверным кодовым словом."""
    mock_conn, mock_cursor = mock_db_connection
    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    user_id = 123
    user_code = "неверный_код"

    # Вызываем функцию
    from ..main import activate_course

    result = await activate_course(update, context, user_id, user_code)

    # Проверяем результат
    assert result is None
    update.message.reply_text.assert_awaited_once_with(
        "Неверное кодовое слово. Попробуйте еще раз."
    )


@pytest.fixture
def update():
    """Создает мок объекта Update."""
    user = User(id=123, first_name="Test", is_bot=False)
    message = Message(
        message_id=1,
        from_user=user,
        chat=Chat(id=123, type="private"),  # Указываем тип чата
        text="test123",
    )
    return Update(update_id=1, message=message)


@pytest.fixture
def context():
    """Создает мок объекта Context."""
    context = MagicMock()
    context.user_data = {}
    return context


@pytest.mark.asyncio
async def test_handle_homework_submission_success(mocker, mock_db_connection):
    """Тест успешной обработки домашнего задания."""
    mock_conn, mock_cursor = mock_db_connection
    update = MagicMock()
    update.message = MagicMock()  # Создаем мок для message
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock()  # Создаем мок для effective_user
    update.effective_user.id = 123
    update.message.photo = [MagicMock(file_id="file123")]

    # Мокируем базу данных (настраиваем возвращаемые значения)
    mock_cursor.fetchone.return_value = (
        "test_course_1",
    )  # имитируем наличие активного курса

    # Мокируем функцию save_homework
    mocker.patch(
        "botAntony.main.save_homework", new_callable=AsyncMock
    )  # Замените ..main на botAntony.main

    # Вызываем функцию
    from ..main import (
        handle_homework_submission,
    )  # Замените ..main на botAntony.main

    await handle_homework_submission(update, context, mock_conn)

    # Проверяем результат
    update.message.reply_text.assert_awaited_once_with(
        "Домашнее задание отправлено на проверку администратору."
    )


@pytest.mark.asyncio
async def test_handle_homework_submission_no_active_course(mocker, mock_db_connection):
    """Тест обработки домашнего задания без активного курса."""
    mock_conn, mock_cursor = mock_db_connection
    update = MagicMock()
    update.message = MagicMock()  # Создаем мок для message
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock()  # Создаем мок для effective_user
    update.effective_user.id = 123
    update.message.photo = [MagicMock(file_id="file123")]

    # Мокируем базу данных (настраиваем возвращаемые значения)
    mock_cursor.fetchone.return_value = None  # имитируем отсутствие активного курса

    # Вызываем функцию
    from ..main import (
        handle_homework_submission,
    )  # Замените ..main на botAntony.main

    await handle_homework_submission(update, context, mock_conn)

    # Проверяем результат
    update.message.reply_text.assert_awaited_once_with("У вас нет активного курса.")


@pytest.mark.asyncio
async def test_self_approve_homework_success(mocker, mock_db_connection):
    """Тест успешной самопроверки домашнего задания."""
    mock_conn, mock_cursor = mock_db_connection
    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.message = MagicMock()
    update.callback_query.message.edit_text = AsyncMock()
    update.callback_query.data = "self_approve_1"
    context = MagicMock()

    # Мокируем базу данных (настраиваем возвращаемые значения)
    mock_cursor.rowcount = 1  # имитируем успешное обновление записи

    # Вызываем функцию
    from ..main import (
        self_approve_homework,
    )  # Замените ..main на botAntony.main

    await self_approve_homework(update, context, mock_conn)

    # Проверяем результат
    update.callback_query.message.edit_text.assert_awaited_once_with(
        "Домашнее задание подтверждено вами."
    )
