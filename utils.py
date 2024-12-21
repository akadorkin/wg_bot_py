# utils.py

import asyncio
import os
from pathlib import Path
import aiofiles
import zipfile
from datetime import datetime
from config import (
    AUTHORIZED_USERS_FILE,
    BANNED_USERS_FILE,
    KEYS_ISSUED_FILE,
    KEYS_LOG_FILE,
    SUPPORT_REQUESTS_FILE,
    SITE_EXCEPTIONS_FILE,
    CONFIGS_DIR,
    KEY_LIMIT_FILE,
    USER_LIMITS_FILE
)
import logging

logger = logging.getLogger(__name__)

DEFAULT_GLOBAL_LIMIT = 10

# Асинхронное чтение файла
async def read_file(file_path: str) -> list:
    """
    Асинхронно читает файл и возвращает список строк.
    """
    if not os.path.exists(file_path):
        return []
    async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
        contents = await f.readlines()
    return [line.strip() for line in contents]

# Асинхронное добавление строки в конец файла
async def append_to_file(file_path: str, data: str):
    """
    Асинхронно добавляет строку в конец файла.
    """
    path = Path(file_path)
    async with aiofiles.open(file_path, mode='a', encoding='utf-8') as f:
        await f.write(f"{data}\n")

# Асинхронная перезапись файла (полное)
async def write_file(file_path: str, lines: list):
    """
    Асинхронно записывает список строк в файл, перезаписывая его.
    """
    path = Path(file_path)
    async with aiofiles.open(file_path, mode='w', encoding='utf-8') as f:
        for line in lines:
            await f.write(f"{line}\n")

# Асинхронное удаление строки из файла
async def remove_from_file(file_path: str, data: str):
    """
    Асинхронно удаляет строку из файла.
    """
    path = Path(file_path)
    if not path.exists():
        return
    lines = await read_file(file_path)
    lines = [line for line in lines if line != data]
    await write_file(file_path, lines)

# Логирование выдачи ключа
async def log_key_issuance(user_id: int, username: str, key_filename: str):
    """
    Логирует выдачу ключа в keys_log.txt и keys_issued.txt.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"{timestamp} - User: {username} (ID: {user_id}) - Key: {key_filename}"
    issued_entry = f"{user_id}:{key_filename}"
    
    await append_to_file(KEYS_LOG_FILE, log_entry)
    await append_to_file(KEYS_ISSUED_FILE, issued_entry)

# Проверка, выдавался ли уже ключ
async def check_key_issued(user_id: int) -> bool:
    """
    Проверяет, был ли уже выдан ключ пользователю.
    """
    issued_keys = await read_file(KEYS_ISSUED_FILE)
    return any(line.startswith(f"{user_id}:") for line in issued_keys)

# Маркировка ключа как выданного
async def mark_key_issued(user_id: int, key_filename: str):
    """
    Маркирует ключ как выданный пользователю.
    """
    entry = f"{user_id}:{key_filename}"
    await append_to_file(KEYS_ISSUED_FILE, entry)

# Получение доступных конфигурационных файлов
async def get_conf_files() -> list:
    """
    Возвращает список доступных .conf файлов.
    """
    if not os.path.exists(CONFIGS_DIR):
        return []
    return [f for f in os.listdir(CONFIGS_DIR) if f.endswith('.conf')]

# Обновление статистики пользователя
async def update_user_stats(user_id: int):
    """
    Обновляет статистику использования ключей пользователем.
    """
    stats = await load_user_stats()
    stats[user_id] = stats.get(user_id, 0) + 1
    # Записываем обновлённую статистику
    await append_to_file(KEYS_LOG_FILE, f"{user_id}:stats:{stats[user_id]}")

# Загрузка статистики пользователей
async def load_user_stats() -> dict:
    """
    Загружает статистику пользователей из keys_log.txt.
    """
    stats = {}
    issued_keys = await read_file(KEYS_LOG_FILE)
    for line in issued_keys:
        # Предполагается формат:
        # timestamp - User: username (ID: user_id) - Key: filename.conf
        if f"(ID: " in line and "stats" in line:
            parts = line.split(':')
            if len(parts) >= 3 and parts[1].strip() == 'stats':
                try:
                    user_id = int(parts[0])
                    count = int(parts[2])
                    stats[user_id] = count
                except:
                    continue
    return stats

# Добавление сайтов в исключения
async def add_site_exceptions(url: str):
    """
    Добавляет сайт в исключения, если его там ещё нет.
    """
    existing_exceptions = await read_file(SITE_EXCEPTIONS_FILE)
    if url not in existing_exceptions:
        await append_to_file(SITE_EXCEPTIONS_FILE, url)
        return [url], existing_exceptions + [url]
    else:
        return [], existing_exceptions

# Извлечение .conf файлов из zip архива
async def extract_conf_files_from_zip(zip_path: str) -> tuple:
    """
    Извлекает .conf файлы из zip архива и сохраняет их в CONFIGS_DIR.
    Возвращает кортеж (количество добавленных файлов, количество заменённых файлов).
    """
    added = 0
    replaced = 0

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            conf_files = [
                f for f in zip_ref.namelist()
                if f.endswith('.conf') and not f.startswith('__MACOSX/') and not os.path.basename(f).startswith('._')
            ]
            for file in conf_files:
                extracted_path = zip_ref.extract(file, path=CONFIGS_DIR)
                target_path = os.path.join(CONFIGS_DIR, os.path.basename(file))
                
                if os.path.exists(target_path):
                    replaced += 1
                else:
                    added += 1

                await asyncio.to_thread(os.replace, extracted_path, target_path)

        return added, replaced
    except zipfile.BadZipFile:
        logger.error(f"Недействительный ZIP архив: {zip_path}")
        return -1, -1
    except Exception as e:
        logger.error(f"Ошибка при извлечении ZIP архива {zip_path}: {e}")
        return -1, -1

# Получение количества ключей у пользователя
async def get_user_keys_count(user_id: int) -> int:
    """
    Подсчитывает количество выданных ключей пользователю из keys_log.txt.
    """
    keys_log = await read_file(KEYS_LOG_FILE)
    count = 0
    for line in keys_log:
        # Предполагается формат:
        # timestamp - User: username (ID: user_id) - Key: filename.conf
        if f"(ID: {user_id})" in line and "Key:" in line:
            count += 1
    return count

# Функции для лимитов
async def get_global_limit() -> int:
    """
    Возвращает глобальный лимит ключей. Если файл не существует или содержит некорректные данные, возвращает DEFAULT_GLOBAL_LIMIT.
    """
    if not os.path.exists(KEY_LIMIT_FILE):
        return DEFAULT_GLOBAL_LIMIT
    lines = await read_file(KEY_LIMIT_FILE)
    if not lines:
        return DEFAULT_GLOBAL_LIMIT
    try:
        return int(lines[0])
    except:
        return DEFAULT_GLOBAL_LIMIT

async def set_global_limit(new_limit: int):
    """
    Устанавливает новый глобальный лимит ключей.
    """
    await write_file(KEY_LIMIT_FILE, [str(new_limit)])

async def get_user_limit(user_id: int) -> int:
    """
    Возвращает индивидуальный лимит ключей пользователя.
    Если лимит не установлен, возвращает глобальный лимит.
    """
    # Если нет записи для пользователя, возвращаем глобальный лимит
    user_limits = await read_file(USER_LIMITS_FILE)
    user_limit_dict = {}
    for line in user_limits:
        parts = line.split(':')
        if len(parts) == 2:
            uid, limit = parts
            try:
                user_limit_dict[int(uid)] = int(limit)
            except:
                continue
    if user_id in user_limit_dict:
        return user_limit_dict[user_id]
    # Иначе глобальный
    return await get_global_limit()

async def set_user_limit(user_id: int, limit: int):
    """
    Устанавливает индивидуальный лимит ключей для пользователя.
    """
    user_limits = await read_file(USER_LIMITS_FILE)
    # Создаём словарь текущих лимитов
    user_limit_dict = {}
    for line in user_limits:
        parts = line.split(':')
        if len(parts) == 2:
            uid, l = parts
            try:
                user_limit_dict[int(uid)] = int(l)
            except:
                continue
    # Устанавливаем или обновляем лимит для пользователя
    user_limit_dict[user_id] = limit

    # Перезаписываем файл с обновлёнными лимитами
    lines = [f"{uid}:{l}" for uid, l in user_limit_dict.items()]
    await write_file(USER_LIMITS_FILE, lines)