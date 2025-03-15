# tests/test_utils.py

import pytest
from unittest.mock import mock_open, patch
from ..main import load_course_data  # Импортируем из main.py


def test_load_course_data_success(mocker):
    # Мокируем открытие файла и его содержимое
    mock_file = mock_open(
        read_data='[{"course_id": "test_course", "course_name": "Test Course", "course_type": "main", "tariff": "premium", "code_word": "test123"}]')

    with patch("builtins.open", mock_file):
        result = load_course_data("fake_path.json")

    assert len(result) == 1
    assert "test123" in result
    assert result["test123"].course_name == "Test Course"