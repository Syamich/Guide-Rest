import asyncio
import json
import os
import subprocess
import logging
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    Filters,
    CallbackContext,
)

# Максимальная длина текста кнопки (в символах) для выравнивания
MAX_BUTTON_TEXT_LENGTH = 100

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка .env
load_dotenv()
logger.info("Загружен файл .env")

# Проверка BOT_TOKEN
if not os.getenv("BOT_TOKEN"):
    logger.error("BOT_TOKEN не найден в переменных окружения")
    raise ValueError("BOT_TOKEN не найден в переменных окружения. Установите его в .env или в переменных окружения PythonAnywhere.")

# Включение/отключение поддержки фотографий
ENABLE_PHOTOS = True  # Установите False, чтобы отключить фотографии

# Состояния для ConversationHandler
GUIDE_QUESTION, GUIDE_ANSWER, GUIDE_ANSWER_PHOTOS = range(3)
GUIDE_EDIT_QUESTION, GUIDE_EDIT_FIELD, GUIDE_EDIT_VALUE = range(3, 6)
TEMPLATE_QUESTION, TEMPLATE_ANSWER, TEMPLATE_ANSWER_PHOTOS = range(6, 9)
TEMPLATE_EDIT_QUESTION, TEMPLATE_EDIT_FIELD, TEMPLATE_EDIT_VALUE = range(9, 12)

# Постоянное клавиатурное меню
MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📖 Справочник"), KeyboardButton("📋 Шаблоны ответов")],
        [KeyboardButton("➕ Добавить пункт"), KeyboardButton("✏️ Редактировать пункт")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

# Чтение JSON
def load_data(data_type: str):
    file_name = 'guide.json' if data_type == 'guide' else 'templates.json'
    try:
        with open(file_name, 'r', encoding='utf-8') as f:
            data = json.load(f)
            key = 'questions' if data_type == 'guide' else 'templates'
            return data if key in data else {key: []}
    except FileNotFoundError:
        logger.warning(f"{file_name} не найден, инициализация пустого {data_type}")
        return {"questions" if data_type == 'guide' else "templates": []}

def load_guide():
    return load_data('guide')

def load_templates():
    return load_data('template')

# Чтение user_id из переменной окружения
def load_users():
    users_str = os.getenv("ALLOWED_USERS", "")
    logger.info(f"Raw ALLOWED_USERS: '{users_str}'")
    if not users_str:
        logger.warning("ALLOWED_USERS пуст")
        return []
    try:
        users = [int(user_id) for user_id in users_str.split(",") if user_id.strip()]
        logger.info(f"Загружены разрешенные пользователи: {users}")
        return users
    except ValueError as e:
        logger.error(f"Ошибка парсинга ALLOWED_USERS: {e}")
        return []

# Сохранение JSON и синхронизация с GitHub
def save_data(data_type: str, data):
    file_name = 'guide.json' if data_type == 'guide' else 'templates.json'
    with open(file_name, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    sync_with_github()

def save_guide(data):
    save_data('guide', data)

def save_templates(data):
    save_data('template', data)

def sync_with_github():
    try:
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not result.stdout:
            logger.info("Нет изменений в рабочей директории для коммита")
            return
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "Обновление JSON файлов через бот"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        logger.info("Успешно синхронизированы JSON файлы с GitHub")
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка синхронизации с Git: {e}")
        try:
            subprocess.run(["git", "rebase", "--abort"], check=True)
            subprocess.run(["git", "pull", "--no-rebase"], check=True)
            subprocess.run(["git", "push", "origin", "main"], check=True)
            logger.info("Разрешен конфликт git и синхронизированы JSON файлы")
        except subprocess.CalledProcessError as e2:
            logger.error(f"Не удалось разрешить конфликт git: {e2}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка при синхронизации с git: {e}")

# Проверка доступа
def restrict_access(func):
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        user = update.effective_user
        user_id = user.id
        # Формируем имя пользователя для логов
        user_display = user.username or f"{user.first_name or ''} {user.last_name or ''}".strip() or f"ID {user_id}"
        logger.info(f"Проверка доступа для пользователя {user_display} (ID: {user_id})")
        users = load_users()
        logger.info(f"Разрешенные пользователи: {users}")
        if user_id not in users:
            error_msg = "🚫 Доступ запрещён! Обратитесь к администратору."
            if update.message:
                update.message.reply_text(error_msg, reply_markup=MAIN_MENU)
            elif update.callback_query:
                update.callback_query.message.reply_text(error_msg, reply_markup=MAIN_MENU)
            logger.warning(f"Попытка несанкционированного доступа пользователем {user_display} (ID: {user_id})")
            return
        # Сохраняем информацию о пользователе в context.user_data для других функций
        context.user_data['user_display'] = user_display
        return func(update, context, *args, **kwargs)
    return wrapper

# Обработчик ошибок
def error_handler(update: Update, context: CallbackContext):
    logger.error(f"Update {update} вызвал ошибку: {context.error}", exc_info=True)
    logger.info(f"Текущее состояние диалога: {context.user_data.get('conversation_state', 'NONE')}")
    context.user_data.clear()
    context.user_data['conversation_state'] = 'ERROR'
    context.user_data['conversation_active'] = False
    if update.message:
        update.message.reply_text(
            "❌ Произошла ошибка. Попробуйте снова или свяжитесь с администратором.",
            reply_markup=MAIN_MENU
        )
    elif update.callback_query:
        update.callback_query.message.reply_text(
            "❌ Произошла ошибка. Попробуйте снова или свяжитесь с администратором.",
            reply_markup=MAIN_MENU
        )
    return ConversationHandler.END

# Команда /start
@restrict_access
def start(update: Update, context: CallbackContext):
    user_display = context.user_data.get('user_display', f"ID {update.effective_user.id}")
    logger.info(f"Пользователь {user_display} запустил бот")
    context.user_data.clear()
    context.user_data['conversation_state'] = 'START'
    context.user_data['conversation_active'] = False
    update.message.reply_text(
        "Добро пожаловать в справочник техподдержки РЭСТ! 📋\nВыберите действие:",
        reply_markup=MAIN_MENU
    )
    return ConversationHandler.END

# Команда /cancel
@restrict_access
def cancel(update: Update, context: CallbackContext):
    user_display = context.user_data.get('user_display', f"ID {update.effective_user.id}")
    logger.info(f"Пользователь {user_display} отменил диалог")
    if context.user_data.get('timeout_task'):
        context.user_data['timeout_task'].cancel()
        context.user_data['timeout_task'] = None
        logger.info(f"Пользователь {user_display} отменил задачу таймаута")
    context.user_data.clear()
    context.user_data['conversation_state'] = 'CANCELLED'
    context.user_data['conversation_active'] = False
    update.message.reply_text(
        "🚪 Диалог отменён. Выберите действие:",
        reply_markup=MAIN_MENU
    )
    return ConversationHandler.END

# Открытие справочника
@restrict_access
def open_guide(update: Update, context: CallbackContext):
    user_display = context.user_data.get('user_display', f"ID {update.effective_user.id}")
    logger.info(f"Пользователь {user_display} открыл справочник")
    try:
        # Удаляем сообщение пользователя
        update.message.delete()
    except Exception as e:
        logger.debug(f"Не удалось удалить сообщение пользователя {user_display}: {e}")
    # Запускаем фоновую очистку чата
    chat_id = update.effective_chat.id
    message_id = update.effective_message.message_id
    context.job_queue.run_once(
        lambda ctx: clear_chat(ctx, chat_id, message_id, user_display),
        0,
        context=None
    )
    context.user_data.clear()
    context.user_data['conversation_state'] = 'OPEN_GUIDE'
    context.user_data['conversation_active'] = False
    context.user_data['data_type'] = 'guide'
    guide = load_guide()
    if not guide["questions"]:
        update.message.reply_text(
            "📖 Справочник пуст. Добавьте первый пункт! ➕",
            reply_markup=MAIN_MENU
        )
        return ConversationHandler.END
    page = context.user_data.get('page', 0)
    # Отображаем справочник сразу
    display_guide_page(update, context, guide, page, 'guide')
    return ConversationHandler.END

# Открытие шаблонов
@restrict_access
def open_templates(update: Update, context: CallbackContext):
    user_display = context.user_data.get('user_display', f"ID {update.effective_user.id}")
    logger.info(f"Пользователь {user_display} открыл шаблоны")
    try:
        # Удаляем сообщение пользователя
        update.message.delete()
    except Exception as e:
        logger.debug(f"Не удалось удалить сообщение пользователя {user_display}: {e}")
    # Запускаем фоновую очистку чата
    chat_id = update.effective_chat.id
    message_id = update.effective_message.message_id
    context.job_queue.run_once(
        lambda ctx: clear_chat(ctx, chat_id, message_id, user_display),
        0,
        context=None
    )
    context.user_data.clear()
    context.user_data['conversation_state'] = 'OPEN_TEMPLATE'
    context.user_data['conversation_active'] = False
    context.user_data['data_type'] = 'template'
    templates = load_templates()
    if not templates["templates"]:
        keyboard = [
            [InlineKeyboardButton("➕ Добавить шаблон", callback_data='add_template')],
            [InlineKeyboardButton("🚪 Вернуться в меню", callback_data='cancel_template')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            "📋 Шаблоны ответов пусты. Добавьте первый шаблон!",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
    page = context.user_data.get('page', 0)
    # Отображаем шаблоны сразу
    display_template_page(update, context, templates, page)
    return ConversationHandler.END

# Отображение страницы справочника
def display_guide_page(update: Update, context: CallbackContext, data, page, data_type: str):
    try:
        ITEMS_PER_PAGE = 15
        total_items = len(data["questions"])
        total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(0, min(page, total_pages - 1))
        context.user_data['page'] = page
        context.user_data['data'] = data
        context.user_data['data_type'] = data_type

        start_idx = page * ITEMS_PER_PAGE
        end_idx = min(start_idx + ITEMS_PER_PAGE, total_items)
        items = data["questions"][start_idx:end_idx]

        keyboard = []
        for item in items:
            if not isinstance(item, dict) or "question" not in item or "id" not in item:
                logger.error(f"Неверные данные справочника: {item}")
                continue
            question_text = item["question"][:50] if len(item["question"]) > 50 else item["question"]
            padded_text = f"📄 {question_text}" + "." * (MAX_BUTTON_TEXT_LENGTH - len(f"📄 {question_text}"))
            logger.debug(f"Сформирована кнопка справочника: '{padded_text}' (длина: {len(padded_text)})")
            keyboard.append([InlineKeyboardButton(padded_text, callback_data=f'{data_type}_question_{item["id"]}')])

        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'{data_type}_page_{page-1}'))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f'{data_type}_page_{page+1}'))
        keyboard.append(nav_buttons)

        inline_reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"📖 Справочник (страница {page + 1}/{total_pages}):"

        if update.message:
            update.message.reply_text(
                text,
                reply_markup=inline_reply_markup,  # Инлайн-кнопки
                reply_to_message_id=None
            )
            # Отправляем сообщение с главным меню
            update.message.reply_text("Выберите нужный пункт", reply_markup=MAIN_MENU)
        elif update.callback_query:
            update.callback_query.message.edit_text(
                text,
                reply_markup=inline_reply_markup  # Только инлайн-кнопки при пагинации
            )

        user_display = context.user_data.get('user_display', f"ID {update.effective_user.id}")
        logger.info(f"Пользователь {user_display} просмотрел страницу справочника {page + 1}")
        context.user_data['conversation_state'] = f'{data_type.upper()}_PAGE'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END

    except Exception as e:
        user_display = context.user_data.get('user_display', f"ID {update.effective_user.id}")
        logger.error(f"Ошибка в display_guide_page для пользователя {user_display}: {str(e)}", exc_info=True)
        if update.message:
            update.message.reply_text(
                "❌ Произошла ошибка при отображении страницы. Попробуйте снова или свяжитесь с администратором.",
                reply_markup=MAIN_MENU
            )
        elif update.callback_query:
            update.callback_query.message.reply_text(
                "❌ Произошла ошибка при отображении страницы. Попробуйте снова или свяжитесь с администратором.",
                reply_markup=MAIN_MENU
            )
        return ConversationHandler.END

# Отображение страницы шаблонов
def display_template_page(update: Update, context: CallbackContext, data, page):
    try:
        ITEMS_PER_PAGE = 15
        total_items = len(data["templates"])
        total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(0, min(page, total_pages - 1))
        context.user_data['page'] = page
        context.user_data['data'] = data
        context.user_data['data_type'] = 'template'

        start_idx = page * ITEMS_PER_PAGE
        end_idx = min(start_idx + ITEMS_PER_PAGE, total_items)
        items = data["templates"][start_idx:end_idx]

        keyboard = []
        for item in items:
            if not isinstance(item, dict) or "question" not in item or "id" not in item:
                logger.error(f"Неверные данные шаблона: {item}")
                continue
            question_text = item["question"][:50] if len(item["question"]) > 50 else item["question"]
            padded_text = f"📄 {question_text}" + "." * (MAX_BUTTON_TEXT_LENGTH - len(f"📄 {question_text}"))
            logger.debug(f"Сформирована кнопка шаблона: '{padded_text}' (длина: {len(padded_text)})")
            keyboard.append([InlineKeyboardButton(padded_text, callback_data=f'template_question_{item["id"]}')])

        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'template_page_{page-1}'))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f'template_page_{page+1}'))
        nav_buttons.extend([
            InlineKeyboardButton("➕ Добавить шаблон", callback_data='add_template'),
            InlineKeyboardButton("✏️ Редактировать шаблон", callback_data='edit_template'),
            InlineKeyboardButton("🚪 Вернуться в меню", callback_data='cancel_template')
        ])
        keyboard.append(nav_buttons)

        inline_reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"📋 Шаблоны ответов (страница {page + 1}/{total_pages}):"

        if update.message:
            update.message.reply_text(
                text,
                reply_markup=inline_reply_markup,  # Инлайн-кнопки
                reply_to_message_id=None
            )
            # Отправляем сообщение с главным меню
            update.message.reply_text("Выберите нужный пункт", reply_markup=MAIN_MENU)
        elif update.callback_query:
            update.callback_query.message.edit_text(
                text,
                reply_markup=inline_reply_markup  # Только инлайн-кнопки при пагинации
            )

        user_display = context.user_data.get('user_display', f"ID {update.effective_user.id}")
        logger.info(f"Пользователь {user_display} просмотрел страницу шаблонов {page + 1}")
        context.user_data['conversation_state'] = 'TEMPLATE_PAGE'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END

    except Exception as e:
        user_display = context.user_data.get('user_display', f"ID {update.effective_user.id}")
        logger.error(f"Ошибка в display_template_page для пользователя {user_display}: {str(e)}", exc_info=True)
        if update.message:
            update.message.reply_text(
                "❌ Произошла ошибка при отображении страницы. Попробуйте снова или свяжитесь с администратором.",
                reply_markup=MAIN_MENU
            )
        elif update.callback_query:
            update.callback_query.message.reply_text(
                "❌ Произошла ошибка при отображении страницы. Попробуйте снова или свяжитесь с администратором.",
                reply_markup=MAIN_MENU
            )
        return ConversationHandler.END

@restrict_access
def show_answer(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    try:
        data_type, _, question_id = query.data.split('_')
        question_id = int(question_id)
        user_display = context.user_data.get('user_display', f"ID {update.effective_user.id}")
        logger.info(f"Пользователь {user_display} запросил ответ для {data_type} ID {question_id}")
        data = load_data(data_type)
        key = 'questions' if data_type == 'guide' else 'templates'
        item = next((q for q in data[key] if q["id"] == question_id), None)
        if item:
            # Форматируем ответ с новой строкой после "Ответ:"
            response = f"📄 Вопрос: {item['question']}\nОтвет:\n{item['answer']}"
            # Создаём инлайн-кнопку для удаления
            delete_button = InlineKeyboardButton("🗑 Удалить", callback_data='delete_answer')
            reply_markup = InlineKeyboardMarkup([[delete_button]])
            photo_ids = item.get('photos', [])  # Получаем список фотографий
            message_ids = []
            chat_id = query.message.chat_id
            if ENABLE_PHOTOS and photo_ids:
                # Проверяем, что все file_id валидны (не пустые и являются строками)
                valid_photo_ids = [pid for pid in photo_ids if isinstance(pid, str) and pid.strip()]
                if not valid_photo_ids:
                    logger.warning(f"Нет валидных file_id для {data_type} ID {question_id}: {photo_ids}")
                    # Если нет валидных фотографий, отправляем только текст
                    message = query.message.reply_text(response, reply_markup=reply_markup)
                    message_ids.append(message.message_id)
                elif len(valid_photo_ids) == 1:
                    # Если одна фотография, отправляем через reply_photo
                    message = query.message.reply_photo(
                        photo=valid_photo_ids[0],
                        caption=response,
                        reply_markup=reply_markup
                    )
                    message_ids.append(message.message_id)
                else:
                    # Если несколько фотографий, отправляем через reply_media_group
                    media = [
                        InputMediaPhoto(media=photo_id, caption=response if i == 0 else None)
                        for i, photo_id in enumerate(valid_photo_ids)
                    ]
                    try:
                        messages = query.message.reply_media_group(media=media)
                        message_ids.extend([msg.message_id for msg in messages])
                        # Отправляем отдельное сообщение с кнопкой удаления
                        delete_message = query.message.reply_text(
                            "Нажмите, чтобы удалить ответ:",
                            reply_markup=reply_markup
                        )
                        message_ids.append(delete_message.message_id)
                    except Exception as e:
                        logger.error(f"Ошибка при отправке reply_media_group для {data_type} ID {question_id}: {e}")
                        # В случае ошибки отправляем только текст
                        message = query.message.reply_text(response, reply_markup=reply_markup)
                        message_ids.append(message.message_id)
            else:
                # Если фотографий нет, отправляем только текст
                message = query.message.reply_text(response, reply_markup=reply_markup)
                message_ids.append(message.message_id)
            # Сохраняем message_ids для удаления
            context.user_data['answer_message_ids'] = message_ids
            # Планируем автоматическое удаление через 30 минут (1800 секунд)
            context.job_queue.run_once(
                schedule_message_deletion,
                1800,
                context={'chat_id': chat_id, 'message_ids': message_ids, 'user_display': user_display}
            )
            logger.info(f"Запланировано автоматическое удаление сообщений {message_ids} через 30 минут для пользователя {user_display}")
        else:
            query.message.reply_text(f"❌ {'Вопрос' if data_type == 'guide' else 'Шаблон'} не найден!", reply_markup=MAIN_MENU)
        context.user_data['conversation_state'] = f'SHOW_{data_type.upper()}_ANSWER'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в show_answer для пользователя {user_display}: {e}", exc_info=True)
        query.message.reply_text(
            "❌ Ошибка при отображении ответа. Попробуйте снова.",
            reply_markup=MAIN_MENU
        )
        return ConversationHandler.END

# Обработка пагинации
@restrict_access
def handle_pagination(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    try:
        data_type, _, page = query.data.split('_')
        page = int(page)
        data = context.user_data.get('data', load_data(data_type))
        if data_type == 'guide':
            display_guide_page(update, context, data, page, data_type)
        else:
            display_template_page(update, context, data, page)
        context.user_data['conversation_state'] = f'{data_type.upper()}_PAGINATION'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в handle_pagination для пользователя {update.effective_user.id}: {e}", exc_info=True)
        query.message.reply_text(
            "❌ Ошибка при переключении страницы. Попробуйте снова.",
            reply_markup=MAIN_MENU
        )
        return ConversationHandler.END

# Обработка действий с шаблонами
@restrict_access
def handle_template_action(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    action = query.data
    try:
        if action == 'add_template':
            return add_template(update, context)
        elif action == 'edit_template':
            return edit_template(update, context)
        elif action == 'cancel_template':
            context.user_data.clear()
            context.user_data['conversation_state'] = 'CANCEL_TEMPLATE'
            context.user_data['conversation_active'] = False
            query.message.reply_text("🚪 Вернулись в главное меню.", reply_markup=MAIN_MENU)
            return ConversationHandler.END
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в handle_template_action для пользователя {update.effective_user.id}: {e}", exc_info=True)
        query.message.reply_text(
            "❌ Ошибка при обработке действия с шаблоном. Попробуйте снова.",
            reply_markup=MAIN_MENU
        )
        return ConversationHandler.END

# Поиск по ключевым словам
@restrict_access
def perform_search(update: Update, context: CallbackContext):
    if context.user_data.get('conversation_active', False):
        logger.info(f"Пользователь {update.effective_user.id} находится в активном диалоге ({context.user_data.get('conversation_state')}), пропускаем perform_search")
        return
    try:
        logger.info(f"Пользователь {update.effective_user.id} вошел в perform_search с текстом: '{update.message.text}'")
        if not update.message or not update.message.text:
            logger.error(f"Пользователь {update.effective_user.id} отправил пустое или неверное сообщение для поиска")
            update.message.reply_text(
                "❌ Пожалуйста, введите ключевое слово для поиска!",
                reply_markup=MAIN_MENU
            )
            return
        keyword = update.message.text.lower().strip()
        logger.info(f"Пользователь {update.effective_user.id} выполнил поиск по ключевому слову '{keyword}'")
        guide = load_guide()
        if not isinstance(guide, dict) or "questions" not in guide or not isinstance(guide["questions"], list):
            logger.error("Неверная структура guide.json")
            update.message.reply_text(
                "❌ Ошибка: Неверная структура файла guide.json. Свяжитесь с администратором.",
                reply_markup=MAIN_MENU
            )
            return
        results = [
            q for q in guide["questions"]
            if isinstance(q, dict) and
            "question" in q and isinstance(q["question"], str) and
            "answer" in q and isinstance(q["answer"], str) and
            (keyword in q["question"].lower() or keyword in q["answer"].lower())
        ]
        if not results:
            logger.info(f"Результаты для ключевого слова '{keyword}' не найдены")
            update.message.reply_text(
                "🔍 Ничего не найдено. Попробуйте другое ключевое слово!",
                reply_markup=MAIN_MENU
            )
            return
        context.user_data['data'] = {"questions": results}
        context.user_data['page'] = 0
        context.user_data['data_type'] = 'guide'
        context.user_data['conversation_state'] = 'SEARCH'
        context.user_data['conversation_active'] = False
        display_guide_page(update, context, {"questions": results}, 0, 'guide')
        return
    except Exception as e:
        logger.error(f"Ошибка в perform_search для пользователя {update.effective_user.id}: {str(e)}", exc_info=True)
        context.user_data.clear()
        context.user_data['conversation_state'] = 'ERROR'
        context.user_data['conversation_active'] = False
        update.message.reply_text(
            "❌ Произошла ошибка при поиске. Попробуйте снова или свяжитесь с администратором.",
            reply_markup=MAIN_MENU
        )
        return

# Добавление пункта в справочник
@restrict_access
def add_point(update: Update, context: CallbackContext):
    logger.info(f"Пользователь {update.effective_user.id} начал добавление нового пункта справочника")
    context.user_data.clear()
    context.user_data['photos'] = []
    context.user_data['media_group_id'] = None
    context.user_data['last_photo_time'] = None
    context.user_data['point_saved'] = False
    context.user_data['loading_message_id'] = None
    context.user_data['timeout_task'] = None
    context.user_data['conversation_state'] = 'ADD_GUIDE'
    context.user_data['conversation_active'] = True
    context.user_data['data_type'] = 'guide'
    try:
        message = update.message.reply_text(
            "➕ Введите вопрос (например, 'Ошибка входа в систему'):\n(Напишите /cancel для отмены)",
            reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True),
            quote=False
        )
        logger.info(f"Пользователь {update.effective_user.id} успешно запустил add_point")
        return GUIDE_QUESTION
    except Exception as e:
        logger.error(f"Ошибка в add_point для пользователя {update.effective_user.id}: {e}", exc_info=True)
        context.user_data.clear()
        context.user_data['conversation_state'] = 'ERROR'
        context.user_data['conversation_active'] = False
        update.message.reply_text(
            "❌ Ошибка при добавлении пункта. Попробуйте снова.",
            reply_markup=MAIN_MENU
        )
        return ConversationHandler.END

# Добавление шаблона
@restrict_access
def add_template(update: Update, context: CallbackContext):
    logger.info(f"Пользователь {update.effective_user.id} начал добавление нового шаблона")
    context.user_data.clear()
    context.user_data['photos'] = []
    context.user_data['media_group_id'] = None
    context.user_data['last_photo_time'] = None
    context.user_data['point_saved'] = False
    context.user_data['loading_message_id'] = None
    context.user_data['timeout_task'] = None
    context.user_data['conversation_state'] = 'ADD_TEMPLATE'
    context.user_data['conversation_active'] = True
    context.user_data['data_type'] = 'template'
    try:
        if update.message:
            update.message.reply_text(
                "➕ Введите вопрос для шаблона (например, 'Шаблон ответа на запрос'):\n(Напишите /cancel для отмены)",
                reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True),
                quote=False
            )
        elif update.callback_query:
            update.callback_query.message.reply_text(
                "➕ Введите вопрос для шаблона (например, 'Шаблон ответа на запрос'):\n(Напишите /cancel для отмены)",
                reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True),
                quote=False
            )
        logger.info(f"Пользователь {update.effective_user.id} успешно запустил add_template")
        return TEMPLATE_QUESTION
    except Exception as e:
        logger.error(f"Ошибка в add_template для пользователя {update.effective_user.id}: {e}", exc_info=True)
        context.user_data.clear()
        context.user_data['conversation_state'] = 'ERROR'
        context.user_data['conversation_active'] = False
        if update.message:
            update.message.reply_text(
                "❌ Ошибка при добавлении шаблона. Попробуйте снова.",
                reply_markup=MAIN_MENU
            )
        elif update.callback_query:
            update.callback_query.message.reply_text(
                "❌ Ошибка при добавлении шаблона. Попробуйте снова.",
                reply_markup=MAIN_MENU
            )
        return ConversationHandler.END

# Обработка вопроса
@restrict_access
def receive_question(update: Update, context: CallbackContext):
    logger.info(f"Пользователь {update.effective_user.id} вошел в receive_question, состояние: {context.user_data.get('conversation_state')}, текст: '{update.message.text}'")
    if not context.user_data.get('conversation_active', False):
        logger.warning(f"Пользователь {update.effective_user.id} попытался отправить вопрос в неактивном диалоге")
        update.message.reply_text(
            f"❌ Пожалуйста, начните добавление {'пункта' if context.user_data.get('data_type') == 'guide' else 'шаблона'} заново.",
            reply_markup=MAIN_MENU,
            quote=False
        )
        context.user_data.clear()
        context.user_data['conversation_state'] = 'INVALID_QUESTION'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    data_type = context.user_data.get('data_type', 'guide')
    if data_type not in ['guide', 'template']:
        logger.error(f"Недопустимый data_type: {data_type}")
        update.message.reply_text(
            "❌ Ошибка: Неверный тип данных. Начните заново.",
            reply_markup=MAIN_MENU,
            quote=False
        )
        context.user_data.clear()
        context.user_data['conversation_state'] = 'INVALID_DATA_TYPE'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    logger.info(f"Пользователь {update.effective_user.id} ввел вопрос для {data_type}: {update.message.text}")
    context.user_data['new_question'] = update.message.text
    context.user_data['conversation_state'] = f'RECEIVE_{data_type.upper()}_QUESTION'
    prompt = "Введите ответ"
    if ENABLE_PHOTOS:
        prompt += " (или отправьте фото/альбом с подписью)"
    prompt += ":\n(Напишите /cancel для отмены)"
    update.message.reply_text(
        prompt,
        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True),
        quote=False
    )
    logger.info(f"Переход в состояние {'GUIDE_ANSWER' if data_type == 'guide' else 'TEMPLATE_ANSWER'} для пользователя {update.effective_user.id}")
    return GUIDE_ANSWER if data_type == 'guide' else TEMPLATE_ANSWER

# Обработка ответа
@restrict_access
def receive_answer(update: Update, context: CallbackContext):
    if not context.user_data.get('conversation_active', False) or 'new_question' not in context.user_data:
        logger.warning(f"Пользователь {update.effective_user.id} попытался отправить ответ без активного диалога или вопроса")
        update.message.reply_text(
            f"❌ Пожалуйста, начните добавление {'пункта' if context.user_data.get('data_type') == 'guide' else 'шаблона'} заново.",
            reply_markup=MAIN_MENU,
            quote=False
        )
        context.user_data.clear()
        context.user_data['conversation_state'] = 'INVALID_ANSWER'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    data_type = context.user_data.get('data_type', 'guide')
    if data_type not in ['guide', 'template']:
        logger.error(f"Недопустимый data_type: {data_type}")
        update.message.reply_text(
            "❌ Ошибка: Неверный тип данных. Начните заново.",
            reply_markup=MAIN_MENU,
            quote=False
        )
        context.user_data.clear()
        context.user_data['conversation_state'] = 'INVALID_DATA_TYPE'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    if 'photos' not in context.user_data:
        context.user_data['photos'] = []
    context.user_data['answer'] = update.message.caption if update.message.photo else update.message.text if update.message.text else ""
    context.user_data['conversation_state'] = f'RECEIVE_{data_type.upper()}_ANSWER'
    if ENABLE_PHOTOS and update.message.photo:
        if update.message.media_group_id:
            context.user_data['media_group_id'] = update.message.media_group_id
            context.user_data['photos'].append(update.message.photo[-1].file_id)
            context.user_data['last_photo_time'] = update.message.date
            logger.info(f"Пользователь {update.effective_user.id} добавил фото в альбом {data_type} media group {update.message.media_group_id}: {update.message.photo[-1].file_id}")
            if len(context.user_data['photos']) == 1:
                loading_message = update.message.reply_text("⏳ Загрузка...", quote=False)
                context.user_data['loading_message_id'] = loading_message.message_id
                if not context.user_data.get('timeout_task'):
                    context.user_data['timeout_task'] = context.job_queue.run_once(
                        check_album_timeout, 2, context=(update, context)
                    )
            return GUIDE_ANSWER_PHOTOS if data_type == 'guide' else TEMPLATE_ANSWER_PHOTOS
        else:
            context.user_data['photos'] = [update.message.photo[-1].file_id]
            logger.info(f"Пользователь {update.effective_user.id} добавил одно фото в {data_type}: {context.user_data['photos']}")
    save_new_point(update, context, send_message=True)
    logger.info(f"Пользователь {update.effective_user.id} завершил add_{data_type}_conv в receive_answer")
    context.user_data.clear()
    context.user_data['conversation_state'] = f'{data_type.upper()}_POINT_SAVED'
    context.user_data['conversation_active'] = False
    return ConversationHandler.END

# Проверка таймаута альбома
def check_album_timeout(context: CallbackContext):
    update, context = context.job.context
    if context.user_data.get('last_photo_time') == update.message.date and not context.user_data.get('point_saved'):
        data_type = context.user_data.get('data_type', 'guide')
        logger.info(f"Пользователь {update.effective_user.id} завершил альбом для {data_type} media group {context.user_data.get('media_group_id')}")
        if context.user_data.get('loading_message_id'):
            try:
                context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=context.user_data['loading_message_id']
                )
                logger.info(f"Пользователь {update.effective_user.id} удалил сообщение о загрузке")
            except Exception as e:
                logger.error(f"Не удалось удалить сообщение о загрузке: {e}")
        save_new_point(update, context, send_message=True)
        context.user_data['point_saved'] = True
        context.user_data['timeout_task'] = None
        logger.info(f"Пользователь {update.effective_user.id} завершил add_{data_type}_conv в check_album_timeout")
        context.user_data.clear()
        context.user_data['conversation_state'] = f'{data_type.upper()}_ALBUM_SAVED'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    return None

# Сохранение нового пункта
def save_new_point(update: Update, context: CallbackContext, send_message: bool = False):
    if context.user_data.get('point_saved'):
        logger.info(f"Пользователь {update.effective_user.id} пропустил сохранение пункта, так как он уже сохранен")
        return
    data_type = context.user_data.get('data_type', 'guide')
    data = load_data(data_type)
    key = 'questions' if data_type == 'guide' else 'templates'
    new_id = max([q["id"] for q in data[key]], default=0) + 1
    new_point = {
        "id": new_id,
        "question": context.user_data['new_question'],
        "answer": context.user_data['answer']
    }
    if ENABLE_PHOTOS and context.user_data.get('photos'):
        new_point['photos'] = context.user_data['photos']
        logger.info(f"Пользователь {update.effective_user.id} добавил фото в {data_type}: {new_point['photos']}")
    data[key].append(new_point)
    save_data(data_type, data)
    logger.info(f"Пользователь {update.effective_user.id} добавил новый пункт {data_type}: {new_point['question']}")
    if send_message:
        update.message.reply_text(
            f"➕ {'Пункт' if data_type == 'guide' else 'Шаблон'} добавлен!\nВопрос: {new_point['question']}",
            reply_markup=MAIN_MENU,
            quote=False
        )
    context.user_data['point_saved'] = True

# Обработка фотографий для ответа
@restrict_access
def receive_answer_photos(update: Update, context: CallbackContext):
    if not context.user_data.get('conversation_active', False) or 'new_question' not in context.user_data:
        logger.warning(f"Пользователь {update.effective_user.id} попытался отправить фото без активного диалога или вопроса")
        update.message.reply_text(
            f"❌ Пожалуйста, начните добавление {'пункта' if context.user_data.get('data_type') == 'guide' else 'шаблона'} заново.",
            reply_markup=MAIN_MENU,
            quote=False
        )
        context.user_data.clear()
        context.user_data['conversation_state'] = 'INVALID_PHOTOS'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    data_type = context.user_data.get('data_type', 'guide')
    if data_type not in ['guide', 'template']:
        logger.error(f"Недопустимый data_type: {data_type}")
        update.message.reply_text(
            "❌ Ошибка: Неверный тип данных. Начните заново.",
            reply_markup=MAIN_MENU,
            quote=False
        )
        context.user_data.clear()
        context.user_data['conversation_state'] = 'INVALID_DATA_TYPE'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    if 'photos' not in context.user_data:
        context.user_data['photos'] = []
    if update.message.media_group_id == context.user_data.get('media_group_id'):
        context.user_data['photos'].append(update.message.photo[-1].file_id)
        context.user_data['last_photo_time'] = update.message.date
        logger.info(f"Пользователь {update.effective_user.id} добавил фото в альбом {data_type}: {update.message.photo[-1].file_id}")
        if not context.user_data.get('timeout_task'):
            context.user_data['timeout_task'] = context.job_queue.run_once(
                check_album_timeout, 2, context=(update, context)
            )
        return GUIDE_ANSWER_PHOTOS if data_type == 'guide' else TEMPLATE_ANSWER_PHOTOS
    if not context.user_data.get('point_saved') and context.user_data.get('photos'):
        logger.info(f"Пользователь {update.effective_user.id} завершил альбом для {data_type} media group {context.user_data.get('media_group_id')} из-за нового сообщения")
        if context.user_data.get('timeout_task'):
            context.user_data['timeout_task'].cancel()
            context.user_data['timeout_task'] = None
            logger.info(f"Пользователь {update.effective_user.id} отменил задачу таймаута в receive_answer_photos")
        if context.user_data.get('loading_message_id'):
            try:
                context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=context.user_data['loading_message_id']
                )
                logger.info(f"Пользователь {update.effective_user.id} удалил сообщение о загрузке")
            except Exception as e:
                logger.error(f"Не удалось удалить сообщение о загрузке: {e}")
        save_new_point(update, context, send_message=True)
        context.user_data['point_saved'] = True
        logger.info(f"Пользователь {update.effective_user.id} завершил add_{data_type}_conv в receive_answer_photos")
        context.user_data.clear()
        context.user_data['conversation_state'] = f'{data_type.upper()}_PHOTOS_SAVED'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    return GUIDE_ANSWER_PHOTOS if data_type == 'guide' else TEMPLATE_ANSWER_PHOTOS

# Редактирование пункта справочника
@restrict_access
def edit_point(update: Update, context: CallbackContext):
    logger.info(f"Пользователь {update.effective_user.id} начал редактирование пункта справочника")
    context.user_data.clear()
    context.user_data['conversation_state'] = 'EDIT_GUIDE'
    context.user_data['conversation_active'] = True
    context.user_data['data_type'] = 'guide'
    try:
        guide = load_guide()
        if not guide["questions"]:
            update.message.reply_text(
                "📖 Справочник пуст. Нечего редактировать! ➕",
                reply_markup=MAIN_MENU,
                quote=False
            )
            context.user_data['conversation_active'] = False
            return ConversationHandler.END
        context.user_data['data'] = guide
        context.user_data['page'] = 0
        display_guide_edit_page(update, context, guide, 0)
        return GUIDE_EDIT_QUESTION
    except Exception as e:
        logger.error(f"Ошибка в edit_point для пользователя {update.effective_user.id}: {e}", exc_info=True)
        context.user_data.clear()
        context.user_data['conversation_state'] = 'ERROR'
        context.user_data['conversation_active'] = False
        update.message.reply_text(
            "❌ Ошибка при редактировании пункта. Попробуйте снова.",
            reply_markup=MAIN_MENU,
            quote=False
        )
        return ConversationHandler.END

# Редактирование шаблона
@restrict_access
def edit_template(update: Update, context: CallbackContext):
    logger.info(f"Пользователь {update.effective_user.id} начал редактирование шаблона")
    context.user_data.clear()
    context.user_data['conversation_state'] = 'EDIT_TEMPLATE'
    context.user_data['conversation_active'] = True
    context.user_data['data_type'] = 'template'
    try:
        templates = load_templates()
        if not templates["templates"]:
            if update.message:
                update.message.reply_text(
                    "📋 Шаблоны ответов пусты. Нечего редактировать! ➕",
                    reply_markup=MAIN_MENU,
                    quote=False
                )
            elif update.callback_query:
                update.callback_query.message.reply_text(
                    "📋 Шаблоны ответов пусты. Нечего редактировать! ➕",
                    reply_markup=MAIN_MENU,
                    quote=False
                )
            context.user_data['conversation_active'] = False
            return ConversationHandler.END
        context.user_data['data'] = templates
        context.user_data['page'] = 0
        display_template_edit_page(update, context, templates, 0)
        return TEMPLATE_EDIT_QUESTION
    except Exception as e:
        logger.error(f"Ошибка в edit_template для пользователя {update.effective_user.id}: {e}", exc_info=True)
        context.user_data.clear()
        context.user_data['conversation_state'] = 'ERROR'
        context.user_data['conversation_active'] = False
        if update.message:
            update.message.reply_text(
                "❌ Ошибка при редактировании шаблона. Попробуйте снова.",
                reply_markup=MAIN_MENU,
                quote=False
            )
        elif update.callback_query:
            update.callback_query.message.reply_text(
                "❌ Ошибка при редактировании шаблона. Попробуйте снова.",
                reply_markup=MAIN_MENU,
                quote=False
            )
        return ConversationHandler.END

# Отображение страницы редактирования справочника
def display_guide_edit_page(update: Update, context: CallbackContext, data, page):
    try:
        ITEMS_PER_PAGE = 15
        total_items = len(data["questions"])
        total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(0, min(page, total_pages - 1))
        context.user_data['page'] = page
        context.user_data['data'] = data
        context.user_data['data_type'] = 'guide'

        start_idx = page * ITEMS_PER_PAGE
        end_idx = min(start_idx + ITEMS_PER_PAGE, total_items)
        items = data["questions"][start_idx:end_idx]

        keyboard = []
        for item in items:
            if not isinstance(item, dict) or "question" not in item or "id" not in item:
                logger.error(f"Неверные данные справочника: {item}")
                continue
            question_text = item["question"][:100] if len(item["question"]) > 100 else item["question"]
            callback_data = f'edit_guide_question_{item["id"]}'
            logger.info(f"Сформирована кнопка редактирования: callback_data={callback_data}, вопрос={question_text}")
            keyboard.append([InlineKeyboardButton(f"📄 {question_text}", callback_data=callback_data)])

        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'edit_guide_page_{page-1}'))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f'edit_guide_page_{page+1}'))
        nav_buttons.append(InlineKeyboardButton("🚪 Отмена", callback_data='cancel_guide_edit'))
        keyboard.append(nav_buttons)

        reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"✏️ Выберите вопрос для редактирования (страница {page + 1}/{total_pages}):"
        if update.message:
            update.message.reply_text(text, reply_markup=reply_markup, quote=False)
        elif update.callback_query:
            update.callback_query.message.edit_text(text, reply_markup=reply_markup)
        logger.info(f"Пользователь {update.effective_user.id} просмотрел страницу редактирования справочника {page + 1}")
        context.user_data['conversation_state'] = 'EDIT_GUIDE_PAGE'
        return GUIDE_EDIT_QUESTION
    except Exception as e:
        logger.error(f"Ошибка в display_guide_edit_page для пользователя {update.effective_user.id}: {e}", exc_info=True)
        context.user_data.clear()
        context.user_data['conversation_state'] = 'ERROR'
        context.user_data['conversation_active'] = False
        if update.message:
            update.message.reply_text(
                "❌ Ошибка при отображении страницы редактирования. Попробуйте снова.",
                reply_markup=MAIN_MENU,
                quote=False
            )
        elif update.callback_query:
            update.callback_query.message.reply_text(
                "❌ Ошибка при отображении страницы редактирования. Попробуйте снова.",
                reply_markup=MAIN_MENU,
                quote=False
            )
        return ConversationHandler.END

# Отображение страницы редактирования шаблонов
def display_template_edit_page(update: Update, context: CallbackContext, data, page):
    try:
        ITEMS_PER_PAGE = 15
        total_items = len(data["templates"])
        total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(0, min(page, total_pages - 1))
        context.user_data['page'] = page
        context.user_data['data'] = data
        context.user_data['data_type'] = 'template'

        start_idx = page * ITEMS_PER_PAGE
        end_idx = min(start_idx + ITEMS_PER_PAGE, total_items)
        items = data["templates"][start_idx:end_idx]

        keyboard = []
        for item in items:
            if not isinstance(item, dict) or "question" not in item or "id" not in item:
                logger.error(f"Неверные данные шаблона: {item}")
                continue
            question_text = item["question"][:100] if len(item["question"]) > 100 else item["question"]
            callback_data = f'edit_template_question_{item["id"]}'
            logger.info(f"Сформирована кнопка редактирования: callback_data={callback_data}, вопрос={question_text}")
            keyboard.append([InlineKeyboardButton(f"📄 {question_text}", callback_data=callback_data)])

        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'edit_template_page_{page-1}'))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f'edit_template_page_{page+1}'))
        nav_buttons.append(InlineKeyboardButton("🚪 Отмена", callback_data='cancel_template_edit'))
        keyboard.append(nav_buttons)

        reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"✏️ Выберите шаблон для редактирования (страница {page + 1}/{total_pages}):"
        if update.message:
            update.message.reply_text(text, reply_markup=reply_markup, quote=False)
        elif update.callback_query:
            update.callback_query.message.edit_text(text, reply_markup=reply_markup)
        logger.info(f"Пользователь {update.effective_user.id} просмотрел страницу редактирования шаблонов {page + 1}")
        context.user_data['conversation_state'] = 'EDIT_TEMPLATE_PAGE'
        return TEMPLATE_EDIT_QUESTION
    except Exception as e:
        logger.error(f"Ошибка в display_template_edit_page для пользователя {update.effective_user.id}: {e}", exc_info=True)
        context.user_data.clear()
        context.user_data['conversation_state'] = 'ERROR'
        context.user_data['conversation_active'] = False
        if update.message:
            update.message.reply_text(
                "❌ Ошибка при отображении страницы редактирования. Попробуйте снова.",
                reply_markup=MAIN_MENU,
                quote=False
            )
        elif update.callback_query:
            update.callback_query.message.reply_text(
                "❌ Ошибка при отображении страницы редактирования. Попробуйте снова.",
                reply_markup=MAIN_MENU,
                quote=False
            )
        return ConversationHandler.END

# Обработка пагинации редактирования
@restrict_access
def handle_edit_pagination(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    try:
        data_type = query.data.split('_')[1]
        logger.info(f"Пользователь {update.effective_user.id} в handle_edit_pagination, callback_data: {query.data}")
        if query.data == f'cancel_{data_type}_edit':
            context.user_data.clear()
            context.user_data['conversation_state'] = f'CANCEL_{data_type.upper()}_EDIT'
            context.user_data['conversation_active'] = False
            query.message.reply_text(
                f"🚪 Редактирование {'пункта' if data_type == 'guide' else 'шаблона'} отменено.",
                reply_markup=MAIN_MENU,
                quote=False
            )
            return ConversationHandler.END
        page = int(query.data.split('_')[3])
        data = context.user_data.get('data', load_data(data_type))
        if data_type == 'guide':
            display_guide_edit_page(update, context, data, page)
            return GUIDE_EDIT_QUESTION
        else:
            display_template_edit_page(update, context, data, page)
            return TEMPLATE_EDIT_QUESTION
    except Exception as e:
        logger.error(f"Ошибка в handle_edit_pagination для пользователя {update.effective_user.id}: {e}", exc_info=True)
        context.user_data.clear()
        context.user_data['conversation_state'] = 'ERROR'
        context.user_data['conversation_active'] = False
        query.message.reply_text(
            "❌ Ошибка при переключении страницы редактирования. Попробуйте снова.",
            reply_markup=MAIN_MENU,
            quote=False
        )
        return ConversationHandler.END

# Выбор вопроса для редактирования
@restrict_access
def select_edit_question(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    try:
        logger.info(f"Пользователь {update.effective_user.id} вошел в select_edit_question с callback_data: {query.data}")
        data_type = query.data.split('_')[1]
        question_id = int(query.data.split('_')[3])
        context.user_data['edit_question_id'] = question_id
        logger.info(f"Пользователь {update.effective_user.id} выбрал для редактирования {data_type} ID {question_id}")
        context.user_data['conversation_state'] = f'SELECT_EDIT_{data_type.upper()}_QUESTION'
        keyboard = [
            [InlineKeyboardButton("Изменить вопрос", callback_data=f'edit_{data_type}_field_question')],
            [InlineKeyboardButton("Изменить ответ", callback_data=f'edit_{data_type}_field_answer')],
            [InlineKeyboardButton("Удалить пункт", callback_data=f'edit_{data_type}_field_delete')],
        ]
        if ENABLE_PHOTOS:
            keyboard.insert(2, [InlineKeyboardButton("Добавить/изменить фото", callback_data=f'edit_{data_type}_field_photo')])
        keyboard.append([InlineKeyboardButton("🚪 Отмена", callback_data=f'cancel_{data_type}_edit')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(
            f"✏️ Что хотите изменить в {'вопросе' if data_type == 'guide' else 'шаблоне'}?",
            reply_markup=reply_markup
        )
        logger.info(f"Пользователь {update.effective_user.id} перешел в состояние {'GUIDE_EDIT_FIELD' if data_type == 'guide' else 'TEMPLATE_EDIT_FIELD'}")
        return GUIDE_EDIT_FIELD if data_type == 'guide' else TEMPLATE_EDIT_FIELD
    except Exception as e:
        logger.error(f"Ошибка в select_edit_question для пользователя {update.effective_user.id}: {e}", exc_info=True)
        context.user_data.clear()
        context.user_data['conversation_state'] = 'ERROR'
        context.user_data['conversation_active'] = False
        query.message.reply_text(
            "❌ Ошибка при выборе пункта для редактирования. Попробуйте снова.",
            reply_markup=MAIN_MENU,
            quote=False
        )
        return ConversationHandler.END

# Обработка выбора поля для редактирования
@restrict_access
def receive_edit_field(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    try:
        data_type = query.data.split('_')[1]
        logger.info(f"Пользователь {update.effective_user.id} вошел в receive_edit_field с callback_data: {query.data}")
        if query.data == f'cancel_{data_type}_edit':
            context.user_data.clear()
            context.user_data['conversation_state'] = f'CANCEL_{data_type.upper()}_EDIT'
            context.user_data['conversation_active'] = False
            query.message.reply_text(
                f"🚪 Редактирование {'пункта' if data_type == 'guide' else 'шаблона'} отменено.",
                reply_markup=MAIN_MENU,
                quote=False
            )
            return ConversationHandler.END
        context.user_data['edit_field'] = query.data
        logger.info(f"Пользователь {update.effective_user.id} выбрал поле для редактирования {data_type}: {query.data}")
        context.user_data['conversation_state'] = f'RECEIVE_{data_type.upper()}_EDIT_FIELD'
        if query.data == f'edit_{data_type}_field_delete':
            data = load_data(data_type)
            key = 'questions' if data_type == 'guide' else 'templates'
            question_id = context.user_data['edit_question_id']
            data[key] = [q for q in data[key] if q["id"] != question_id]
            save_data(data_type, data)
            context.user_data.clear()
            context.user_data['conversation_state'] = f'{data_type.upper()}_POINT_DELETED'
            context.user_data['conversation_active'] = False
            query.message.reply_text(
                f"🗑️ {'Пункт' if data_type == 'guide' else 'Шаблон'} удалён!",
                reply_markup=MAIN_MENU,
                quote=False
            )
            logger.info(f"Пользователь {update.effective_user.id} удалил {data_type} ID {question_id}")
            return ConversationHandler.END
        field = "вопрос" if query.data == f'edit_{data_type}_field_question' else "ответ" if query.data == f'edit_{data_type}_field_answer' else "фото/альбом"
        prompt = f"✏️ Введите новый {field}:\n(Напишите /cancel для отмены)"
        query.message.reply_text(
            prompt,
            reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True),
            quote=False
        )
        logger.info(f"Пользователь {update.effective_user.id} перешел в состояние {'GUIDE_EDIT_VALUE' if data_type == 'guide' else 'TEMPLATE_EDIT_VALUE'}")
        return GUIDE_EDIT_VALUE if data_type == 'guide' else TEMPLATE_EDIT_VALUE
    except Exception as e:
        logger.error(f"Ошибка в receive_edit_field для пользователя {update.effective_user.id}: {e}", exc_info=True)
        context.user_data.clear()
        context.user_data['conversation_state'] = 'ERROR'
        context.user_data['conversation_active'] = False
        query.message.reply_text(
            "❌ Ошибка при выборе поля для редактирования. Попробуйте снова.",
            reply_markup=MAIN_MENU,
            quote=False
        )
        return ConversationHandler.END

# Обработка значения для редактирования
@restrict_access
def receive_edit_value(update: Update, context: CallbackContext):
    if not context.user_data.get('conversation_active', False):
        logger.warning(f"Пользователь {update.effective_user.id} попытался отправить значение для редактирования в неактивном диалоге")
        update.message.reply_text(
            f"❌ Пожалуйста, начните редактирование {'пункта' if context.user_data.get('data_type') == 'guide' else 'шаблона'} заново.",
            reply_markup=MAIN_MENU,
            quote=False
        )
        context.user_data.clear()
        context.user_data['conversation_state'] = 'INVALID_EDIT_VALUE'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    data_type = context.user_data.get('data_type', 'guide')
    try:
        data = load_data(data_type)
        key = 'questions' if data_type == 'guide' else 'templates'
        question_id = context.user_data['edit_question_id']
        field = context.user_data['edit_field']
        for q in data[key]:
            if q["id"] == question_id:
                if field == f'edit_{data_type}_field_question':
                    q['question'] = update.message.text
                    logger.info(f"Пользователь {update.effective_user.id} обновил вопрос для {data_type} ID {question_id}: {q['question']}")
                elif field == f'edit_{data_type}_field_answer':
                    q['answer'] = update.message.text
                    logger.info(f"Пользователь {update.effective_user.id} обновил ответ для {data_type} ID {question_id}: {q['answer']}")
                elif field == f'edit_{data_type}_field_photo' and ENABLE_PHOTOS:
                    if update.message.photo:
                        q['photos'] = [update.message.photo[-1].file_id]
                        logger.info(f"Пользователь {update.effective_user.id} обновил фото для {data_type} ID {question_id}: {q['photos']}")
                        q.pop('photo', None)
                    else:
                        update.message.reply_text(
                            f"❌ Пожалуйста, отправьте фото или альбом!\n(Напишите /cancel для отмены)",
                            reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True),
                            quote=False
                        )
                        return GUIDE_EDIT_VALUE if data_type == 'guide' else TEMPLATE_EDIT_VALUE
                break
        save_data(data_type, data)
        logger.info(f"Пользователь {update.effective_user.id} обновил {field} для {data_type} ID {question_id}")
        context.user_data.clear()
        context.user_data['conversation_state'] = f'EDIT_{data_type.upper()}_VALUE'
        context.user_data['conversation_active'] = False
        update.message.reply_text(
            f"✏️ {'Вопрос' if field == f'edit_{data_type}_field_question' else 'Ответ' if field == f'edit_{data_type}_field_answer' else 'Фото'} обновлён!",
            reply_markup=MAIN_MENU,
            quote=False
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в receive_edit_value для пользователя {update.effective_user.id}: {e}", exc_info=True)
        context.user_data.clear()
        context.user_data['conversation_state'] = 'ERROR'
        context.user_data['conversation_active'] = False
        update.message.reply_text(
            "❌ Ошибка при обновлении значения. Попробуйте снова.",
            reply_markup=MAIN_MENU,
            quote=False
        )
        return ConversationHandler.END

# Обработчик неподдерживаемых сообщений
@restrict_access
def handle_invalid_input(update: Update, context: CallbackContext):
    logger.warning(f"Пользователь {update.effective_user.id} отправил неподдерживаемый ввод в состоянии диалога: {context.user_data.get('conversation_state')}")
    data_type = context.user_data.get('data_type', 'guide')
    context.user_data.clear()
    context.user_data['conversation_state'] = 'INVALID_INPUT'
    context.user_data['conversation_active'] = False
    update.message.reply_text(
        f"❌ Пожалуйста, отправьте текст или фото/альбом (для ответа/фото)!\n(Напишите /cancel для отмены)",
        reply_markup=MAIN_MENU,
        quote=False
    )
    return ConversationHandler.END

# Запуск бота
def main():
    updater = Updater(os.getenv("BOT_TOKEN"), use_context=True)
    dp = updater.dispatcher
    dp.add_error_handler(error_handler)

    # Регистрация ConversationHandler'ов в начале для повышения приоритета
    guide_add_conv = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex(r'^➕ Добавить пункт$'), add_point)],
        states={
            GUIDE_QUESTION: [
                MessageHandler(
                    Filters.text & ~Filters.command,
                    receive_question
                ),
            ],
            GUIDE_ANSWER: [
                MessageHandler(
                    Filters.text & ~Filters.command,
                    receive_answer
                ),
                MessageHandler(Filters.photo, receive_answer) if ENABLE_PHOTOS else None,
                MessageHandler(~(Filters.text | Filters.photo) & ~Filters.command, handle_invalid_input),
            ],
            GUIDE_ANSWER_PHOTOS: [
                MessageHandler(Filters.photo, receive_answer_photos) if ENABLE_PHOTOS else None,
                MessageHandler(
                    Filters.text & ~Filters.command,
                    receive_answer
                ),
                MessageHandler(~(Filters.text | Filters.photo) & ~Filters.command, handle_invalid_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=False,
    )

    template_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_template, pattern='^add_template$')],
        states={
            TEMPLATE_QUESTION: [
                MessageHandler(
                    Filters.text & ~Filters.command,
                    receive_question
                ),
            ],
            TEMPLATE_ANSWER: [
                MessageHandler(
                    Filters.text & ~Filters.command,
                    receive_answer
                ),
                MessageHandler(Filters.photo, receive_answer) if ENABLE_PHOTOS else None,
                MessageHandler(~(Filters.text | Filters.photo) & ~Filters.command, handle_invalid_input),
            ],
            TEMPLATE_ANSWER_PHOTOS: [
                MessageHandler(Filters.photo, receive_answer_photos) if ENABLE_PHOTOS else None,
                MessageHandler(
                    Filters.text & ~Filters.command,
                    receive_answer
                ),
                MessageHandler(~(Filters.text | Filters.photo) & ~Filters.command, handle_invalid_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=False,
    )

    guide_edit_conv = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex(r'^✏️ Редактировать пункт$'), edit_point)],
        states={
            GUIDE_EDIT_QUESTION: [
                CallbackQueryHandler(select_edit_question, pattern=r'^edit_guide_question_\d+$'),
                CallbackQueryHandler(handle_edit_pagination, pattern=r'^(edit_guide_page_\d+|cancel_guide_edit)$'),
            ],
            GUIDE_EDIT_FIELD: [
                CallbackQueryHandler(receive_edit_field, pattern=r'^(edit_guide_field_(question|answer|photo|delete)|cancel_guide_edit)$'),
            ],
            GUIDE_EDIT_VALUE: [
                MessageHandler(
                    Filters.text & ~Filters.command,
                    receive_edit_value
                ),
                MessageHandler(Filters.photo, receive_edit_value) if ENABLE_PHOTOS else None,
                MessageHandler(~(Filters.text | Filters.photo) & ~Filters.command, handle_invalid_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        per_message=False,
        allow_reentry=False,
    )

    template_edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_template, pattern='^edit_template$')],
        states={
            TEMPLATE_EDIT_QUESTION: [
                CallbackQueryHandler(select_edit_question, pattern=r'^edit_template_question_\d+$'),
                CallbackQueryHandler(handle_edit_pagination, pattern=r'^(edit_template_page_\d+|cancel_template_edit)$'),
            ],
            TEMPLATE_EDIT_FIELD: [
                CallbackQueryHandler(receive_edit_field, pattern=r'^(edit_template_field_(question|answer|photo|delete)|cancel_template_edit)$'),
            ],
            TEMPLATE_EDIT_VALUE: [
                MessageHandler(
                    Filters.text & ~Filters.command,
                    receive_edit_value
                ),
                MessageHandler(Filters.photo, receive_edit_value) if ENABLE_PHOTOS else None,
                MessageHandler(~(Filters.text | Filters.photo) & ~Filters.command, handle_invalid_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        per_message=False,
        allow_reentry=False,
    )

    # Регистрация ConversationHandler'ов
    dp.add_handler(guide_add_conv)
    dp.add_handler(template_add_conv)
    dp.add_handler(guide_edit_conv)
    dp.add_handler(template_edit_conv)

    # Регистрация основных команд
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("cancel", cancel))

    # Регистрация обработчиков меню
    dp.add_handler(MessageHandler(Filters.regex(r'^📖 Справочник$'), open_guide))
    dp.add_handler(MessageHandler(Filters.regex(r'^📋 Шаблоны ответов$'), open_templates))
    dp.add_handler(MessageHandler(Filters.regex(r'^➕ Добавить пункт$'), add_point))
    dp.add_handler(MessageHandler(Filters.regex(r'^✏️ Редактировать пункт$'), edit_point))

    # Регистрация обработчиков callback-запросов
    dp.add_handler(CallbackQueryHandler(handle_pagination, pattern=r'^(guide|template)_page_\d+$'))
    dp.add_handler(CallbackQueryHandler(show_answer, pattern=r'^(guide|template)_question_\d+$'))
    dp.add_handler(CallbackQueryHandler(handle_template_action, pattern='^(add_template|edit_template|cancel_template)$'))
    dp.add_handler(CallbackQueryHandler(delete_answer, pattern='^delete_answer$'))

    # Регистрация обработчика поиска
    dp.add_handler(MessageHandler(
        Filters.text & ~Filters.command & ~Filters.regex(r'^(📖 Справочник|📋 Шаблоны ответов|➕ Добавить пункт|✏️ Редактировать пункт)$'),
        perform_search
    ))

    logger.info("Бот запущен...")
    updater.start_polling(allowed_updates=Update.ALL_TYPES)
    updater.idle()

# Очистка чата (фоновая задача)
def clear_chat(context: CallbackContext, chat_id: int, message_id: int, user_display: str):
    try:
        logger.info(f"Пользователь {user_display} инициировал фоновую очистку чата {chat_id}")
        # Ограничиваем количество удаляемых сообщений до 50
        deleted_count = 0
        for i in range(message_id - 1, max(message_id - 50, 1), -1):
            try:
                context.bot.delete_message(chat_id=chat_id, message_id=i)
                deleted_count += 1
                # Задержка 0.2 секунды для соблюдения лимитов Telegram API
                asyncio.run(asyncio.sleep(0.2))
            except Exception as e:
                logger.debug(f"Не удалось удалить сообщение {i} в чате {chat_id}: {e}")
                continue
        logger.info(f"Чат {chat_id} очищен пользователем {user_display} в фоновом режиме, удалено {deleted_count} сообщений")
    except Exception as e:
        logger.error(f"Ошибка при фоновой очистке чата {chat_id} для пользователя {user_display}: {e}", exc_info=True)

# Планирование автоматического удаления сообщения
def schedule_message_deletion(context: CallbackContext):
    try:
        job_data = context.job.context
        chat_id = job_data['chat_id']
        message_ids = job_data['message_ids']
        user_display = job_data['user_display']
        for message_id in message_ids:
            try:
                context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                logger.info(f"Автоматически удалено сообщение {message_id} в чате {chat_id} для пользователя {user_display}")
            except Exception as e:
                logger.debug(f"Не удалось автоматически удалить сообщение {message_id} в чате {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка при автоматическом удалении сообщения для пользователя {user_display}: {e}", exc_info=True)

# Обработка нажатия на кнопку удаления ответа
@restrict_access
def delete_answer(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    try:
        chat_id = query.message.chat_id
        user_display = context.user_data.get('user_display', f"ID {update.effective_user.id}")
        # Удаляем все сообщения, связанные с ответом
        message_ids = context.user_data.get('answer_message_ids', [query.message.message_id])
        for message_id in message_ids:
            try:
                context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                logger.info(f"Пользователь {user_display} удалил сообщение {message_id} в чате {chat_id}")
            except Exception as e:
                logger.debug(f"Не удалось удалить сообщение {message_id} в чате {chat_id}: {e}")
        context.user_data.clear()
        context.user_data['conversation_state'] = 'DELETE_ANSWER'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения для пользователя {user_display}: {e}", exc_info=True)
        query.message.reply_text(
            "❌ Не удалось удалить сообщение. Попробуйте снова.",
            reply_markup=MAIN_MENU
        )
        return ConversationHandler.END

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Получен KeyboardInterrupt, завершение работы...")
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}", exc_info=True)