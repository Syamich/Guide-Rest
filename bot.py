import json
import os
import subprocess
import logging
import re
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

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка .env
load_dotenv()
logger.info("Loaded .env file")

# Проверка BOT_TOKEN
if not os.getenv("BOT_TOKEN"):
    logger.error("BOT_TOKEN not found in environment variables")
    raise ValueError("BOT_TOKEN not found in environment variables. Please set it in .env or PythonAnywhere Environment Variables.")

# Включение/отключение поддержки фотографий
ENABLE_PHOTOS = True  # Установи False, чтобы отключить фотографии

# Состояния для ConversationHandler
QUESTION, ANSWER, ANSWER_PHOTOS = range(3)
EDIT_QUESTION, EDIT_FIELD, EDIT_VALUE = range(3, 6)
TEMPLATE_QUESTION, TEMPLATE_ANSWER, TEMPLATE_ANSWER_PHOTOS = range(6, 9)
EDIT_TEMPLATE_QUESTION, EDIT_TEMPLATE_FIELD, EDIT_TEMPLATE_VALUE = range(9, 12)

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
        logger.warning(f"{file_name} not found, initializing empty {data_type}")
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
        logger.warning("ALLOWED_USERS is empty")
        return []
    try:
        users = [int(user_id) for user_id in users_str.split(",") if user_id.strip()]
        logger.info(f"Loaded allowed users: {users}")
        return users
    except ValueError as e:
        logger.error(f"Error parsing ALLOWED_USERS: {e}")
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
            logger.info("No changes in working directory to commit")
            return
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "Update JSON files via bot"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        logger.info("Successfully synced JSON files to GitHub")
    except subprocess.CalledProcessError as e:
        logger.error(f"Git sync error: {e}")
        try:
            subprocess.run(["git", "rebase", "--abort"], check=True)
            subprocess.run(["git", "pull", "--no-rebase"], check=True)
            subprocess.run(["git", "push", "origin", "main"], check=True)
            logger.info("Resolved git conflict and synced JSON files")
        except subprocess.CalledProcessError as e2:
            logger.error(f"Failed to resolve git conflict: {e2}")
    except Exception as e:
        logger.error(f"Unexpected error during git sync: {e}")

# Проверка доступа
def restrict_access(func):
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        logger.info(f"Checking access for user_id: {user_id}")
        users = load_users()
        logger.info(f"Allowed users: {users}")
        if user_id not in users:
            error_msg = "🚫 Доступ запрещён! Обратитесь к администратору."
            if update.message:
                update.message.reply_text(error_msg, reply_markup=MAIN_MENU)
            elif update.callback_query:
                update.callback_query.message.reply_text(error_msg, reply_markup=MAIN_MENU)
            logger.warning(f"Unauthorized access attempt by user {user_id}")
            return
        return func(update, context, *args, **kwargs)
    return wrapper

# Обработчик ошибок
def error_handler(update: Update, context: CallbackContext):
    logger.error(f"Update {update} caused error: {context.error}", exc_info=True)
    logger.info(f"Current conversation state: {context.user_data.get('conversation_state', 'None')}")
    context.user_data.clear()
    context.user_data['conversation_state'] = 'ERROR'
    if hasattr(context, 'dispatcher') and hasattr(context.dispatcher, 'update_persistence'):
        context.dispatcher.update_persistence()
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
    logger.info(f"User {update.effective_user.id} started the bot")
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
    logger.info(f"User {update.effective_user.id} cancelled the conversation")
    if context.user_data.get('timeout_task'):
        context.user_data['timeout_task'].cancel()
        context.user_data['timeout_task'] = None
        logger.info(f"User {update.effective_user.id} cancelled timeout task")
    context.user_data.clear()
    context.user_data['conversation_state'] = 'CANCELLED'
    context.user_data['conversation_active'] = False
    if hasattr(context, 'dispatcher') and hasattr(context.dispatcher, 'update_persistence'):
        context.dispatcher.update_persistence()
    update.message.reply_text(
        "🚪 Диалог отменён. Выберите действие:",
        reply_markup=MAIN_MENU
    )
    return ConversationHandler.END

# Открытие справочника или шаблонов с пагинацией
@restrict_access
def open_data(update: Update, context: CallbackContext, data_type: str):
    logger.info(f"User {update.effective_user.id} opened {data_type}")
    context.user_data.clear()
    context.user_data['conversation_state'] = f'OPEN_{data_type.upper()}'
    context.user_data['conversation_active'] = False
    context.user_data['data_type'] = data_type
    data = load_data(data_type)
    key = 'questions' if data_type == 'guide' else 'templates'
    if not data[key]:
        update.message.reply_text(
            f"{'📖 Справочник' if data_type == 'guide' else '📋 Шаблоны ответов'} пуст. Добавьте первый пункт! ➕",
            reply_markup=MAIN_MENU
        )
        return ConversationHandler.END
    page = context.user_data.get('page', 0)
    display_guide_page(update, context, data, page, data_type)
    return ConversationHandler.END

@restrict_access
def open_guide(update: Update, context: CallbackContext):
    return open_data(update, context, 'guide')

@restrict_access
def open_templates(update: Update, context: CallbackContext):
    return open_data(update, context, 'template')

# Отображение страницы справочника или шаблонов
def display_guide_page(update: Update, context: CallbackContext, data, page, data_type: str):
    try:
        ITEMS_PER_PAGE = 15
        key = 'questions' if data_type == 'guide' else 'templates'
        total_items = len(data[key])
        total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(0, min(page, total_pages - 1))
        context.user_data['page'] = page
        context.user_data['data'] = data
        context.user_data['data_type'] = data_type

        start_idx = page * ITEMS_PER_PAGE
        end_idx = min(start_idx + ITEMS_PER_PAGE, total_items)
        items = data[key][start_idx:end_idx]

        keyboard = []
        for item in items:
            if not isinstance(item, dict) or "question" not in item or "id" not in item:
                logger.error(f"Invalid {data_type} data: {item}")
                continue
            question_text = item["question"][:100] if len(item["question"]) > 100 else item["question"]
            keyboard.append([InlineKeyboardButton(f"📄 {question_text}", callback_data=f'{data_type}_question_{item["id"]}')])

        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'{data_type}_page_{page-1}'))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f'{data_type}_page_{page+1}'))
        if nav_buttons:
            keyboard.append(nav_buttons)

        reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"{'📖 Справочник' if data_type == 'guide' else '📋 Шаблоны ответов'} (страница {page + 1}/{total_pages}):"

        if update.message:
            update.message.reply_text(text, reply_markup=reply_markup)
        elif update.callback_query:
            update.callback_query.message.edit_text(text, reply_markup=reply_markup)

        logger.info(f"User {update.effective_user.id} viewed {data_type} page {page + 1}")
        context.user_data['conversation_state'] = f'{data_type.upper()}_PAGE'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error in display_guide_page for user {update.effective_user.id}, data_type {data_type}: {str(e)}", exc_info=True)
        if update.message:
            update.message.reply_text(
                f"❌ Произошла ошибка при отображении страницы. Попробуйте снова или свяжитесь с администратором.",
                reply_markup=MAIN_MENU
            )
        elif update.callback_query:
            update.callback_query.message.reply_text(
                f"❌ Произошла ошибка при отображении страницы. Попробуйте снова или свяжитесь с администратором.",
                reply_markup=MAIN_MENU
            )
        return ConversationHandler.END

# Показ ответа
@restrict_access
def show_answer(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data_type, _, question_id = query.data.split('_')
    question_id = int(question_id)
    logger.info(f"User {update.effective_user.id} requested answer for {data_type} ID {question_id}")
    data = load_data(data_type)
    key = 'questions' if data_type == 'guide' else 'templates'
    item = next((q for q in data[key] if q["id"] == question_id), None)
    if item:
        response = f"📄 Вопрос: {item['question']}\nОтвет: {item['answer']}"
        photo_ids = item.get('photos', []) or ([item['photo']] if item.get('photo') else [])
        if ENABLE_PHOTOS and photo_ids:
            if len(photo_ids) == 1:
                query.message.reply_photo(
                    photo=photo_ids[0],
                    caption=response,
                    reply_markup=MAIN_MENU
                )
            else:
                media = [InputMediaPhoto(media=photo_id, caption=response if i == 0 else None) for i, photo_id in enumerate(photo_ids)]
                query.message.reply_media_group(media=media)
                query.message.reply_text("Выберите действие:", reply_markup=MAIN_MENU)
        else:
            query.message.reply_text(response, reply_markup=MAIN_MENU)
    else:
        query.message.reply_text(f"❌ {'Вопрос' if data_type == 'guide' else 'Шаблон'} не найден!", reply_markup=MAIN_MENU)
    context.user_data.clear()
    context.user_data['conversation_state'] = f'SHOW_{data_type.upper()}_ANSWER'
    context.user_data['conversation_active'] = False
    return ConversationHandler.END

# Обработка пагинации
@restrict_access
def handle_pagination(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data_type, _, page = query.data.split('_')
    page = int(page)
    data = context.user_data.get('data', load_data(data_type))
    display_guide_page(update, context, data, page, data_type)
    context.user_data['conversation_state'] = f'{data_type.upper()}_PAGINATION'
    context.user_data['conversation_active'] = False
    return ConversationHandler.END

# Поиск по ключевым словам
@restrict_access
def perform_search(update: Update, context: CallbackContext):
    try:
        logger.info(f"User {update.effective_user.id} entered perform_search with text: '{update.message.text}'")
        if not update.message or not update.message.text:
            logger.error(f"User {update.effective_user.id} sent empty or invalid message for search")
            update.message.reply_text(
                "❌ Пожалуйста, введите ключевое слово для поиска!",
                reply_markup=MAIN_MENU
            )
            return ConversationHandler.END

        keyword = update.message.text.lower().strip()
        logger.info(f"User {update.effective_user.id} searched for '{keyword}'")

        guide = load_guide()
        if not isinstance(guide, dict) or "questions" not in guide or not isinstance(guide["questions"], list):
            logger.error("Invalid guide.json structure")
            update.message.reply_text(
                "❌ Ошибка: Неверная структура файла guide.json. Свяжитесь с администратором.",
                reply_markup=MAIN_MENU
            )
            return ConversationHandler.END

        results = [
            q for q in guide["questions"]
            if isinstance(q, dict) and
            "question" in q and isinstance(q["question"], str) and
            "answer" in q and isinstance(q["answer"], str) and
            (keyword in q["question"].lower() or keyword in q["answer"].lower())
        ]

        if not results:
            logger.info(f"No results found for keyword '{keyword}'")
            update.message.reply_text(
                "🔍 Ничего не найдено. Попробуйте другое ключевое слово!",
                reply_markup=MAIN_MENU
            )
            return ConversationHandler.END

        context.user_data['data'] = {"questions": results}
        context.user_data['page'] = 0
        context.user_data['data_type'] = 'guide'
        context.user_data['conversation_state'] = 'SEARCH'
        context.user_data['conversation_active'] = False
        display_guide_page(update, context, {"questions": results}, 0, 'guide')
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error in perform_search for user {update.effective_user.id}: {str(e)}", exc_info=True)
        context.user_data.clear()
        context.user_data['conversation_state'] = 'ERROR'
        context.user_data['conversation_active'] = False
        update.message.reply_text(
            "❌ Произошла ошибка при поиске. Попробуйте снова или свяжитесь с администратором.",
            reply_markup=MAIN_MENU
        )
        return ConversationHandler.END

# Добавление пункта
@restrict_access
def add_item(update: Update, context: CallbackContext, data_type: str):
    logger.info(f"User {update.effective_user.id} started adding a new {data_type}")
    context.user_data.clear()
    context.user_data['photos'] = []
    context.user_data['media_group_id'] = None
    context.user_data['last_photo_time'] = None
    context.user_data['point_saved'] = False
    context.user_data['loading_message_id'] = None
    context.user_data['timeout_task'] = None
    context.user_data['conversation_state'] = f'ADD_{data_type.upper()}'
    context.user_data['conversation_active'] = True
    context.user_data['data_type'] = data_type
    try:
        update.message.reply_text(
            f"➕ Введите вопрос (например, 'Ошибка входа в систему'):\n(Напишите /cancel для отмены)",
            reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
        )
        logger.info(f"User {update.effective_user.id} successfully triggered add_{data_type}")
    except Exception as e:
        logger.error(f"Error in add_{data_type} for user {update.effective_user.id}: {e}", exc_info=True)
        context.user_data.clear()
        context.user_data['conversation_state'] = 'ERROR'
        context.user_data['conversation_active'] = False
        update.message.reply_text(
            f"❌ Ошибка при добавлении {'пункта' if data_type == 'guide' else 'шаблона'}. Попробуйте снова.",
            reply_markup=MAIN_MENU
        )
        return ConversationHandler.END
    return QUESTION if data_type == 'guide' else TEMPLATE_QUESTION

@restrict_access
def add_point(update: Update, context: CallbackContext):
    return add_item(update, context, 'guide')

@restrict_access
def add_template(update: Update, context: CallbackContext):
    return add_item(update, context, 'template')

@restrict_access
def receive_question(update: Update, context: CallbackContext):
    if not context.user_data.get('conversation_active', False):
        logger.warning(f"User {update.effective_user.id} attempted to provide question in inactive conversation")
        update.message.reply_text(
            f"❌ Пожалуйста, начните добавление {'пункта' if context.user_data.get('data_type') == 'guide' else 'шаблона'} заново (нажмите '{'➕ Добавить пункт' if context.user_data.get('data_type') == 'guide' else '📋 Шаблоны ответов'}').",
            reply_markup=MAIN_MENU
        )
        context.user_data.clear()
        context.user_data['conversation_state'] = 'INVALID_QUESTION'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    data_type = context.user_data.get('data_type', 'guide')
    logger.info(f"User {update.effective_user.id} entered {data_type} question: {update.message.text}")
    context.user_data['new_question'] = update.message.text
    context.user_data['conversation_state'] = f'RECEIVE_{data_type.upper()}_QUESTION'
    prompt = "Введите подсказку для решения"
    if ENABLE_PHOTOS:
        prompt += " (или отправьте фото/альбом с подписью)"
    prompt += ":\n(Напишите /cancel для отмены)"
    update.message.reply_text(
        prompt,
        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
    )
    return ANSWER if data_type == 'guide' else TEMPLATE_ANSWER

@restrict_access
def receive_answer(update: Update, context: CallbackContext):
    if not context.user_data.get('conversation_active', False) or 'new_question' not in context.user_data:
        logger.warning(f"User {update.effective_user.id} attempted to provide answer without active conversation or question")
        update.message.reply_text(
            f"❌ Пожалуйста, начните добавление {'пункта' if context.user_data.get('data_type') == 'guide' else 'шаблона'} заново (нажмите '{'➕ Добавить пункт' if context.user_data.get('data_type') == 'guide' else '📋 Шаблоны ответов'}').",
            reply_markup=MAIN_MENU
        )
        context.user_data.clear()
        context.user_data['conversation_state'] = 'INVALID_ANSWER'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    data_type = context.user_data.get('data_type', 'guide')
    context.user_data['answer'] = update.message.caption if update.message.photo else update.message.text if update.message.text else ""
    context.user_data['conversation_state'] = f'RECEIVE_{data_type.upper()}_ANSWER'
    if ENABLE_PHOTOS and update.message.photo:
        if update.message.media_group_id:
            context.user_data['media_group_id'] = update.message.media_group_id
            context.user_data['photos'].append(update.message.photo[-1].file_id)
            context.user_data['last_photo_time'] = update.message.date
            logger.info(f"User {update.effective_user.id} added photo to {data_type} media group {update.message.media_group_id}: {update.message.photo[-1].file_id}")
            if len(context.user_data['photos']) == 1:
                loading_message = update.message.reply_text("⏳ Загрузка...")
                context.user_data['loading_message_id'] = loading_message.message_id
                if not context.user_data.get('timeout_task'):
                    context.user_data['timeout_task'] = context.job_queue.run_once(
                        check_album_timeout, 2, context=(update, context)
                    )
            return ANSWER_PHOTOS if data_type == 'guide' else TEMPLATE_ANSWER_PHOTOS
        else:
            context.user_data['photos'] = [update.message.photo[-1].file_id]
            logger.info(f"User {update.effective_user.id} added single photo to {data_type}: {context.user_data['photos']}")
    save_new_point(update, context, send_message=True)
    logger.info(f"User {update.effective_user.id} ending add_{data_type}_conv in receive_answer")
    context.user_data.clear()
    context.user_data['conversation_state'] = f'{data_type.upper()}_POINT_SAVED'
    context.user_data['conversation_active'] = False
    return ConversationHandler.END

def check_album_timeout(context: CallbackContext):
    update, context = context.job.context
    if context.user_data.get('last_photo_time') == update.message.date and not context.user_data.get('point_saved'):
        data_type = context.user_data.get('data_type', 'guide')
        logger.info(f"User {update.effective_user.id} finished album for {data_type} media group {context.user_data.get('media_group_id')}")
        if context.user_data.get('loading_message_id'):
            try:
                context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=context.user_data['loading_message_id']
                )
                logger.info(f"User {update.effective_user.id} deleted loading message")
            except Exception as e:
                logger.error(f"Failed to delete loading message: {e}")
        save_new_point(update, context, send_message=True)
        context.user_data['point_saved'] = True
        context.user_data['timeout_task'] = None
        logger.info(f"User {update.effective_user.id} ending add_{data_type}_conv in check_album_timeout")
        context.user_data.clear()
        context.user_data['conversation_state'] = f'{data_type.upper()}_ALBUM_SAVED'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    return None

def save_new_point(update: Update, context: CallbackContext, send_message: bool = False):
    if context.user_data.get('point_saved'):
        logger.info(f"User {update.effective_user.id} skipped saving point as it was already saved")
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
    if ENABLE_PHOTOS and context.user_data['photos']:
        new_point['photos'] = context.user_data['photos']
        logger.info(f"User {update.effective_user.id} added photos to {data_type}: {new_point['photos']}")
    data[key].append(new_point)
    save_data(data_type, data)
    logger.info(f"User {update.effective_user.id} added new {data_type} point: {new_point['question']}")
    if send_message:
        update.message.reply_text(
            f"➕ {'Пункт' if data_type == 'guide' else 'Шаблон'} добавлен!\nВопрос: {new_point['question']}",
            reply_markup=MAIN_MENU
        )
    context.user_data['point_saved'] = True

@restrict_access
def receive_answer_photos(update: Update, context: CallbackContext):
    if not context.user_data.get('conversation_active', False) or 'new_question' not in context.user_data:
        logger.warning(f"User {update.effective_user.id} attempted to provide photos without active conversation or question")
        update.message.reply_text(
            f"❌ Пожалуйста, начните добавление {'пункта' if context.user_data.get('data_type') == 'guide' else 'шаблона'} заново (нажмите '{'➕ Добавить пункт' if context.user_data.get('data_type') == 'guide' else '📋 Шаблоны ответов'}').",
            reply_markup=MAIN_MENU
        )
        context.user_data.clear()
        context.user_data['conversation_state'] = 'INVALID_PHOTOS'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    data_type = context.user_data.get('data_type', 'guide')
    if update.message.media_group_id == context.user_data.get('media_group_id'):
        context.user_data['photos'].append(update.message.photo[-1].file_id)
        context.user_data['last_photo_time'] = update.message.date
        logger.info(f"User {update.effective_user.id} added photo to {data_type} media group: {update.message.photo[-1].file_id}")
        if not context.user_data.get('timeout_task'):
            context.user_data['timeout_task'] = context.job_queue.run_once(
                check_album_timeout, 2, context=(update, context)
            )
        return ANSWER_PHOTOS if data_type == 'guide' else TEMPLATE_ANSWER_PHOTOS
    if not context.user_data.get('point_saved') and context.user_data.get('photos'):
        logger.info(f"User {update.effective_user.id} finished album for {data_type} media group {context.user_data.get('media_group_id')} due to new message")
        if context.user_data.get('timeout_task'):
            context.user_data['timeout_task'].cancel()
            context.user_data['timeout_task'] = None
            logger.info(f"User {update.effective_user.id} cancelled timeout task in receive_answer_photos")
        if context.user_data.get('loading_message_id'):
            try:
                context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=context.user_data['loading_message_id']
                )
                logger.info(f"User {update.effective_user.id} deleted loading message")
            except Exception as e:
                logger.error(f"Failed to delete loading message: {e}")
        save_new_point(update, context, send_message=True)
        context.user_data['point_saved'] = True
        logger.info(f"User {update.effective_user.id} ending add_{data_type}_conv in receive_answer_photos")
        context.user_data.clear()
        context.user_data['conversation_state'] = f'{data_type.upper()}_PHOTOS_SAVED'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    return ANSWER_PHOTOS if data_type == 'guide' else TEMPLATE_ANSWER_PHOTOS

@restrict_access
def edit_item(update: Update, context: CallbackContext, data_type: str):
    logger.info(f"User {update.effective_user.id} started editing a {data_type}")
    context.user_data.clear()
    context.user_data['conversation_state'] = f'EDIT_{data_type.upper()}'
    context.user_data['conversation_active'] = True
    context.user_data['data_type'] = data_type
    data = load_data(data_type)
    key = 'questions' if data_type == 'guide' else 'templates'
    if not data[key]:
        update.message.reply_text(
            f"{'📖 Справочник' if data_type == 'guide' else '📋 Шаблоны ответов'} пуст. Нечего редактировать! ➕",
            reply_markup=MAIN_MENU
        )
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    context.user_data['data'] = data
    context.user_data['page'] = 0
    display_edit_page(update, context, data, 0, data_type)
    return EDIT_QUESTION if data_type == 'guide' else EDIT_TEMPLATE_QUESTION

@restrict_access
def edit_point(update: Update, context: CallbackContext):
    return edit_item(update, context, 'guide')

@restrict_access
def edit_template(update: Update, context: CallbackContext):
    return edit_item(update, context, 'template')

# Отображение страницы для редактирования
def display_edit_page(update: Update, context: CallbackContext, data, page, data_type: str):
    ITEMS_PER_PAGE = 15
    key = 'questions' if data_type == 'guide' else 'templates'
    total_items = len(data[key])
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    context.user_data['page'] = page
    context.user_data['data'] = data
    context.user_data['data_type'] = data_type

    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, total_items)
    items = data[key][start_idx:end_idx]

    keyboard = [[InlineKeyboardButton(f"📄 {q['question']}", callback_data=f'edit_{data_type}_question_{q["id"]}')] for q in items]
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'edit_{data_type}_page_{page-1}'))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f'edit_{data_type}_page_{page+1}'))
    nav_buttons.append(InlineKeyboardButton("🚪 Отмена", callback_data=f'cancel_{data_type}_edit'))
    keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"✏️ Выберите {'вопрос' if data_type == 'guide' else 'шаблон'} для редактирования (страница {page + 1}/{total_pages}):"
    if update.message:
        update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        update.callback_query.message.edit_text(text, reply_markup=reply_markup)
    logger.info(f"User {update.effective_user.id} viewed {data_type} edit page {page + 1}")
    context.user_data['conversation_state'] = f'EDIT_{data_type.upper()}_PAGE'
    return EDIT_QUESTION if data_type == 'guide' else EDIT_TEMPLATE_QUESTION

@restrict_access
def handle_edit_pagination(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data_type = query.data.split('_')[1] if query.data.startswith('edit_') else query.data.split('_')[0]
    if query.data == f'cancel_{data_type}_edit':
        context.user_data.clear()
        context.user_data['conversation_state'] = f'CANCEL_{data_type.upper()}_EDIT'
        context.user_data['conversation_active'] = False
        query.message.reply_text(f"🚪 Редактирование {'пункта' if data_type == 'guide' else 'шаблона'} отменено.", reply_markup=MAIN_MENU)
        return ConversationHandler.END
    page = int(query.data.split('_')[3])
    data = context.user_data.get('data', load_data(data_type))
    display_edit_page(update, context, data, page, data_type)
    context.user_data['conversation_state'] = f'EDIT_{data_type.upper()}_PAGINATION'
    return EDIT_QUESTION if data_type == 'guide' else EDIT_TEMPLATE_QUESTION

@restrict_access
def select_edit_question(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data_type = query.data.split('_')[1]
    context.user_data['edit_question_id'] = int(query.data.split('_')[3])
    logger.info(f"User {update.effective_user.id} selected {data_type} ID {context.user_data['edit_question_id']} for editing")
    context.user_data['conversation_state'] = f'SELECT_EDIT_{data_type.upper()}_QUESTION'
    keyboard = [
        [InlineKeyboardButton("Изменить вопрос", callback_data=f'edit_{data_type}_field_question')],
        [InlineKeyboardButton("Изменить ответ", callback_data=f'edit_{data_type}_field_answer')],
        [InlineKeyboardButton("Удалить пункт", callback_data=f'edit_{data_type}_field_delete')]
    ]
    if ENABLE_PHOTOS:
        keyboard.insert(2, [InlineKeyboardButton("Добавить/изменить фото", callback_data=f'edit_{data_type}_field_photo')])
    keyboard.append([InlineKeyboardButton("🚪 Отмена", callback_data=f'cancel_{data_type}_edit')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.message.reply_text(f"✏️ Что хотите изменить в {'вопросе' if data_type == 'guide' else 'шаблоне'}?", reply_markup=reply_markup)
    return EDIT_FIELD if data_type == 'guide' else EDIT_TEMPLATE_FIELD

@restrict_access
def receive_edit_field(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data_type = query.data.split('_')[1]
    if query.data == f'cancel_{data_type}_edit':
        context.user_data.clear()
        context.user_data['conversation_state'] = f'CANCEL_{data_type.upper()}_EDIT'
        context.user_data['conversation_active'] = False
        query.message.reply_text(f"🚪 Редактирование {'пункта' if data_type == 'guide' else 'шаблона'} отменено.", reply_markup=MAIN_MENU)
        return ConversationHandler.END
    context.user_data['edit_field'] = query.data
    logger.info(f"User {update.effective_user.id} chose to edit {data_type} field: {query.data}")
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
        query.message.reply_text(f"🗑️ {'Пункт' if data_type == 'guide' else 'Шаблон'} удалён!", reply_markup=MAIN_MENU)
        return ConversationHandler.END
    field = "вопрос" if query.data == f'edit_{data_type}_field_question' else "ответ" if query.data == f'edit_{data_type}_field_answer' else "фото/альбом"
    prompt = f"✏️ Введите новый {field}:\n(Напишите /cancel для отмены)"
    query.message.reply_text(
        prompt,
        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
    )
    return EDIT_VALUE if data_type == 'guide' else EDIT_TEMPLATE_VALUE

@restrict_access
def receive_edit_value(update: Update, context: CallbackContext):
    if not context.user_data.get('conversation_active', False):
        logger.warning(f"User {update.effective_user.id} attempted to provide edit value in inactive conversation")
        update.message.reply_text(
            f"❌ Пожалуйста, начните редактирование {'пункта' if context.user_data.get('data_type') == 'guide' else 'шаблона'} заново (нажмите '{'✏️ Редактировать пункт' if context.user_data.get('data_type') == 'guide' else '📋 Шаблоны ответов'}').",
            reply_markup=MAIN_MENU
        )
        context.user_data.clear()
        context.user_data['conversation_state'] = 'INVALID_EDIT_VALUE'
        context.user_data['conversation_active'] = False
        return ConversationHandler.END
    data_type = context.user_data.get('data_type', 'guide')
    data = load_data(data_type)
    key = 'questions' if data_type == 'guide' else 'templates'
    question_id = context.user_data['edit_question_id']
    field = context.user_data['edit_field']
    for q in data[key]:
        if q["id"] == question_id:
            if field == f'edit_{data_type}_field_question':
                q['question'] = update.message.text
            elif field == f'edit_{data_type}_field_answer':
                q['answer'] = update.message.text
            elif field == f'edit_{data_type}_field_photo' and ENABLE_PHOTOS:
                if update.message.photo:
                    q['photos'] = [update.message.photo[-1].file_id]
                    logger.info(f"User {update.effective_user.id} updated photo(s) for {data_type} ID {question_id}: {q['photos']}")
                    q.pop('photo', None)
                else:
                    update.message.reply_text(
                        f"❌ Пожалуйста, отправьте фото или альбом!\n(Напишите /cancel для отмены)",
                        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
                    )
                    return EDIT_VALUE if data_type == 'guide' else EDIT_TEMPLATE_VALUE
            break
    save_data(data_type, data)
    logger.info(f"User {update.effective_user.id} updated {field} for {data_type} ID {question_id}")
    context.user_data.clear()
    context.user_data['conversation_state'] = f'EDIT_{data_type.upper()}_VALUE'
    context.user_data['conversation_active'] = False
    update.message.reply_text(
        f"✏️ {field.replace(f'edit_{data_type}_field_', '').capitalize()} обновлён!",
        reply_markup=MAIN_MENU
    )
    return ConversationHandler.END

# Обработчик неподдерживаемых сообщений
@restrict_access
def handle_invalid_input(update: Update, context: CallbackContext):
    logger.warning(f"User {update.effective_user.id} sent invalid input in conversation state")
    data_type = context.user_data.get('data_type', 'guide')
    context.user_data.clear()
    context.user_data['conversation_state'] = 'INVALID_INPUT'
    context.user_data['conversation_active'] = False
    update.message.reply_text(
        f"❌ Пожалуйста, отправьте текст или фото/альбом (для ответа/фото)!\n(Напишите /cancel для отмены)",
        reply_markup=MAIN_MENU
    )
    return ConversationHandler.END

# Обработчик для отладки текстовых сообщений
@restrict_access
def debug_text(update: Update, context: CallbackContext):
    logger.info(f"User {update.effective_user.id} sent text: '{update.message.text}'")
    current_state = context.user_data.get('conversation_state', 'NONE')
    logger.info(f"Current conversation state: {current_state}")
    if context.user_data.get('conversation_active', False):
        logger.info(f"User {update.effective_user.id} is in active conversation state {current_state}, skipping perform_search")
        return
    menu_pattern = r'^(📖 Справочник|📋 Шаблоны ответов|➕ Добавить пункт|✏️ Редактировать пункт)$'
    if re.match(menu_pattern, update.message.text):
        logger.info(f"User {update.effective_user.id} sent menu command: '{update.message.text}', skipping perform_search")
        return
    context.user_data.clear()
    context.user_data['conversation_state'] = 'SEARCH'
    context.user_data['conversation_active'] = False
    perform_search(update, context)

# Запуск бота
def main():
    updater = Updater(os.getenv("BOT_TOKEN"), use_context=True)
    dp = updater.dispatcher
    dp.add_error_handler(error_handler)
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("cancel", cancel))  # Глобальный /cancel
    dp.add_handler(MessageHandler(Filters.regex(r'^📖 Справочник$'), open_guide))
    dp.add_handler(MessageHandler(Filters.regex(r'^📋 Шаблоны ответов$'), open_templates))
    add_conv = ConversationHandler(
        entry_points=[
            MessageHandler(Filters.regex(r'^➕ Добавить пункт$'), add_point),
            MessageHandler(Filters.regex(r'^📋 Шаблоны ответов$'), add_template)
        ],
        states={
            QUESTION: [
                MessageHandler(
                    Filters.text & ~Filters.command & ~Filters.regex(r'^(📖 Справочник|📋 Шаблоны ответов|➕ Добавить пункт|✏️ Редактировать пункт)$'),
                    receive_question
                ),
            ],
            ANSWER: [
                MessageHandler(
                    Filters.text & ~Filters.command & ~Filters.regex(r'^(📖 Справочник|📋 Шаблоны ответов|➕ Добавить пункт|✏️ Редактировать пункт)$'),
                    receive_answer
                ),
                MessageHandler(Filters.photo, receive_answer) if ENABLE_PHOTOS else None,
                MessageHandler(~(Filters.text | Filters.photo) & ~Filters.command, handle_invalid_input)
            ],
            ANSWER_PHOTOS: [
                MessageHandler(Filters.photo, receive_answer_photos) if ENABLE_PHOTOS else None,
                MessageHandler(
                    Filters.text & ~Filters.command & ~Filters.regex(r'^(📖 Справочник|📋 Шаблоны ответов|➕ Добавить пункт|✏️ Редактировать пункт)$'),
                    receive_answer
                ),
                MessageHandler(~(Filters.text | Filters.photo) & ~Filters.command, handle_invalid_input)
            ],
            TEMPLATE_QUESTION: [
                MessageHandler(
                    Filters.text & ~Filters.command & ~Filters.regex(r'^(📖 Справочник|📋 Шаблоны ответов|➕ Добавить пункт|✏️ Редактировать пункт)$'),
                    receive_question
                ),
            ],
            TEMPLATE_ANSWER: [
                MessageHandler(
                    Filters.text & ~Filters.command & ~Filters.regex(r'^(📖 Справочник|📋 Шаблоны ответов|➕ Добавить пункт|✏️ Редактировать пункт)$'),
                    receive_answer
                ),
                MessageHandler(Filters.photo, receive_answer) if ENABLE_PHOTOS else None,
                MessageHandler(~(Filters.text | Filters.photo) & ~Filters.command, handle_invalid_input)
            ],
            TEMPLATE_ANSWER_PHOTOS: [
                MessageHandler(Filters.photo, receive_answer_photos) if ENABLE_PHOTOS else None,
                MessageHandler(
                    Filters.text & ~Filters.command & ~Filters.regex(r'^(📖 Справочник|📋 Шаблоны ответов|➕ Добавить пункт|✏️ Редактировать пункт)$'),
                    receive_answer
                ),
                MessageHandler(~(Filters.text | Filters.photo) & ~Filters.command, handle_invalid_input)
            ]
        },
        fallbacks=[],
        per_user=True,
        per_chat=True,
        allow_reentry=False
    )
    dp.add_handler(add_conv)
    edit_conv = ConversationHandler(
        entry_points=[
            MessageHandler(Filters.regex(r'^✏️ Редактировать пункт$'), edit_point),
            MessageHandler(Filters.regex(r'^📋 Шаблоны ответов$'), edit_template)
        ],
        states={
            EDIT_QUESTION: [
                CallbackQueryHandler(select_edit_question, pattern='^edit_guide_question_.*$'),
                CallbackQueryHandler(handle_edit_pagination, pattern='^(edit_guide_page_.*|cancel_guide_edit)$')
            ],
            EDIT_FIELD: [
                CallbackQueryHandler(receive_edit_field, pattern='^(edit_guide_field_.*|cancel_guide_edit)$')
            ],
            EDIT_VALUE: [
                MessageHandler(
                    Filters.text & ~Filters.command & ~Filters.regex(r'^(📖 Справочник|📋 Шаблоны ответов|➕ Добавить пункт|✏️ Редактировать пункт)$'),
                    receive_edit_value
                ),
                MessageHandler(Filters.photo, receive_edit_value) if ENABLE_PHOTOS else None,
                MessageHandler(~(Filters.text | Filters.photo) & ~Filters.command, handle_invalid_input)
            ],
            EDIT_TEMPLATE_QUESTION: [
                CallbackQueryHandler(select_edit_question, pattern='^edit_template_question_.*$'),
                CallbackQueryHandler(handle_edit_pagination, pattern='^(edit_template_page_.*|cancel_template_edit)$')
            ],
            EDIT_TEMPLATE_FIELD: [
                CallbackQueryHandler(receive_edit_field, pattern='^(edit_template_field_.*|cancel_template_edit)$')
            ],
            EDIT_TEMPLATE_VALUE: [
                MessageHandler(
                    Filters.text & ~Filters.command & ~Filters.regex(r'^(📖 Справочник|📋 Шаблоны ответов|➕ Добавить пункт|✏️ Редактировать пункт)$'),
                    receive_edit_value
                ),
                MessageHandler(Filters.photo, receive_edit_value) if ENABLE_PHOTOS else None,
                MessageHandler(~(Filters.text | Filters.photo) & ~Filters.command, handle_invalid_input)
            ]
        },
        fallbacks=[],
        per_user=True,
        per_chat=True,
        per_message=False,
        allow_reentry=False
    )
    dp.add_handler(edit_conv)
    dp.add_handler(CallbackQueryHandler(handle_pagination, pattern='^(guide|template)_page_.*$'))
    dp.add_handler(CallbackQueryHandler(show_answer, pattern='^(guide|template)_question_.*$'))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, debug_text))

    logger.info("Bot is running...")
    updater.start_polling(allowed_updates=Update.ALL_TYPES)
    updater.idle()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, shutting down...")
    except Exception as e:
        logger.error(f"Error running bot: {e}", exc_info=True)