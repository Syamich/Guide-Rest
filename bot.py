import json
import os
import subprocess
import asyncio
import logging
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
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

# Постоянное клавиатурное меню
MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📖 Справочник")],
        [KeyboardButton("➕ Добавить пункт"), KeyboardButton("✏️ Редактировать пункт")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

# Чтение JSON
def load_guide():
    try:
        with open('guide.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("guide.json not found, initializing empty guide")
        return {"questions": []}

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
def save_guide(data):
    with open('guide.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    sync_with_github()

def sync_with_github():
    try:
        # Проверяем статус
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not result.stdout:
            logger.info("No changes in working directory to commit")
            return
        # Сохраняем все изменения
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "Update guide.json via bot"], check=True)
        # Синхронизируем
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        logger.info("Successfully synced guide.json to GitHub")
    except subprocess.CalledProcessError as e:
        logger.error(f"Git sync error: {e}")
        try:
            # Пробуем разрешить конфликт
            subprocess.run(["git", "rebase", "--abort"], check=True)
            subprocess.run(["git", "pull", "--no-rebase"], check=True)
            subprocess.run(["git", "push", "origin", "main"], check=True)
            logger.info("Resolved git conflict and synced guide.json")
        except subprocess.CalledProcessError as e2:
            logger.error(f"Failed to resolve git conflict: {e2}")
    except Exception as e:
        logger.error(f"Unexpected error during git sync: {e}")

# Проверка доступа
def restrict_access(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        logger.info(f"Checking access for user_id: {user_id}")
        users = load_users()
        logger.info(f"Allowed users: {users}")
        if user_id not in users:
            error_msg = "🚫 Доступ запрещён! Обратитесь к администратору."
            if update.message:
                await update.message.reply_text(error_msg, reply_markup=MAIN_MENU)
            elif update.callback_query:
                await update.callback_query.message.reply_text(error_msg, reply_markup=MAIN_MENU)
            logger.warning(f"Unauthorized access attempt by user {user_id}")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")
    if update.message:
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте снова или свяжитесь с администратором.", reply_markup=MAIN_MENU)
    elif update.callback_query:
        await update.callback_query.message.reply_text("❌ Произошла ошибка. Попробуйте снова или свяжитесь с администратором.", reply_markup=MAIN_MENU)
    # Очищаем user_data при ошибке
    context.user_data.clear()

# Команда /start
@restrict_access
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"User {update.effective_user.id} started the bot")
    context.user_data.clear()  # Очищаем user_data
    await update.message.reply_text(
        "Добро пожаловать в справочник техподдержки РЭСТ! 📋\nВыберите действие:",
        reply_markup=MAIN_MENU
    )

# Команда /cancel
@restrict_access
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"User {update.effective_user.id} cancelled the conversation")
    context.user_data.clear()  # Очищаем user_data
    await update.message.reply_text(
        "🚪 Диалог отменён. Выберите действие:",
        reply_markup=MAIN_MENU
    )
    return ConversationHandler.END

# Открытие справочника с пагинацией
@restrict_access
async def open_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"User {update.effective_user.id} opened the guide")
    context.user_data.clear()  # Очищаем user_data
    guide = load_guide()
    if not guide["questions"]:
        await update.message.reply_text(
            "📖 Справочник пуст. Добавьте первый пункт! ➕",
            reply_markup=MAIN_MENU
        )
        return
    page = context.user_data.get('page', 0)
    await display_guide_page(update, context, guide, page)

# Отображение страницы справочника
async def display_guide_page(update: Update, context: ContextTypes.DEFAULT_TYPE, guide, page):
    ITEMS_PER_PAGE = 15
    total_items = len(guide["questions"])
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))  # Ограничиваем страницу
    context.user_data['page'] = page
    context.user_data['guide'] = guide

    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, total_items)
    questions = guide["questions"][start_idx:end_idx]

    keyboard = [[InlineKeyboardButton(f"📄 {q['question']}", callback_data=f'question_{q["id"]}')] for q in questions]
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'page_{page-1}'))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f'page_{page+1}'))
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"📖 Справочник (страница {page + 1}/{total_pages}):"
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
    logger.info(f"User {update.effective_user.id} viewed guide page {page + 1}")

# Показ ответа
@restrict_access
async def show_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    question_id = int(query.data.split('_')[1])
    logger.info(f"User {update.effective_user.id} requested answer for question ID {question_id}")
    guide = load_guide()
    question = next((q for q in guide["questions"] if q["id"] == question_id), None)
    if question:
        response = f"📄 Вопрос: {question['question']}\nОтвет: {question['answer']}"
        # Поддержка обратной совместимости: проверяем 'photo' и 'photos'
        photo_ids = question.get('photos', []) or ([question['photo']] if question.get('photo') else [])
        if ENABLE_PHOTOS and photo_ids:
            if len(photo_ids) == 1:
                # Одна фотография
                await query.message.reply_photo(
                    photo=photo_ids[0],
                    caption=response,
                    reply_markup=MAIN_MENU
                )
            else:
                # Несколько фотографий как альбом
                media = [InputMediaPhoto(media=photo_id, caption=response if i == 0 else None) for i, photo_id in enumerate(photo_ids)]
                await query.message.reply_media_group(media=media)
                # Отправляем главное меню отдельным сообщением
                await query.message.reply_text("Выберите действие:", reply_markup=MAIN_MENU)
        else:
            await query.message.reply_text(response, reply_markup=MAIN_MENU)
    else:
        await query.message.reply_text("❌ Вопрос не найден!", reply_markup=MAIN_MENU)
    context.user_data.clear()  # Очищаем user_data

# Обработка пагинации
@restrict_access
async def handle_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split('_')[1])
    guide = context.user_data.get('guide', load_guide())
    await display_guide_page(update, context, guide, page)

# Поиск по ключевым словам
@restrict_access
async def perform_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.lower()
    logger.info(f"User {update.effective_user.id} searched for '{keyword}'")
    guide = load_guide()
    results = [q for q in guide["questions"] if keyword in q["question"].lower() or keyword in q["answer"].lower()]
    if not results:
        await update.message.reply_text(
            "🔍 Ничего не найдено. Попробуйте другое ключевое слово!",
            reply_markup=MAIN_MENU
        )
        return
    context.user_data['guide'] = {"questions": results}
    context.user_data['page'] = 0
    await display_guide_page(update, context, {"questions": results}, 0)

# Добавление пункта
@restrict_access
async def add_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"User {update.effective_user.id} started adding a new point")
    context.user_data.clear()  # Очищаем user_data
    context.user_data['photos'] = []  # Инициализируем список для фотографий
    context.user_data['media_group_id'] = None
    context.user_data['last_photo_time'] = None
    context.user_data['point_saved'] = False  # Флаг для предотвращения дублирования
    context.user_data['loading_message_id'] = None
    context.user_data['timeout_task'] = None  # Для хранения задачи таймера
    await update.message.reply_text(
        "➕ Введите вопрос (например, 'Ошибка входа в систему'):\n(Напишите /cancel для отмены)",
        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
    )
    return QUESTION

@restrict_access
async def receive_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_question'] = update.message.text
    logger.info(f"User {update.effective_user.id} entered question: {update.message.text}")
    prompt = "Введите подсказку для решения"
    if ENABLE_PHOTOS:
        prompt += " (или отправьте фото/альбом с подписью)"
    prompt += ":\n(Напишите /cancel для отмены)"
    await update.message.reply_text(
        prompt,
        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
    )
    return ANSWER

@restrict_access
async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сохраняем текст ответа
    context.user_data['answer'] = update.message.caption if update.message.photo else update.message.text if update.message.text else ""
    if ENABLE_PHOTOS and update.message.photo:
        # Проверяем, является ли сообщение частью альбома
        if update.message.media_group_id:
            context.user_data['media_group_id'] = update.message.media_group_id
            context.user_data['photos'].append(update.message.photo[-1].file_id)
            context.user_data['last_photo_time'] = update.message.date
            logger.info(f"User {update.effective_user.id} added photo to media group {update.message.media_group_id}: {update.message.photo[-1].file_id}")
            # Отправляем сообщение "Загрузка" при первой фотографии
            if len(context.user_data['photos']) == 1:
                loading_message = await update.message.reply_text("⏳ Загрузка...")
                context.user_data['loading_message_id'] = loading_message.message_id
                # Запускаем таймер только если он ещё не запущен
                if not context.user_data.get('timeout_task'):
                    context.user_data['timeout_task'] = asyncio.create_task(check_album_timeout(update, context))
            return ANSWER_PHOTOS
        else:
            # Одиночная фотография
            context.user_data['photos'] = [update.message.photo[-1].file_id]
            logger.info(f"User {update.effective_user.id} added single photo: {context.user_data['photos']}")
    # Сохраняем пункт, если нет альбома или это текстовый ответ
    await save_new_point(update, context, send_message=True)
    context.user_data.clear()  # Очищаем user_data
    return ConversationHandler.END

async def check_album_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ждём 2 секунды, чтобы собрать все фотографии альбома
    await asyncio.sleep(2)
    if context.user_data.get('last_photo_time') == update.message.date and not context.user_data.get('point_saved'):
        logger.info(f"User {update.effective_user.id} finished album for media group {context.user_data.get('media_group_id')}")
        # Удаляем сообщение "Загрузка"
        if context.user_data.get('loading_message_id'):
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=context.user_data['loading_message_id']
                )
                logger.info(f"User {update.effective_user.id} deleted loading message")
            except Exception as e:
                logger.error(f"Failed to delete loading message: {e}")
        await save_new_point(update, context, send_message=True)
        context.user_data['point_saved'] = True  # Устанавливаем флаг после сохранения
        context.user_data.clear()  # Очищаем user_data после отправки
        return ConversationHandler.END
    return None

async def save_new_point(update: Update, context: ContextTypes.DEFAULT_TYPE, send_message: bool = False):
    if context.user_data.get('point_saved'):
        logger.info(f"User {update.effective_user.id} skipped saving point as it was already saved")
        return
    guide = load_guide()
    new_id = max([q["id"] for q in guide["questions"]], default=0) + 1
    new_point = {
        "id": new_id,
        "question": context.user_data['new_question'],
        "answer": context.user_data['answer']
    }
    if ENABLE_PHOTOS and context.user_data['photos']:
        new_point['photos'] = context.user_data['photos']
        logger.info(f"User {update.effective_user.id} added photos: {new_point['photos']}")
    guide["questions"].append(new_point)
    save_guide(guide)
    logger.info(f"User {update.effective_user.id} added new point: {new_point['question']}")
    if send_message:
        await update.message.reply_text(
            f"➕ Пункт добавлен!\nВопрос: {new_point['question']}",
            reply_markup=MAIN_MENU
        )
    context.user_data['point_saved'] = True  # Устанавливаем флаг после сохранения

@restrict_access
async def receive_answer_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.media_group_id == context.user_data.get('media_group_id'):
        context.user_data['photos'].append(update.message.photo[-1].file_id)
        context.user_data['last_photo_time'] = update.message.date
        logger.info(f"User {update.effective_user.id} added photo to media group: {update.message.photo[-1].file_id}")
        # Запускаем таймер только если он ещё не запущен
        if not context.user_data.get('timeout_task'):
            context.user_data['timeout_task'] = asyncio.create_task(check_album_timeout(update, context))
        return ANSWER_PHOTOS
    # Если получено сообщение с новым media_group_id или без него, завершаем текущий альбом
    if not context.user_data.get('point_saved') and context.user_data.get('photos'):
        logger.info(f"User {update.effective_user.id} finished album for media group {context.user_data.get('media_group_id')} due to new message")
        # Отменяем существующий таймер, если он есть
        if context.user_data.get('timeout_task'):
            context.user_data['timeout_task'].cancel()
            context.user_data['timeout_task'] = None
        # Удаляем сообщение "Загрузка"
        if context.user_data.get('loading_message_id'):
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=context.user_data['loading_message_id']
                )
                logger.info(f"User {update.effective_user.id} deleted loading message")
            except Exception as e:
                logger.error(f"Failed to delete loading message: {e}")
        await save_new_point(update, context, send_message=True)
        context.user_data['point_saved'] = True
        context.user_data.clear()
        return ConversationHandler.END
    return ANSWER_PHOTOS

# Редактирование пункта
@restrict_access
async def edit_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"User {update.effective_user.id} started editing a point")
    context.user_data.clear()  # Очищаем user_data
    guide = load_guide()
    if not guide["questions"]:
        await update.message.reply_text(
            "📖 Справочник пуст. Нечего редактировать! ➕",
            reply_markup=MAIN_MENU
        )
        return ConversationHandler.END
    context.user_data['guide'] = guide
    context.user_data['page'] = 0
    await display_edit_page(update, context, guide, 0)
    return EDIT_QUESTION

# Отображение страницы для редактирования
async def display_edit_page(update: Update, context: ContextTypes.DEFAULT_TYPE, guide, page):
    ITEMS_PER_PAGE = 15
    total_items = len(guide["questions"])
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))  # Ограничиваем страницу
    context.user_data['page'] = page
    context.user_data['guide'] = guide

    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, total_items)
    questions = guide["questions"][start_idx:end_idx]

    keyboard = [[InlineKeyboardButton(f"📄 {q['question']}", callback_data=f'edit_question_{q["id"]}')] for q in questions]
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'edit_page_{page-1}'))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f'edit_page_{page+1}'))
    nav_buttons.append(InlineKeyboardButton("🚪 Отмена", callback_data='cancel_edit'))
    keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"✏️ Выберите вопрос для редактирования (страница {page + 1}/{total_pages}):"
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
    logger.info(f"User {update.effective_user.id} viewed edit page {page + 1}")

# Обработка пагинации для редактирования
@restrict_access
async def handle_edit_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'cancel_edit':
        context.user_data.clear()
        await query.message.reply_text("🚪 Редактирование отменено.", reply_markup=MAIN_MENU)
        return ConversationHandler.END
    page = int(query.data.split('_')[2])
    guide = context.user_data.get('guide', load_guide())
    await display_edit_page(update, context, guide, page)
    return EDIT_QUESTION

@restrict_access
async def select_edit_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['edit_question_id'] = int(query.data.split('_')[2])
    logger.info(f"User {update.effective_user.id} selected question ID {context.user_data['edit_question_id']} for editing")
    keyboard = [
        [InlineKeyboardButton("Изменить вопрос", callback_data='edit_field_question')],
        [InlineKeyboardButton("Изменить ответ", callback_data='edit_field_answer')],
        [InlineKeyboardButton("Удалить пункт", callback_data='edit_field_delete')]
    ]
    if ENABLE_PHOTOS:
        keyboard.insert(2, [InlineKeyboardButton("Добавить/изменить фото", callback_data='edit_field_photo')])
    keyboard.append([InlineKeyboardButton("🚪 Отмена", callback_data='cancel_edit')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("✏️ Что хотите изменить?", reply_markup=reply_markup)
    return EDIT_FIELD

@restrict_access
async def receive_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'cancel_edit':
        context.user_data.clear()
        await query.message.reply_text("🚪 Редактирование отменено.", reply_markup=MAIN_MENU)
        return ConversationHandler.END
    context.user_data['edit_field'] = query.data
    logger.info(f"User {update.effective_user.id} chose to edit field: {query.data}")
    if query.data == 'edit_field_delete':
        guide = load_guide()
        question_id = context.user_data['edit_question_id']
        guide["questions"] = [q for q in guide["questions"] if q["id"] != question_id]
        save_guide(guide)
        context.user_data.clear()  # Очищаем user_data
        await query.message.reply_text("🗑️ Пункт удалён!", reply_markup=MAIN_MENU)
        return ConversationHandler.END
    field = "вопрос" if query.data == 'edit_field_question' else "ответ" if query.data == 'edit_field_answer' else "фото/альбом"
    prompt = f"✏️ Введите новый {field}:\n(Напишите /cancel для отмены)"
    await query.message.reply_text(
        prompt,
        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
    )
    return EDIT_VALUE

@restrict_access
async def receive_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guide = load_guide()
    question_id = context.user_data['edit_question_id']
    field = context.user_data['edit_field']
    for q in guide["questions"]:
        if q["id"] == question_id:
            if field == 'edit_field_question':
                q['question'] = update.message.text
            elif field == 'edit_field_answer':
                q['answer'] = update.message.text
            elif field == 'edit_field_photo' and ENABLE_PHOTOS:
                if update.message.photo:
                    q['photos'] = [update.message.photo[-1].file_id]
                    logger.info(f"User {update.effective_user.id} updated photo(s) for question ID {question_id}: {q['photos']}")
                    q.pop('photo', None)  # Удаляем старое поле 'photo'
                else:
                    await update.message.reply_text(
                        "❌ Пожалуйста, отправьте фото или альбом!\n(Напишите /cancel для отмены)",
                        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
                    )
                    return
            break
    save_guide(guide)
    logger.info(f"User {update.effective_user.id} updated {field} for question ID {question_id}")
    context.user_data.clear()  # Очищаем user_data
    await update.message.reply_text(
        f"✏️ {field.replace('edit_field_', '').capitalize()} обновлён!",
        reply_markup=MAIN_MENU
    )
    return ConversationHandler.END

# Обработчик неподдерживаемых сообщений
@restrict_access
async def handle_invalid_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.warning(f"User {update.effective_user.id} sent invalid input in conversation state")
    await update.message.reply_text(
        "❌ Пожалуйста, отправьте текст или фото/альбом (для ответа/фото)!\n(Напишите /cancel для отмены)",
        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
    )

# Запуск бота
async def main():
    application = Application.builder().token(os.getenv("BOT_TOKEN")).build()
    application.add_error_handler(error_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(MessageHandler(filters.Regex(r'^📖 Справочник$'), open_guide))
    application.add_handler(CallbackQueryHandler(show_answer, pattern='^question_.*$'))
    application.add_handler(CallbackQueryHandler(handle_pagination, pattern='^page_.*$'))
    add_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r'^➕ Добавить пункт$'), add_point)],
        states={
            QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_question)],
            ANSWER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_answer),
                MessageHandler(filters.PHOTO, receive_answer) if ENABLE_PHOTOS else None,
                MessageHandler(~(filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_invalid_input)
            ],
            ANSWER_PHOTOS: [
                MessageHandler(filters.PHOTO, receive_answer_photos) if ENABLE_PHOTOS else None,
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_answer),
                MessageHandler(~(filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_invalid_input)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=True  # Разрешаем повторный вход
    )
    application.add_handler(add_conv)
    edit_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r'^✏️ Редактировать пункт$'), edit_point)],
        states={
            EDIT_QUESTION: [
                CallbackQueryHandler(select_edit_question, pattern='^edit_question_.*$'),
                CallbackQueryHandler(handle_edit_pagination, pattern='^(edit_page_.*|cancel_edit)$')
            ],
            EDIT_FIELD: [CallbackQueryHandler(receive_edit_field, pattern='^(edit_field_.*|cancel_edit)$')],
            EDIT_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_value),
                MessageHandler(filters.PHOTO, receive_edit_value) if ENABLE_PHOTOS else None,
                MessageHandler(~(filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_invalid_input)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=True  # Разрешаем повторный вход
    )
    application.add_handler(edit_conv)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(r'^(📖 Справочник|➕ Добавить пункт|✏️ Редактировать пункт)$'), perform_search))
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("Bot is running...")
    # Keep the bot running until interrupted
    try:
        while True:
            await asyncio.sleep(3600)  # Sleep for an hour to keep the event loop alive
    except KeyboardInterrupt:
        await application.stop()
        await application.updater.stop()

if __name__ == '__main__':
    asyncio.run(main())