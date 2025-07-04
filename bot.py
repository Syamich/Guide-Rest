import json
import os
import subprocess
import random
import asyncio
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка .env
load_dotenv()

# Проверка BOT_TOKEN
if not os.getenv("BOT_TOKEN"):
    raise ValueError("BOT_TOKEN not found in environment variables. Please set it in .env or PythonAnywhere Environment Variables.")

# Состояния для ConversationHandler
QUESTION, ANSWER = range(2)
EDIT_QUESTION, EDIT_FIELD, EDIT_VALUE = range(3)

# Чтение JSON
def load_guide():
    try:
        with open('guide.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"questions": []}

def load_jokes():
    try:
        with open('jokes.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"jokes": []}

# Чтение user_id из переменной окружения
def load_users():
    users_str = os.getenv("ALLOWED_USERS", "")
    if not users_str:
        return []
    try:
        return [int(user_id) for user_id in users_str.split(",")]
    except ValueError:
        logger.error("ALLOWED_USERS contains invalid user IDs. Expected comma-separated integers.")
        return []

# Сохранение JSON и синхронизация с GitHub
def save_guide(data):
    with open('guide.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    sync_with_github()

def sync_with_github():
    try:
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if "guide.json" not in result.stdout:
            logger.info("No changes in guide.json to commit.")
            return
        subprocess.run(["git", "add", "guide.json"], check=True)
        subprocess.run(["git", "commit", "-m", "Update guide.json via bot"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        logger.info("Successfully synced guide.json to GitHub.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Git sync error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during git sync: {e}")

# Проверка доступа
def restrict_access(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        users = load_users()
        if user_id not in users:
            if update.message:
                await update.message.reply_text("🚫 Доступ запрещён! Обратитесь к администратору.")
            elif update.callback_query:
                await update.callback_query.message.reply_text("🚫 Доступ запрещён! Обратитесь к администратору.")
            logger.warning(f"Unauthorized access attempt by user {user_id}")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# Команда /start
@restrict_access
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"User {update.effective_user.id} started the bot")
    jokes = load_jokes()
    joke = random.choice(jokes["jokes"]) if jokes["jokes"] else "Справочник готов к работе! 😄"
    keyboard = [
        [InlineKeyboardButton("📖 Открыть справочник", callback_data='open_guide')],
        [InlineKeyboardButton("➕ Добавить пункт", callback_data='add_point')],
        [InlineKeyboardButton("✏️ Редактировать пункт", callback_data='edit_point')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Добро пожаловать в справочник техподдержки РЭСТ! 📋\n[Шутка: {joke}]", reply_markup=reply_markup)

# Команда /cancel
@restrict_access
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"User {update.effective_user.id} cancelled the conversation")
    await update.message.reply_text("🚪 Диалог отменён. Напишите /start для возврата в меню.")
    return ConversationHandler.END

# Открытие справочника
@restrict_access
async def open_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info(f"User {update.effective_user.id} opened the guide")
    guide = load_guide()
    if not guide["questions"]:
        await query.message.reply_text("📖 Справочник пуст. Добавьте первый пункт! ➕")
        return
    keyboard = [[InlineKeyboardButton(f"📄 {q['question']}", callback_data=f'question_{q["id"]}')] for q in guide["questions"]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    jokes = load_jokes()
    joke = random.choice(jokes["jokes"]) if jokes["jokes"] else "Выберите вопрос!"
    await query.message.reply_text(f"📖 Справочник:\n[Шутка: {joke}]", reply_markup=reply_markup)

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
        await query.message.reply_text(f"📄 Вопрос: {question['question']}\nОтвет: {question['answer']}")
    else:
        await query.message.reply_text("❌ Вопрос не найден!")

# Поиск по ключевым словам
@restrict_access
async def perform_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.lower()
    logger.info(f"User {update.effective_user.id} searched for '{keyword}'")
    guide = load_guide()
    results = [q for q in guide["questions"] if keyword in q["question"].lower() or keyword in q["answer"].lower()]
    if not results:
        await update.message.reply_text("🔍 Ничего не найдено. Попробуйте другое ключевое слово!")
        return
    keyboard = [[InlineKeyboardButton(f"📄 {q['question']}", callback_data=f'question_{q["id"]}')] for q in results]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"🔍 Результаты поиска для '{keyword}':", reply_markup=reply_markup)

# Добавление пункта
@restrict_access
async def add_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info(f"User {update.effective_user.id} started adding a new point")
    await query.message.reply_text("➕ Введите вопрос (например, 'Ошибка входа в систему'):\n(Напишите /cancel для отмены)")
    return QUESTION

@restrict_access
async def receive_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_question'] = update.message.text
    logger.info(f"User {update.effective_user.id} entered question: {update.message.text}")
    await update.message.reply_text("Введите подсказку для решения:\n(Напишите /cancel для отмены)")
    return ANSWER

@restrict_access
async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guide = load_guide()
    new_id = max([q["id"] for q in guide["questions"]], default=0) + 1
    new_point = {
        "id": new_id,
        "question": context.user_data['new_question'],
        "answer": update.message.text
    }
    guide["questions"].append(new_point)
    save_guide(guide)
    logger.info(f"User {update.effective_user.id} added new point: {new_point['question']}")
    await update.message.reply_text(f"➕ Пункт добавлен!\nВопрос: {new_point['question']}")
    return ConversationHandler.END

# Редактирование пункта
@restrict_access
async def edit_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info(f"User {update.effective_user.id} started editing a point")
    guide = load_guide()
    if not guide["questions"]:
        await query.message.reply_text("📖 Справочник пуст. Нечего редактировать! ➕")
        return
    keyboard = [[InlineKeyboardButton(f"📄 {q['question']}", callback_data=f'edit_question_{q["id"]}')] for q in guide["questions"]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("✏️ Выберите вопрос для редактирования:\n(Напишите /cancel для отмены)", reply_markup=reply_markup)
    return EDIT_QUESTION

@restrict_access
async def select_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['edit_question_id'] = int(query.data.split('_')[2])
    logger.info(f"User {update.effective_user.id} selected question ID {context.user_data['edit_question_id']} for editing")
    keyboard = [
        [InlineKeyboardButton("Изменить вопрос", callback_data='edit_field_question')],
        [InlineKeyboardButton("Изменить ответ", callback_data='edit_field_answer')],
        [InlineKeyboardButton("Удалить пункт", callback_data='edit_field_delete')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("✏️ Что хотите изменить?\n(Напишите /cancel для отмены)", reply_markup=reply_markup)
    return EDIT_FIELD

@restrict_access
async def receive_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['edit_field'] = query.data
    logger.info(f"User {update.effective_user.id} chose to edit field: {query.data}")
    if query.data == 'edit_field_delete':
        guide = load_guide()
        question_id = context.user_data['edit_question_id']
        guide["questions"] = [q for q in guide["questions"] if q["id"] != question_id]
        save_guide(guide)
        await query.message.reply_text("🗑️ Пункт удалён!")
        return ConversationHandler.END
    field = "вопрос" if query.data == 'edit_field_question' else "ответ"
    await query.message.reply_text(f"✏️ Введите новый {field}:\n(Напишите /cancel для отмены)")
    return EDIT_VALUE

@restrict_access
async def receive_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guide = load_guide()
    question_id = context.user_data['edit_question_id']
    field = "question" if context.user_data['edit_field'] == 'edit_field_question' else "answer"
    for q in guide["questions"]:
        if q["id"] == question_id:
            q[field] = update.message.text
            break
    save_guide(guide)
    logger.info(f"User {update.effective_user.id} updated {field} for question ID {question_id}")
    await update.message.reply_text(f"✏️ {field.capitalize()} обновлён!")
    return ConversationHandler.END

# Запуск бота
async def main():
    application = Application.builder().token(os.getenv("BOT_TOKEN")).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(open_guide, pattern='open_guide'))
    application.add_handler(CallbackQueryHandler(show_answer, pattern='question_.*'))
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_point, pattern='add_point')],
        states={
            QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_question)],
            ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_answer)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    application.add_handler(add_conv)
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_point, pattern='edit_point')],
        states={
            EDIT_QUESTION: [CallbackQueryHandler(select_edit_field, pattern='edit_question_.*')],
            EDIT_FIELD: [CallbackQueryHandler(receive_edit_field, pattern='edit_field_.*')],
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_value)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    application.add_handler(edit_conv)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, perform_search))
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
