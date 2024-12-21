# handlers.py

import logging
import os
import asyncio
import html
import json
from datetime import datetime
import zipfile

import aiofiles
from aiogram import types, Dispatcher, Bot
from aiogram.types import ParseMode, InputFile, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.exceptions import Unauthorized, CantParseEntities
from aiogram.dispatcher import FSMContext

from config import (
    AUTHORIZED_USERS_FILE,
    BANNED_USERS_FILE,
    KEYS_ISSUED_FILE,
    KEYS_LOG_FILE,
    SUPPORT_REQUESTS_FILE,
    SITE_EXCEPTIONS_FILE,
    CONFIGS_DIR,
    AUTHORIZED_USER_ID,
    ADMIN_USERNAME,
    USER_LIMITS_FILE,
    KEY_LIMIT_FILE
)

from keyboards import (
    get_main_menu_kb,
    access_request_kb,
    create_authorize_kb,
    get_back_kb,
    get_users_keyboard,
    get_user_actions_keyboard,
    get_stats_user_actions_keyboard
)

from states import (
    WishesStates,
    VPNSupportStates,
    AddSiteForm,
    BroadcastForm,
    UploadKeysForm,
    ManageUserForm,
    SupportReplyStates,
    GlobalSettingsForm
)

from utils import (
    read_file,
    append_to_file,
    remove_from_file,
    log_key_issuance,
    check_key_issued,
    mark_key_issued,
    get_conf_files,
    update_user_stats,
    load_user_stats,
    add_site_exceptions,
    extract_conf_files_from_zip,
    write_file,
    get_user_limit,
    set_user_limit,
    get_global_limit,
    set_global_limit,
    get_user_keys_count
)

logger = logging.getLogger(__name__)

bot = None  # Будет установлен в main.py через set_bot_instance

def set_bot_instance(new_bot: Bot):
    global bot
    bot = new_bot

def load_messages(filepath='messages.json'):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Файл {filepath} не найден.")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка декодирования JSON из файла {filepath}: {e}")
        return {}

MESSAGES = load_messages()

def format_user_display(user_obj, user_id, keys_count):
    """
    Форматирует отображение пользователя для списка.
    Приоритет: username -> если есть, @username (жирный) + ID + количество ключей
    Если нет username, используем Имя Фамилия (или "Имя не указано"), + ID + количество ключей
    """
    first_name = user_obj.first_name or ""
    last_name = user_obj.last_name or ""
    full_name = (first_name + " " + last_name).strip()
    if user_obj.username:
        # @username
        return f"<b>@{html.escape(user_obj.username)}</b> (ID: {user_id}) {keys_count} ключей"
    else:
        # Имени может не быть
        if full_name:
            return f"{html.escape(full_name)} (ID: {user_id}) {keys_count} ключей"
        else:
            return f"Имя не указано (ID: {user_id}) {keys_count} ключей"

# Обработчики команд и сообщений

async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    logger.info(f"Команда /start от {user_id}")
    banned_users = await read_file(BANNED_USERS_FILE)
    if str(user_id) in banned_users:
        await message.reply(MESSAGES.get("get_key_banned", "🚫 Вы забанены."), parse_mode=ParseMode.HTML)
        return

    authorized_users = await read_file(AUTHORIZED_USERS_FILE)
    if str(user_id) not in authorized_users and user_id != AUTHORIZED_USER_ID:
        await message.reply(MESSAGES.get("access_request", "🔒 Для доступа к VPN нажмите кнопку ниже."), reply_markup=access_request_kb(), parse_mode=ParseMode.HTML)
        return

    main_menu_kb = get_main_menu_kb(user_id)
    text = MESSAGES.get("welcome", "👋 Добро пожаловать! Выберите действие")
    await message.reply(text, reply_markup=main_menu_kb, parse_mode=ParseMode.HTML)

async def handle_access_request(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    try:
        username = call.from_user.username or f"{call.from_user.first_name} {call.from_user.last_name}"
        user_display = username if call.from_user.username else f"{call.from_user.first_name} {call.from_user.last_name}"
        
        # Отправляем сообщение админу с кнопками "✅ Да" и "❌ Нет"
        keyboard = create_authorize_kb(user_id)
        message_text = (
            f"🔔 Новый запрос на авторизацию от пользователя <a href='tg://user?id={user_id}'>{html.escape(user_display)}</a> (ID: {user_id}).\n\n"
            f"Хотите предоставить доступ?"
        )
        await bot.send_message(
            AUTHORIZED_USER_ID,
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
        await call.answer(MESSAGES.get("access_request_sent", "✅ Ваш запрос отправлен администратору"), show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при обработке запроса доступа: {e}")
        await call.answer(MESSAGES.get("error_generic", "❌ Произошла ошибка."), show_alert=True)

async def handle_authorization_response(call: types.CallbackQuery, state: FSMContext):
    admin_id = call.from_user.id
    if admin_id != AUTHORIZED_USER_ID:
        await call.answer(MESSAGES.get("access_denied", "🚫 У вас нет прав для выполнения этого действия"), show_alert=True)
        return

    try:
        # Ожидается формат: "authorize_yes_{user_id}" или "authorize_no_{user_id}"
        parts = call.data.split("_")
        if len(parts) != 3:
            raise ValueError("Неправильный формат данных")
        # parts: ['authorize', 'yes/no', 'user_id']
        response = parts[1]  # 'yes' или 'no'
        user_id = int(parts[2])  # ID пользователя
    except Exception as e:
        logger.error(f"Ошибка при разборе данных авторизации: {e}")
        await call.answer(MESSAGES.get("error_generic", "❌ Произошла ошибка."), show_alert=True)
        return

    try:
        user = await bot.get_chat(user_id)
        keys_count = await get_user_keys_count(user_id)
        user_display = format_user_display(user, user_id, keys_count)

        if response == "yes":
            # Проверяем, не добавлен ли уже пользователь
            authorized_users = await read_file(AUTHORIZED_USERS_FILE)
            if str(user_id) not in authorized_users:
                await append_to_file(AUTHORIZED_USERS_FILE, str(user_id))
            message_text = f"✅ {user_display}: доступ предоставлен"
            await call.message.edit_text(message_text, parse_mode=ParseMode.HTML)
            await bot.send_message(
                user_id,
                MESSAGES.get("access_granted", "🎉 Ваш запрос на доступ был одобрен! Теперь вы можете использовать бота."),
                reply_markup=get_main_menu_kb(user_id),
                parse_mode=ParseMode.HTML
            )
        elif response == "no":
            # Проверяем, не добавлен ли уже пользователь в бан
            banned_users = await read_file(BANNED_USERS_FILE)
            if str(user_id) not in banned_users:
                await append_to_file(BANNED_USERS_FILE, str(user_id))
            message_text = f"❌ {user_display}: доступ отклонен"
            await call.message.edit_text(message_text, parse_mode=ParseMode.HTML)
            await bot.send_message(
                user_id,
                MESSAGES.get("access_denied_user", "🚫 Ваш запрос на доступ был отклонен. Если вы считаете это ошибкой, свяжитесь с администратором."),
                reply_markup=ReplyKeyboardRemove(),
                parse_mode=ParseMode.HTML
            )
        else:
            logger.error("Неизвестный ответ")
            await call.answer(MESSAGES.get("error_generic", "❌ Произошла ошибка."), show_alert=True)
            return

        await call.answer()  # Убирает загрузку кнопки
    except Unauthorized:
        await call.answer("❌ Пользователь не найден", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при обработке авторизации: {e}")
        await call.answer(MESSAGES.get("error_generic", "❌ Произошла ошибка."), show_alert=True)

async def process_wishes(message: types.Message, state: FSMContext):
    await WishesStates.waiting_for_text.set()
    await message.reply(MESSAGES.get("wishes_prompt", "📝 Напишите текст вашего пожелания или предложения:"), reply_markup=get_back_kb(), parse_mode=ParseMode.HTML)

async def process_wishes_text(message: types.Message, state: FSMContext):
    if message.text.strip().lower() == "🔙 назад":
        await state.finish()
        user_id = message.from_user.id
        await message.reply(MESSAGES.get("welcome", "👋 Добро пожаловать! Выберите действие"), reply_markup=get_main_menu_kb(user_id))
        return

    user_text = message.text.strip()
    admin_id = AUTHORIZED_USER_ID
    escaped_text = html.escape(user_text)
    try:
        await bot.send_message(
            admin_id,
            f"📝 <b>Пожелание от <a href='tg://user?id={message.from_user.id}'>{html.escape(message.from_user.full_name)}</a> (ID: {message.from_user.id}):</b>\n{escaped_text}",
            parse_mode=ParseMode.HTML
        )
    except CantParseEntities:
        await bot.send_message(
            admin_id,
            f"📝 Пожелание от {message.from_user.full_name} (ID: {message.from_user.id}):\n{user_text}"
        )

    await message.reply(MESSAGES.get("wishes_thanks", "✅ Спасибо за ваше пожелание!"), parse_mode=ParseMode.HTML)
    user_id = message.from_user.id
    await message.reply(MESSAGES.get("welcome", "👋 Добро пожаловать! Выберите действие"), reply_markup=get_main_menu_kb(user_id))
    await state.finish()

async def process_vpn_issue(message: types.Message, state: FSMContext):
    await VPNSupportStates.waiting_for_operator.set()
    await message.reply(MESSAGES.get("vpn_issue_prompt_operator", "📞 Укажите оператора связи:"), reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)

async def process_operator(message: types.Message, state: FSMContext):
    operator = message.text.strip()
    await state.update_data(operator=operator)
    await VPNSupportStates.next()
    await message.reply(MESSAGES.get("vpn_issue_prompt_description", "📝 Опишите вашу проблему:"), reply_markup=get_back_kb(), parse_mode=ParseMode.HTML)

async def process_description(message: types.Message, state: FSMContext):
    if message.text.strip().lower() == "🔙 назад":
        await state.finish()
        user_id = message.from_user.id
        await message.reply(MESSAGES.get("welcome", "👋 Добро пожаловать! Выберите действие"), reply_markup=get_main_menu_kb(user_id))
        return

    description = message.text.strip()
    user_id = message.from_user.id
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    operator = (await state.get_data()).get('operator', 'Не указано')

    admin_id = AUTHORIZED_USER_ID

    try:
        user = await bot.get_chat(user_id)
        username = user.username if user.username else f"{user.first_name} {user.last_name}"
        message_text = (
            f"🆘 <b>Обращение в поддержку VPN</b>\n\n"
            f"Пользователь: <a href='tg://user?id={user_id}'>{html.escape(username)}</a> (ID: {user_id})\n"
            f"Время обращения: {html.escape(timestamp)}\n"
            f"Оператор связи: {html.escape(operator)}\n"
            f"Описание проблемы:\n{html.escape(description)}"
        )

        # Используем инлайн-клавиатуру с кнопкой "Ответить", включающей user_id и user_message_id
        reply_button = InlineKeyboardButton("Ответить", callback_data=f"reply_{user_id}_{message.message_id}")
        reply_kb = InlineKeyboardMarkup().add(reply_button)

        await bot.send_message(
            admin_id,
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_kb
        )
        await message.reply(MESSAGES.get("vpn_issue_submitted", "✅ Ваша заявка отправлена в поддержку. Мы свяжемся с вами в ближайшее время."), reply_markup=get_main_menu_kb(user_id), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка при отправке обращения VPN админу: {e}")
        await message.reply(MESSAGES.get("error_generic", "❌ Произошла ошибка."), reply_markup=get_main_menu_kb(user_id))

    await state.finish()

async def handle_reply_button(call: types.CallbackQuery, state: FSMContext):
    """
    Обработчик ответа администратора на обращение пользователя.
    Ожидается, что админ нажмет кнопку "Ответить" и введет текст.
    """
    admin_id = call.from_user.id
    if admin_id != AUTHORIZED_USER_ID:
        await call.answer(MESSAGES.get("access_denied", "🚫 У вас нет прав для выполнения этого действия"), show_alert=True)
        return

    # Извлекаем user_id и user_message_id из callback_data
    try:
        _, user_id_str, user_message_id_str = call.data.split("_")
        user_id = int(user_id_str)
        user_message_id = int(user_message_id_str)
    except ValueError:
        await call.answer("❌ Некорректный запрос", show_alert=True)
        return

    # Сохраняем user_id и user_message_id в состоянии для последующего ответа
    await state.update_data(selected_user_id=user_id, selected_user_message_id=user_message_id)
    await SupportReplyStates.waiting_for_reply.set()

    await call.message.reply(MESSAGES.get("reply_prompt", "✉️ Введите ваш ответ пользователю:"), reply_markup=get_back_kb(), parse_mode=ParseMode.HTML)
    await call.answer()

async def process_support_reply(message: types.Message, state: FSMContext):
    if message.text.strip().lower() == "🔙 назад":
        await state.finish()
        user_id = message.from_user.id
        await message.reply(MESSAGES.get("reply_cancelled", "🔙 Отмена отправки ответа. Вернулись в главное меню."), reply_markup=get_main_menu_kb(user_id))
        return

    reply_text = message.text.strip()
    data = await state.get_data()
    user_id = data.get('selected_user_id')
    user_message_id = data.get('selected_user_message_id')

    if not user_id or not user_message_id:
        await message.reply(MESSAGES.get("error_generic", "❌ Произошла ошибка."), reply_markup=get_main_menu_kb(message.from_user.id))
        await state.finish()
        return

    try:
        await bot.send_message(
            user_id,
            f"📨 Ответ от администратора:\n{html.escape(reply_text)}",
            parse_mode=ParseMode.HTML
        )
        await message.reply(MESSAGES.get("reply_success", "✅ Ваш ответ был отправлен пользователю."), reply_markup=get_main_menu_kb(message.from_user.id))
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа пользователю {user_id}: {e}")
        await message.reply(MESSAGES.get("error_generic", "❌ Произошла ошибка."), reply_markup=get_main_menu_kb(message.from_user.id))

    await state.finish()

async def cmd_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != AUTHORIZED_USER_ID:
        await message.reply(MESSAGES.get("access_denied", "🚫 У вас нет прав для выполнения этого действия."), parse_mode=ParseMode.HTML)
        return
    await BroadcastForm.message_text.set()
    await message.reply(MESSAGES.get("broadcast_prompt", "📢 Введите сообщение для рассылки:"), reply_markup=get_back_kb(), parse_mode=ParseMode.HTML)

async def process_broadcast_message(message: types.Message, state: FSMContext):
    if message.text.strip().lower() == "🔙 назад":
        await state.finish()
        user_id = message.from_user.id
        await message.reply(MESSAGES.get("welcome", "👋 Добро пожаловать! Выберите действие"), reply_markup=get_main_menu_kb(user_id))
        return

    broadcast_message = message.text.strip()
    authorized_users = await read_file(AUTHORIZED_USERS_FILE)
    authorized_users = [int(uid) for uid in authorized_users if uid.isdigit()]
    if AUTHORIZED_USER_ID not in authorized_users:
        authorized_users.append(AUTHORIZED_USER_ID)

    count = 0
    for uid in authorized_users:
        try:
            await bot.send_message(uid, broadcast_message, parse_mode=ParseMode.HTML)
            count += 1
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {uid}: {e}")

    await message.reply(MESSAGES.get("broadcast_sent", "✅ Сообщение отправлено {count} пользователям.").format(count=count), reply_markup=get_main_menu_kb(message.from_user.id))
    await state.finish()

async def cmd_upload_keys(message: types.Message, state: FSMContext):
    if message.from_user.id != AUTHORIZED_USER_ID:
        await message.reply(MESSAGES.get("access_denied", "🚫 У вас нет прав для выполнения этого действия."), parse_mode=ParseMode.HTML)
        return
    await UploadKeysForm.uploading.set()
    await message.reply(MESSAGES.get("upload_keys_prompt", "📤 Отправьте архив .zip с .conf файлами для загрузки:"), reply_markup=get_back_kb())

MAX_ZIP_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_CONF_FILES = 1220

async def process_upload_keys(message: types.Message, state: FSMContext):
    if message.text and message.text.strip().lower() == "🔙 назад":
        await state.finish()
        user_id = message.from_user.id
        await message.reply(MESSAGES.get("welcome", "👋 Добро пожаловать! Выберите действие"), reply_markup=get_main_menu_kb(user_id))
        return

    if message.document:
        doc = message.document
        if not doc.file_name.endswith('.zip'):
            await message.reply(f"❌ Файл `{doc.file_name}` имеет некорректное расширение.", reply_markup=get_back_kb())
            return

        if doc.file_size > MAX_ZIP_SIZE:
            await message.reply(f"❌ Размер архива превышает допустимый лимит (10 MB).", reply_markup=get_back_kb())
            return

        try:
            temp_zip_path = os.path.join(CONFIGS_DIR, f"temp_{doc.file_id}.zip")
            await doc.download(destination_file=temp_zip_path)

            added, replaced = await extract_conf_files_from_zip(temp_zip_path)
            os.remove(temp_zip_path)

            if added == -1 and replaced == -1:
                await message.reply(MESSAGES.get("upload_keys_error", "❌ Произошла неизвестная ошибка."), reply_markup=get_back_kb())
                return

            if added + replaced > MAX_CONF_FILES:
                await message.reply(f"❌ В архиве слишком много `.conf` файлов.", reply_markup=get_back_kb())
                # Удаляем все временные файлы
                for f in os.listdir(CONFIGS_DIR):
                    if f.startswith("temp_"):
                        os.remove(os.path.join(CONFIGS_DIR, f))
                return

            response_message = MESSAGES.get("upload_keys_success", "✅ Загружено {added} файлов `.conf`.\n✅ Заменено {replaced} существующих файлов.").format(added=added, replaced=replaced)
            await message.reply(response_message, reply_markup=get_main_menu_kb(message.from_user.id))
            await update_user_stats(message.from_user.id)
        except zipfile.BadZipFile:
            await message.reply(MESSAGES.get("upload_keys_error", "❌ Произошла неизвестная ошибка.").format(error="Недействительный ZIP архив"), reply_markup=get_back_kb())
        except Exception as e:
            await message.reply(MESSAGES.get("upload_keys_error", "❌ Произошла неизвестная ошибка.").format(error=str(e)), reply_markup=get_back_kb())
    else:
        await message.reply(MESSAGES.get("error_generic", "❌ Произошла ошибка."), reply_markup=get_back_kb())

async def cmd_get_key(message: types.Message):
    user_id = message.from_user.id
    banned_users = await read_file(BANNED_USERS_FILE)
    if str(user_id) in banned_users:
        await message.reply(MESSAGES.get("get_key_banned", "🚫 Вы забанены и не можете использовать этого бота."), parse_mode=ParseMode.HTML)
        return

    authorized_users = await read_file(AUTHORIZED_USERS_FILE)
    if str(user_id) not in authorized_users and user_id != AUTHORIZED_USER_ID:
        await message.reply(MESSAGES.get("get_key_not_authorized", "🔒 Вы не авторизованы для использования этого бота."), parse_mode=ParseMode.HTML)
        return

    # Проверка лимита ключей
    user_limit = await get_user_limit(user_id)
    issued_keys = await read_file(KEYS_ISSUED_FILE)
    user_keys = [line for line in issued_keys if line.startswith(f"{user_id}:")]
    if len(user_keys) >= user_limit and user_id != AUTHORIZED_USER_ID:
        await message.reply(MESSAGES.get("get_key_limit_reached", "🔒 Вы достигли максимального лимита ключей. Пожалуйста, свяжитесь с поддержкой для увеличения лимита."), parse_mode=ParseMode.HTML)
        return

    conf_files = await get_conf_files()
    if not conf_files:
        await message.reply("❌ Все файлы были отправлены")
        return

    next_file = conf_files[0]
    file_path = os.path.join(CONFIGS_DIR, next_file)

    try:
        first_key = not any(line.startswith(f"{user_id}:") for line in issued_keys)
        instruction_message = ""
        if first_key:
            instruction_message = (
                "📖 <b>Инструкция по использованию VPN:</b>\n"
                "- Скачайте приложение WireGuard или AmneziaWG\n"
                "- Нажмите кнопку <b>Получить ключ</b> и добавьте файл `.conf` в приложение WireGuard или AmneziaVPN\n"
            )

        if not os.path.exists(file_path):
            await message.reply("❌ Файл не найден. Пожалуйста, попробуйте позже")
            return

        if first_key:
            await message.reply_document(
                InputFile(file_path),
                caption=instruction_message,
                parse_mode=ParseMode.HTML
            )
        else:
            await message.reply_document(InputFile(file_path))

        try:
            user = await bot.get_chat(user_id)
            username = user.username if user.username else f"{user.first_name} {user.last_name}"
        except:
            username = f"ID: {user_id}"

        await log_key_issuance(user_id, username, next_file)
        await mark_key_issued(user_id, next_file)
        await update_user_stats(user_id)

        os.remove(file_path)

        confirmation_message = MESSAGES.get("get_key_sent", "🔑 Ключ успешно отправлен\n\n👋 Выберите действие:")
        if first_key:
            confirmation_message = MESSAGES.get("get_key_sent_first", "🔑 Ключ успешно отправлен\n\n📖 Инструкция по использованию VPN была отправлена вместе с ключом.\n\n👋 Выберите действие:")
        await message.reply(f"{confirmation_message}", reply_markup=get_main_menu_kb(user_id), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка при отправке файла {next_file}: {e}")
        await message.reply(MESSAGES.get("error_generic", "❌ Произошла ошибка."))

async def cmd_add_site(message: types.Message, state: FSMContext):
    await AddSiteForm.site_url.set()
    await message.reply(MESSAGES.get("add_site_prompt", "🌐 Введите URL сайта, который необходимо добавить в исключения:"), reply_markup=get_back_kb(), parse_mode=ParseMode.HTML)

async def process_site_url(message: types.Message, state: FSMContext):
    if message.text.strip().lower() == "🔙 назад":
        await state.finish()
        user_id = message.from_user.id
        await message.reply(MESSAGES.get("welcome", "👋 Добро пожаловать! Выберите действие"), reply_markup=get_main_menu_kb(user_id))
        return

    url = message.text.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        await message.reply("❌ Некорректный URL", reply_markup=get_back_kb())
        return

    await state.update_data(site_url=url)
    await AddSiteForm.next()
    await message.reply(MESSAGES.get("add_site_processing", "⏳ Обработка запроса..."), reply_markup=get_back_kb(), parse_mode=ParseMode.HTML)

    added_patterns, all_patterns = await add_site_exceptions(url)
    if not added_patterns:
        await message.reply(MESSAGES.get("add_site_already_exists", "✅ Сайты уже были добавлены ранее."), parse_mode=ParseMode.HTML)
        user_id = message.from_user.id
        await message.reply(MESSAGES.get("welcome", "👋 Добро пожаловать! Выберите действие"), reply_markup=get_main_menu_kb(user_id), parse_mode=ParseMode.HTML)
        await state.finish()
        return

    await message.reply(MESSAGES.get("add_site_success", "✅ Сайты будут добавлены и Docker перезапущен в ближайший час."), reply_markup=get_main_menu_kb(message.from_user.id), parse_mode=ParseMode.HTML)
    await state.finish()

async def cmd_users(message: types.Message, state: FSMContext):
    if message.from_user.id != AUTHORIZED_USER_ID:
        await message.reply(MESSAGES.get("access_denied", "🚫 У вас нет прав для выполнения этого действия."), parse_mode=ParseMode.HTML)
        return

    authorized_users = await read_file(AUTHORIZED_USERS_FILE)
    banned_users = await read_file(BANNED_USERS_FILE)

    # Сформируем списки пользователей
    user_list = []
    # Авторизованные пользователи
    for uid_str in authorized_users:
        if not uid_str.isdigit():
            continue
        uid = int(uid_str)
        try:
            user_obj = await bot.get_chat(uid)
            keys_count = await get_user_keys_count(uid)
            user_display = user_obj.username if user_obj.username else f"{user_obj.first_name or ''} {user_obj.last_name or ''}".strip() or "Имя не указано"
            user_list.append((user_display, uid))
        except Exception as e:
            logger.error(f"Ошибка получения информации о пользователе {uid}: {e}")
            user_list.append(("Имя не указано", uid))

    # Забаненные пользователи
    for uid_str in banned_users:
        if not uid_str.isdigit():
            continue
        uid = int(uid_str)
        try:
            user_obj = await bot.get_chat(uid)
            keys_count = await get_user_keys_count(uid)
            user_display = user_obj.username if user_obj.username else f"{user_obj.first_name or ''} {user_obj.last_name or ''}".strip() or "Имя не указано"
            user_list.append((user_display, uid))
        except Exception as e:
            logger.error(f"Ошибка получения информации о пользователе {uid}: {e}")
            user_list.append(("Имя не указано", uid))

    # Сформируем текст списка пользователей
    text = "👥 **Авторизованные пользователи:**\n"
    authorized_users_display = []
    for user_display, uid in user_list:
        if uid in map(int, authorized_users):
            keys_count = await get_user_keys_count(uid)
            authorized_users_display.append(f"{user_display} (ID: {uid}) - {keys_count} ключей")
    if authorized_users_display:
        text += "\n".join(authorized_users_display)
    else:
        text += "Нет авторизованных пользователей."

    text += "\n\n🚫 **Забаненные пользователи:**\n"
    banned_users_display = []
    for user_display, uid in user_list:
        if uid in map(int, banned_users):
            keys_count = await get_user_keys_count(uid)
            banned_users_display.append(f"{user_display} (ID: {uid}) - {keys_count} ключей")
    if banned_users_display:
        text += "\n".join(banned_users_display)
    else:
        text += "Нет забаненных пользователей."

    # Клавиатура с кнопками для каждого пользователя
    users_keyboard = get_users_keyboard(user_list)

    await message.reply(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True, reply_markup=users_keyboard)

async def handle_user_selection(message: types.Message, state: FSMContext):
    """
    Обработчик выбора пользователя из клавиатуры.
    Извлекает user_id из текста кнопки.
    """
    text = message.text
    try:
        # Ожидаем формат "Имя (ID: 12345) - X ключей"
        start = text.rfind("(ID: ")
        end = text.find(")", start)
        if start == -1 or end == -1:
            raise ValueError("Неправильный формат кнопки")
        user_id_str = text[start+5:end]
        user_id = int(user_id_str)
    except Exception as e:
        logger.error(f"Ошибка при разборе ID пользователя из текста '{text}': {e}")
        await message.reply("❌ Не удалось определить пользователя. Попробуйте снова.", reply_markup=get_back_kb())
        return

    # Сохраняем выбранный user_id в состоянии
    await state.update_data(selected_user_id=user_id)

    # Проверяем, забанен ли пользователь
    banned_users = await read_file(BANNED_USERS_FILE)
    is_banned = str(user_id) in banned_users

    # Создаём клавиатуру с действиями
    actions_keyboard = get_user_actions_keyboard(is_banned)

    # Отправляем меню действий
    try:
        user_obj = await bot.get_chat(user_id)
        user_display = user_obj.username if user_obj.username else f"{user_obj.first_name or ''} {user_obj.last_name or ''}".strip() or "Имя не указано"
    except Exception as e:
        logger.error(f"Ошибка получения информации о пользователе {user_id}: {e}")
        user_display = "Имя не указано"

    action_text = f"🔧 **Управление пользователем:**\n{html.escape(user_display)} (ID: {user_id})"

    await message.reply(action_text, parse_mode=ParseMode.MARKDOWN, reply_markup=actions_keyboard)

async def handle_user_action(message: types.Message, state: FSMContext):
    """
    Обработчик действий для выбранного пользователя.
    """
    action = message.text.strip()
    data = await state.get_data()
    user_id = data.get('selected_user_id')

    if not user_id:
        await message.reply("❌ Неизвестный пользователь.", reply_markup=get_back_kb())
        return

    if action == "🔙 Назад":
        await state.finish()
        user_id = message.from_user.id
        await message.reply(MESSAGES.get("welcome", "👋 Добро пожаловать! Выберите действие"), reply_markup=get_main_menu_kb(user_id))
        return

    if action == "Забанить":
        authorized_users = await read_file(AUTHORIZED_USERS_FILE)
        if str(user_id) not in authorized_users:
            await append_to_file(BANNED_USERS_FILE, str(user_id))
            await message.reply("✅ Пользователь забанен.", reply_markup=get_user_actions_keyboard(True))
            logger.info(f"Пользователь {user_id} был забанен")
        else:
            await message.reply("❌ Пользователь уже авторизован и не может быть забанен.", reply_markup=get_back_kb())
    elif action == "Разбанить":
        await remove_from_file(BANNED_USERS_FILE, str(user_id))
        await message.reply("✅ Пользователь разбанен.", reply_markup=get_user_actions_keyboard(False))
        logger.info(f"Пользователь {user_id} был разбанен")
    elif action == "Изменить личный лимит ключей":
        await ManageUserForm.set_limit.set()
        await message.reply("Введите новый лимит ключей для этого пользователя:", reply_markup=get_back_kb())
    else:
        await message.reply("❌ Неизвестное действие.", reply_markup=get_back_kb())

async def set_user_limit_value(message: types.Message, state: FSMContext):
    """
    Обработчик установки нового лимита для пользователя.
    """
    if message.text.strip().lower() == "🔙 назад":
        await state.finish()
        user_id = (await state.get_data()).get('selected_user_id')
        is_banned = str(user_id) in await read_file(BANNED_USERS_FILE)
        await message.reply("🔙 Отменено.", reply_markup=get_user_actions_keyboard(is_banned))
        return

    try:
        new_limit = int(message.text.strip())
        if new_limit <= 0:
            raise ValueError("Лимит должен быть положительным числом.")
    except ValueError as e:
        await message.reply(f"❌ Некорректный ввод: {e}", reply_markup=get_back_kb())
        return

    data = await state.get_data()
    user_id = data.get('selected_user_id')

    if not user_id:
        await message.reply("❌ Неизвестный пользователь.", reply_markup=get_back_kb())
        return

    await set_user_limit(user_id, new_limit)
    await message.reply(f"✅ Лимит ключей для пользователя {user_id} установлен на {new_limit}.", reply_markup=get_user_actions_keyboard(str(user_id) in await read_file(BANNED_USERS_FILE)))

    logger.info(f"Лимит ключей для пользователя {user_id} изменён на {new_limit}")
    await state.finish()

async def cmd_stats(message: types.Message, state: FSMContext):
    if message.from_user.id != AUTHORIZED_USER_ID:
        await message.reply(MESSAGES.get("access_denied", "🚫 У вас нет прав для выполнения этого действия."), parse_mode=ParseMode.HTML)
        return

    # Общее количество оставшихся ключей
    conf_files = await get_conf_files()
    remain = len(conf_files)

    authorized_users = await read_file(AUTHORIZED_USERS_FILE)
    banned_users = await read_file(BANNED_USERS_FILE)

    # Сформируем списки пользователей
    user_list = []
    # Авторизованные пользователи
    for uid_str in authorized_users:
        if not uid_str.isdigit():
            continue
        uid = int(uid_str)
        try:
            user_obj = await bot.get_chat(uid)
            keys_count = await get_user_keys_count(uid)
            user_display = user_obj.username if user_obj.username else f"{user_obj.first_name or ''} {user_obj.last_name or ''}".strip() or "Имя не указано"
            user_list.append((user_display, uid))
        except Exception as e:
            logger.error(f"Ошибка получения информации о пользователе {uid}: {e}")
            user_list.append(("Имя не указано", uid))

    # Забаненные пользователи
    for uid_str in banned_users:
        if not uid_str.isdigit():
            continue
        uid = int(uid_str)
        try:
            user_obj = await bot.get_chat(uid)
            keys_count = await get_user_keys_count(uid)
            user_display = user_obj.username if user_obj.username else f"{user_obj.first_name or ''} {user_obj.last_name or ''}".strip() or "Имя не указано"
            user_list.append((user_display, uid))
        except Exception as e:
            logger.error(f"Ошибка получения информации о пользователе {uid}: {e}")
            user_list.append(("Имя не указано", uid))

    # Сформируем текст статистики
    text = f"📊 **Статистика:**\n\n**Осталось ключей:** {remain}\n\n**Авторизованные пользователи:**\n"
    authorized_users_display = []
    for user_display, uid in user_list:
        if uid in map(int, authorized_users):
            keys_count = await get_user_keys_count(uid)
            authorized_users_display.append(f"{user_display} (ID: {uid}) - {keys_count} ключей")
    if authorized_users_display:
        text += "\n".join(authorized_users_display)
    else:
        text += "Нет авторизованных пользователей."

    text += "\n\n🚫 **Забаненные пользователи:**\n"
    banned_users_display = []
    for user_display, uid in user_list:
        if uid in map(int, banned_users):
            keys_count = await get_user_keys_count(uid)
            banned_users_display.append(f"{user_display} (ID: {uid}) - {keys_count} ключей")
    if banned_users_display:
        text += "\n".join(banned_users_display)
    else:
        text += "Нет забаненных пользователей."

    # Клавиатура с кнопками для каждого пользователя
    stats_keyboard = get_users_keyboard(user_list)

    await message.reply(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True, reply_markup=stats_keyboard)

async def handle_stats_user_selection(message: types.Message, state: FSMContext):
    """
    Обработчик выбора пользователя для просмотра статистики.
    """
    text = message.text
    try:
        # Ожидаем формат "Имя (ID: 12345) - X ключей"
        start = text.rfind("(ID: ")
        end = text.find(")", start)
        if start == -1 or end == -1:
            raise ValueError("Неправильный формат кнопки")
        user_id_str = text[start+5:end]
        user_id = int(user_id_str)
    except Exception as e:
        logger.error(f"Ошибка при разборе ID пользователя из текста '{text}': {e}")
        await message.reply("❌ Не удалось определить пользователя. Попробуйте снова.", reply_markup=get_back_kb())
        return

    # Получаем список выданных ключей этому пользователю
    issued_keys = await read_file(KEYS_LOG_FILE)
    user_files = []
    for line in issued_keys:
        # Предполагается формат:
        # timestamp - User: username (ID: user_id) - Key: filename.conf
        if f"(ID: {user_id})" in line and "Key:" in line:
            # Извлекаем filename.conf
            parts = line.strip().split(" - ")
            if len(parts) >= 3:
                key_part = parts[2]
                key_filename = key_part.replace("Key: ", "")
                user_files.append(key_filename)

    if user_files:
        keys_text = f"📄 **Ключи пользователя (ID: {user_id}):**\n" + "\n".join(user_files)
    else:
        keys_text = f"❌ У пользователя (ID: {user_id}) нет выданных ключей."

    # Клавиатура с кнопкой "🔙 Назад"
    kb = get_stats_user_actions_keyboard()

    await message.reply(keys_text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True, reply_markup=kb)

async def handle_stats_back(message: types.Message, state: FSMContext):
    """
    Обработчик кнопки "🔙 Назад" в статистике.
    """
    await state.finish()
    user_id = message.from_user.id
    await message.reply(MESSAGES.get("welcome", "👋 Добро пожаловать! Выберите действие"), reply_markup=get_main_menu_kb(user_id))

async def handle_user_action_in_stats(message: types.Message, state: FSMContext):
    """
    Обработчик для статистики, в данном случае просто кнопка "🔙 Назад".
    """
    action = message.text.strip()
    if action == "🔙 Назад":
        await state.finish()
        user_id = message.from_user.id
        await message.reply("🔙 Вернулись в главное меню.", reply_markup=get_main_menu_kb(user_id))
        return
    else:
        await message.reply("❌ Неизвестное действие.", reply_markup=get_back_kb())

async def handle_back(message: types.Message, state: FSMContext):
    """
    Обработчик кнопки "🔙 Назад".
    Завершает текущее состояние и возвращает пользователя в главное меню.
    """
    await state.finish()
    user_id = message.from_user.id
    await message.reply(MESSAGES.get("welcome", "👋 Добро пожаловать! Выберите действие"), reply_markup=get_main_menu_kb(user_id), parse_mode=ParseMode.HTML)

# Регистрация всех обработчиков

def register_handlers(dp: Dispatcher):
    # Регистрация обработчиков команд
    dp.register_message_handler(cmd_start, commands=['start'])

    # Обработчики кнопок для запроса доступа
    dp.register_callback_query_handler(handle_access_request, lambda c: c.data == 'request_access', state='*')
    dp.register_callback_query_handler(handle_authorization_response, lambda c: c.data.startswith('authorize_'), state='*')

    # Обработчики кнопок пользователей (управление и статистика)
    dp.register_message_handler(handle_user_selection, lambda m: "(ID: " in m.text, state='*')  # Управление пользователями
    dp.register_message_handler(handle_stats_user_selection, lambda m: "(ID: " in m.text, state='*')  # Статистика

    # Обработчики действий для управления пользователями
    dp.register_message_handler(handle_user_action, lambda m: m.text in ["Забанить", "Разбанить", "Изменить личный лимит ключей", "🔙 Назад"], state='*')
    dp.register_message_handler(set_user_limit_value, state=ManageUserForm.set_limit, content_types=types.ContentTypes.TEXT)

    # Обработчики статистики
    dp.register_message_handler(cmd_stats, lambda m: m.text == "📊 Статистика")
    dp.register_message_handler(handle_stats_back, lambda m: m.text == "🔙 Назад", state='*')
    dp.register_message_handler(handle_user_action_in_stats, lambda m: m.text == "🔙 Назад", state='*')

    # Обработчики других команд и состояний
    dp.register_message_handler(process_wishes, lambda m: m.text == "💬 Пожелания и предложения", state='*')
    dp.register_message_handler(process_wishes_text, state=WishesStates.waiting_for_text, content_types=types.ContentTypes.TEXT)
    dp.register_message_handler(cmd_get_key, lambda m: m.text == "🔑 Получить ключ")
    dp.register_message_handler(cmd_add_site, lambda m: m.text == "🌐 Добавить сайт в исключения")
    dp.register_message_handler(process_site_url, state=AddSiteForm.site_url)
    dp.register_message_handler(process_vpn_issue, lambda m: m.text == "🛠 Не работает VPN")

    dp.register_message_handler(cmd_broadcast, lambda m: m.text == "📢 Отправить сообщение всем")
    dp.register_message_handler(process_broadcast_message, state=BroadcastForm.message_text)
    dp.register_message_handler(cmd_upload_keys, lambda m: m.text == "📤 Загрузить ключи")
    dp.register_message_handler(process_upload_keys, content_types=types.ContentType.DOCUMENT, state=UploadKeysForm.uploading)
    dp.register_message_handler(cmd_users, lambda m: m.text == "👥 Управление пользователями")

    dp.register_message_handler(process_support_reply, state=SupportReplyStates.waiting_for_reply, content_types=types.ContentTypes.TEXT)
    dp.register_message_handler(process_operator, state=VPNSupportStates.waiting_for_operator, content_types=types.ContentTypes.TEXT)
    dp.register_message_handler(process_description, state=VPNSupportStates.waiting_for_description, content_types=types.ContentTypes.TEXT)

    # Обработчики кнопки "🔙 Назад" во всех состояниях
    dp.register_message_handler(handle_back, lambda m: m.text.strip().lower() == "🔙 назад", state='*')

    # Обработчики callback_query для поддержки
    dp.register_callback_query_handler(handle_reply_button, lambda c: c.data and c.data.startswith("reply_"), state='*')

    # Дополнительные обработчики (если необходимо)
    dp.register_callback_query_handler(lambda c: c.answer(), lambda c: c.data == "no_action")