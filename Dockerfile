# Используем образ Python 3.11 в качестве базового
FROM python:3.11-slim-buster

# Устанавливаем переменные окружения
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Создаем рабочую директорию
WORKDIR /app

# Копируем requirements.txt и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы проекта в рабочую директорию
COPY . .

# Устанавливаем права на исполнение для скрипта запуска
RUN chmod +x run.sh

# Запускаем бота
CMD ["./run.sh"]
