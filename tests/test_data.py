# tests/test_data.py

TEST_COURSE_DATA = [
    {
        "course_id": "femininity_premium",
        "course_name": "Курс женственности",
        "course_type": "main",
        "tariff": "premium",
        "code_word": "femininity123"
    },
    {
        "course_id": "self_development_basic",
        "course_name": "Саморазвитие",
        "course_type": "auxiliary",
        "tariff": "basic",
        "code_word": "selfdev456"
    }
]

TEST_TARIFFS_DATA = [
    {
        "id": "premium",
        "title": "Премиум",
        "description": "Полный доступ ко всем материалам",
        "price": 5000,
        "type": "payment"
    },
    {
        "id": "basic",
        "title": "Базовый",
        "description": "Ограниченный доступ",
        "price": 2000,
        "type": "payment"
    }
]