# keyboards.py

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from config import AUTHORIZED_USER_ID

def get_main_menu_kb(user_id: int) -> ReplyKeyboardMarkup:
    """
    Создаёт основную клавиатуру для пользователя.
    """
    buttons = [
        KeyboardButton("🔑 Получить ключ"),
        KeyboardButton("🛠 Не работает VPN"),
        KeyboardButton("💬 Пожелания и предложения")
    ]
    # Добавляем админские кнопки, если пользователь администратор
    if user_id == AUTHORIZED_USER_ID:
        buttons.extend([
            KeyboardButton("📊 Статистика"),
            KeyboardButton("📢 Отправить сообщение всем"),
            KeyboardButton("📤 Загрузить ключи"),
            KeyboardButton("👥 Управление пользователями")
        ])
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(*buttons)
    return kb

def access_request_kb() -> InlineKeyboardMarkup:
    """
    Клавиатура с кнопкой "Запросить доступ".
    """
    # Используем InlineKeyboardMarkup для отправки callback_query
    request_button = InlineKeyboardButton("🔒 Запросить доступ", callback_data="request_access")
    kb = InlineKeyboardMarkup()
    kb.add(request_button)
    return kb

def create_authorize_kb(user_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура для администратора с кнопками "✅ Да" и "❌ Нет".
    """
    # Используем InlineKeyboardMarkup с callback_data, содержащими действие и user_id
    yes_button = InlineKeyboardButton("✅ Да", callback_data=f"authorize_yes_{user_id}")
    no_button = InlineKeyboardButton("❌ Нет", callback_data=f"authorize_no_{user_id}")
    kb = InlineKeyboardMarkup()
    kb.add(yes_button, no_button)
    return kb

def get_back_kb() -> ReplyKeyboardMarkup:
    """
    Клавиатура с кнопкой "🔙 Назад".
    """
    back_button = KeyboardButton("🔙 Назад")
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(back_button)
    return kb

def get_users_keyboard(user_list: list) -> ReplyKeyboardMarkup:
    """
    Создаёт клавиатуру с кнопками для каждого пользователя.
    user_list: список кортежей (user_display_text, user_id)
    """
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for user_display, user_id in user_list:
        # Кнопка отображает имя/ник и ID
        button_text = f"{user_display} (ID: {user_id})"
        kb.add(KeyboardButton(button_text))
    kb.add(KeyboardButton("🔙 Назад"))
    return kb

def get_user_actions_keyboard(is_banned: bool) -> ReplyKeyboardMarkup:
    """
    Создаёт клавиатуру с действиями для выбранного пользователя.
    is_banned: bool, указывает, забанен ли пользователь
    """
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    if is_banned:
        kb.add(KeyboardButton("Разбанить"))
    else:
        kb.add(KeyboardButton("Забанить"))
    kb.add(KeyboardButton("Изменить личный лимит ключей"))
    kb.add(KeyboardButton("🔙 Назад"))
    return kb

def get_stats_user_actions_keyboard() -> ReplyKeyboardMarkup:
    """
    Клавиатура для возврата из детальной статистики пользователя.
    """
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("🔙 Назад"))
    return kb

