# tests/test_utils.py
import pytest
from unittest.mock import mock_open, patch
from ..main import load_course_data, get_lesson_files  # Относительный импорт


def test_load_course_data_success(mocker):
    """Тест загрузки данных курса из JSON-файла."""
    mock_file = mock_open(
        read_data='[{"course_id": "test_course", "course_name": "Test Course", "code_word": "test123", "course_type": "main", "tariff": "premium"}]'
    )

    with patch("builtins.open", mock_file):
        result = load_course_data("fake_path.json")

    assert len(result) == 1
    assert "test123" in result
    assert result["test123"].course_name == "Test Course"


def test_get_lesson_files_success(mocker):
    """Тест успешного получения файлов урока."""
    # Мокируем файловую систему
    mocker.patch(
        "os.listdir", return_value=["lesson1.txt", "lesson1.jpg", "lesson1.mp3"]
    )
    mocker.patch("os.path.isfile", return_value=True)

    # Вызываем функцию
    files = get_lesson_files(user_id=123, lesson_number=1, course_id="test_course")

    # Проверяем результат
    assert len(files) == 2  # Только .jpg и .mp3 (не .txt)
    assert files[0]["type"] == "photo"
    assert files[1]["type"] == "audio"


def test_get_lesson_files_no_files(mocker):
    """Тест получения файлов урока, если файлы отсутствуют."""
    # Мокируем файловую систему
    mocker.patch("os.listdir", return_value=[])
    mocker.patch("os.path.isfile", return_value=False)

    # Вызываем функцию
    files = get_lesson_files(user_id=123, lesson_number=1, course_id="test_course")

    # Проверяем результат
    assert len(files) == 0
