# Используем официальный образ Python 3.9-slim в качестве базового
FROM python:3.9-slim

# Устанавливаем переменные окружения
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы зависимостей и устанавливаем их
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код проекта
COPY . .

# Определяем команду запуска бота
CMD ["python", "main.py"]