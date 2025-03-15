# tests/test_handlers.py

import pytest
from unittest.mock import MagicMock
from telegram import Update, Message, User, Chat
from ..main import handle_code_words, Course  # Импортируем из main.py


@pytest.fixture
def update():
    # Создаем мок для Update
    user = User(id=123, first_name="Test", is_bot=False)
    message = Message(message_id=1, from_user=user, chat=Chat(id=123), text="test123")
    return Update(update_id=1, message=message)


@pytest.fixture
def context():
    # Создаем мок для Context
    context = MagicMock()
    context.user_data = {}
    return context


def test_handle_code_words_valid_code(update, context):
    # Мокируем COURSE_DATA
    COURSE_DATA = {
        "test123": Course(course_id="test_course", course_name="Test Course", course_type="main", tariff="premium",
                          code_word="test123")}

    # Мокируем глобальную переменную
    from main import COURSE_DATA as original_data
    original_data.clear()
    original_data.update(COURSE_DATA)

    # Вызываем функцию
    result = handle_code_words(update, context)

    # Проверяем результат
    assert result == "ACTIVE"  # Ожидаемое состояние
    assert context.user_data.get("waiting_for_code") is False