# tests/conftest.py

import json
import pytest

@pytest.fixture
def course_data():
    with open("courses.json", "r", encoding="utf-8") as f:
        return json.load(f)