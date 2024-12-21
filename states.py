# states.py

from aiogram.dispatcher.filters.state import StatesGroup, State

class WishesStates(StatesGroup):
    waiting_for_text = State()

class VPNSupportStates(StatesGroup):
    waiting_for_operator = State()
    waiting_for_description = State()

class AddSiteForm(StatesGroup):
    site_url = State()

class BroadcastForm(StatesGroup):
    message_text = State()

class UploadKeysForm(StatesGroup):
    uploading = State()

class ManageUserForm(StatesGroup):
    set_limit = State()  # Установка лимита для пользователя

class GlobalSettingsForm(StatesGroup):
    waiting_for_limit = State()  # Установка глобального лимита

class SupportReplyStates(StatesGroup):
    waiting_for_reply = State()