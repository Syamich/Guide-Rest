import json
import os
import subprocess
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    Filters,
    ContextTypes,
)

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

def load_users():
    try:
        with open('users.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"users": []}

# Сохранение JSON и синхронизация с GitHub
def save_guide(data):
    with open('guide.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    sync_with_github()

def sync_with_github():
    try:
        # Проверяем, есть ли изменения
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if "guide.json" not in result.stdout:
            print("No changes in guide.json to commit.")
            return
        
        subprocess.run(["git", "add", "guide.json"], check=True)
        subprocess.run(["git", "commit", "-m", "Update guide.json via bot"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        print("Successfully synced guide.json to GitHub.")
    except subprocess.CalledProcessError as e:
        print(f"Git sync error: {e}")
    except Exception as e:
        print(f"Unexpected error during git sync: {e}")

# Проверка доступа
def restrict_access(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        users = load_users()
        if user_id not in users["users"]:
            await update.message.reply_text("🚫 Доступ запрещён! Обратитесь к администратору.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# Команда /start
@restrict_access
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jokes = load_jokes()
    joke = random.choice(jokes["jokes"]) if jokes["jokes"] else "Справочник готов к работе! 😄"
    keyboard = [
        [InlineKeyboardButton("📖 Открыть справочник", callback_data='open_guide')],
        [InlineKeyboardButton("➕ Добавить пункт", callback_data='add_point')],
        [InlineKeyboardButton("✏️ Редактировать пункт", callback_data='edit_point')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Добро пожаловать в справочник техподдержки РЭСТ! 📋\n[Шутка: {joke}]", reply_markup=reply_markup)

# Открытие справочника
async def open_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
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
async def show_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    question_id = int(query.data.split('_')[1])
    guide = load_guide()
    question = next((q for q in guide["questions"] if q["id"] == question_id), None)
    if question:
        await query.message.reply_text(f"📄 Вопрос: {question['question']}\nОтвет: {question['answer']}")

# Поиск по ключевым словам
@restrict_access
async def perform_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.lower()
    guide = load_guide()
    results = [q for q in guide["questions"] if keyword in q["question"].lower() or keyword in q["answer"].lower()]
    
    if not results:
        await update.message.reply_text("🔍 Ничего не найдено. Попробуйте другое ключевое слово!")
        return
    
    keyboard = [[InlineKeyboardButton(f"📄 {q['question']}", callback_data=f'question_{q["id"]}')] for q in results]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"🔍 Результаты поиска для '{keyword}':", reply_markup=reply_markup)

# Добавление пункта
async def add_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("➕ Введите вопрос (например, 'Ошибка входа в систему'):")
    return QUESTION

async def receive_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_question'] = update.message.text
    await update.message.reply_text("Введите подсказку для решения:")
    return ANSWER

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
    await update.message.reply_text(f"➕ Пункт добавлен!\nВопрос: {new_point['question']}")
    return ConversationHandler.END

# Редактирование пункта
async def edit_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    guide = load_guide()
    if not guide["questions"]:
        await query.message.reply_text("📖 Справочник пуст. Нечего редактировать! ➕")
        return
    
    keyboard = [[InlineKeyboardButton(f"📄 {q['question']}", callback_data=f'edit_question_{q["id"]}')] for q in guide["questions"]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("✏️ Выберите вопрос для редактирования:", reply_markup=reply_markup)

async def select_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['edit_question_id'] = int(query.data.split('_')[2])
    keyboard = [
        [InlineKeyboardButton("Изменить вопрос", callback_data='edit_field_question')],
        [InlineKeyboardButton("Изменить ответ", callback_data='edit_field_answer')],
        [InlineKeyboardButton("Удалить пункт", callback_data='edit_field_delete')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("✏️ Что хотите изменить?", reply_markup=reply_markup)
    return EDIT_FIELD

async def receive_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['edit_field'] = query.data
    if query.data == 'edit_field_delete':
        guide = load_guide()
        question_id = context.user_data['edit_question_id']
        guide["questions"] = [q for q in guide["questions"] if q["id"] != question_id]
        save_guide(guide)
        await query.message.reply_text("🗑️ Пункт удалён!")
        return ConversationHandler.END
    field = "вопрос" if query.data == 'edit_field_question' else "ответ"
    await query.message.reply_text(f"✏️ Введите новый {field}:")
    return EDIT_VALUE

async def receive_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guide = load_guide()
    question_id = context.user_data['edit_question_id']
    field = "question" if context.user_data['edit_field'] == 'edit_field_question' else "answer"
    for q in guide["questions"]:
        if q["id"] == question_id:
            q[field] = update.message.text
            break
    save_guide(guide)
    await update.message.reply_text(f"✏️ {field.capitalize()} обновлён!")
    return ConversationHandler.END

# Запуск бота
def main():
    app = Application.builder().token(os.getenv("BOT_TOKEN")).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(open_guide, pattern='open_guide'))
    app.add_handler(CallbackQueryHandler(show_answer, pattern='question_.*'))
    app.add_handler(CallbackQueryHandler(add_point, pattern='add_point'))
    app.add_handler(CallbackQueryHandler(edit_point, pattern='edit_point'))
    
    # Поиск по любому текстовому сообщению
    app.add_handler(MessageHandler(Filters.text & ~Filters.command, perform_search))
    
    # Добавление пункта
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_point, pattern='add_point')],
        states={
            QUESTION: [MessageHandler(Filters.text & ~Filters.command, receive_question)],
            ANSWER: [MessageHandler(Filters.text & ~Filters.command, receive_answer)]
        },
        fallbacks=[]
    )
    app.add_handler(add_conv)
    
    # Редактирование пункта
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_point, pattern='edit_point')],
        states={
            EDIT_QUESTION: [CallbackQueryHandler(select_edit_field, pattern='edit_question_.*')],
            EDIT_FIELD: [CallbackQueryHandler(receive_edit_field, pattern='edit_field_.*')],
            EDIT_VALUE: [MessageHandler(Filters.text & ~Filters.command, receive_edit_value)]
        },
        fallbacks=[]
    )
    app.add_handler(edit_conv)
    
    app.run_polling()

if __name__ == '__main__':
    main()
