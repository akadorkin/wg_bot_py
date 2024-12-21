# main.py

import logging
import os
import aiofiles  # Асинхронное чтение и запись файлов
from aiogram import Bot, Dispatcher
from aiogram.types import ParseMode
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from config import (
    API_TOKEN,
    AUTHORIZED_USER_ID,
    CONFIGS_DIR,
    USERS_DIR,
    DATA_DIR,
    KEY_LIMIT_FILE,
    USER_LIMITS_FILE
)
from handlers import register_handlers, set_bot_instance
from utils import read_file, append_to_file, write_file
from logging.handlers import TimedRotatingFileHandler
from dotenv import load_dotenv

# Загрузка переменных окружения из .env
load_dotenv()

# Настройка логирования
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

handler = TimedRotatingFileHandler(
    filename=os.path.join(log_dir, 'bot.log'),
    when='midnight',
    interval=1,
    backupCount=7,
    encoding='utf-8',
    delay=False,
    utc=False
)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Установка экземпляра бота для других модулей
set_bot_instance(bot)

# Регистрация обработчиков
register_handlers(dp)

# Функция инициализации проекта
async def initialize_project():
    """
    Создаёт необходимые директории и файлы при первом запуске бота.
    """
    required_dirs = [DATA_DIR, CONFIGS_DIR, USERS_DIR, log_dir]
    for directory in required_dirs:
        if not os.path.exists(directory):
            os.makedirs(directory)
            logger.info(f"Создана директория: {directory}")

    data_files = {
        'authorized_users.txt': [],
        'banned_users.txt': [],
        'keys_issued.txt': [],
        'keys_log.txt': [],
        'support_requests.txt': [],
        'exceptions.txt': [],
        'key_limit.txt': ['10'],  # Устанавливаем глобальный лимит по умолчанию
        'user_limits.txt': [],
        'user_keys_count.txt': []
    }

    for filename, default_content in data_files.items():
        file_path = os.path.join(USERS_DIR, filename)
        if not os.path.exists(file_path):
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                if default_content:
                    for line in default_content:
                        await f.write(f"{line}\n")
            logger.info(f"Создан файл: {file_path} с начальным содержимым.")

    # Проверяем, существует ли ключевой лимит, если нет - создаём его
    if not os.path.exists(KEY_LIMIT_FILE):
        await write_file(KEY_LIMIT_FILE, ['10'])  # Устанавливаем глобальный лимит по умолчанию
        logger.info(f"Создан файл с глобальным лимитом ключей: {KEY_LIMIT_FILE}")

    # Проверяем, существует ли файл индивидуальных лимитов пользователей
    if not os.path.exists(USER_LIMITS_FILE):
        await write_file(USER_LIMITS_FILE, [])
        logger.info(f"Создан файл с индивидуальными лимитами пользователей: {USER_LIMITS_FILE}")

# Функция, выполняемая при старте бота
async def on_startup(dispatcher):
    await initialize_project()
    logger.info("🚀 Бот запущен и инициализирован.")

if __name__ == '__main__':
    from aiogram import executor

    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
    
    