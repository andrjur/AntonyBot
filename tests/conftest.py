# tests/conftest.py
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_db_connection(mocker):
    """Мок соединения с базой данных."""
    mock_conn = MagicMock()
    mock_conn.cursor = MagicMock()  # Мокируем cursor как MagicMock
    mock_conn.commit = MagicMock()  # Мокируем commit как MagicMock
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mocker.patch("sqlite3.connect", return_value=mock_conn)
    return mock_conn, mock_cursor
