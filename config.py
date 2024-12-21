import os
from dotenv import load_dotenv
from sys import exit

load_dotenv()

def get_env_variable(var_name: str, required: bool = True) -> str:
    value = os.getenv(var_name)
    if required and not value:
        print(f"Ошибка: переменная окружения {var_name} не задана.")
        exit(1)
    return value

API_TOKEN = get_env_variable("API_TOKEN")
AUTHORIZED_USER_ID = int(get_env_variable("AUTHORIZED_USER_ID"))
ADMIN_USERNAME = get_env_variable("ADMIN_USERNAME")

# Пути к файлам данных
DATA_DIR = os.path.join(os.getcwd(), 'data')
CONFIGS_DIR = os.path.join(DATA_DIR, 'configs')  # Путь к папке configs
USERS_DIR = os.path.join(DATA_DIR, 'users')      # Путь к папке users

AUTHORIZED_USERS_FILE = os.path.join(USERS_DIR, 'authorized_users.txt')
BANNED_USERS_FILE = os.path.join(USERS_DIR, 'banned_users.txt')
KEYS_ISSUED_FILE = os.path.join(USERS_DIR, 'keys_issued.txt')
KEYS_LOG_FILE = os.path.join(USERS_DIR, 'keys_log.txt')
SUPPORT_REQUESTS_FILE = os.path.join(USERS_DIR, 'support_requests.txt')
SITE_EXCEPTIONS_FILE = os.path.join(USERS_DIR, 'exceptions.txt')
KEY_LIMIT_FILE = os.path.join(USERS_DIR, 'key_limit.txt')
USER_LIMITS_FILE = os.path.join(USERS_DIR, 'user_limits.txt')

# Дополнительные файлы для подсчёта ключей
USER_KEYS_COUNT_FILE = os.path.join(USERS_DIR, 'user_keys_count.txt')

# Путь к Docker Compose файлу (опционально)
DOCKER_COMPOSE_FILE = os.path.expanduser('~/antizapret/docker-compose.yml')