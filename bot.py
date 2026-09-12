import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()

waiting_users = []
pairs = {}

# --- Клавиатура с кнопками ---
def get_main_keyboard():
    kb = [
        [InlineKeyboardButton(text="🔍 Найти собеседника", callback_data="find_partner")],
        [InlineKeyboardButton(text="❌ Остановить чат", callback_data="stop_chat")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- Функция поиска собеседника ---
async def find_partner(user_id, message: Message = None, callback: CallbackQuery = None):
    # Если пользователь уже в паре
    if user_id in pairs:
        text = "Ты уже в чате. Нажми «Остановить чат», чтобы выйти."
        if callback: await callback.message.answer(text)
        else: await message.answer(text)
        return

    # Если пользователь уже в очереди
    if user_id in waiting_users:
        text = "Ты уже в очереди, ждём собеседника..."
        if callback: await callback.message.answer(text)
        else: await message.answer(text)
        return

    # Ищем пару
    if waiting_users:
        partner = waiting_users.pop(0)
        pairs[user_id] = partner
        pairs[partner] = user_id
        
        # Уведомляем обоих
        if callback: await callback.message.answer("✅ Собеседник найден! Можешь писать.", reply_markup=get_main_keyboard())
        else: await message.answer("✅ Собеседник найден! Можешь писать.", reply_markup=get_main_keyboard())
        
        await bot.send_message(partner, "✅ Собеседник найден! Можешь писать.", reply_markup=get_main_keyboard())
    else:
        waiting_users.append(user_id)
        text = "🔎 Ищем собеседника..."
        if callback: await callback.message.answer(text, reply_markup=get_main_keyboard())
        else: await message.answer(text, reply_markup=get_main_keyboard())

# --- Функция остановки чата ---
async def stop_chat(user_id, message: Message = None, callback: CallbackQuery = None):
    partner = pairs.pop(user_id, None)
    if partner:
        pairs.pop(partner, None)
        await bot.send_message(partner, "❌ Собеседник вышел из чата. Нажми /start чтобы найти нового.", reply_markup=get_main_keyboard())
        text = "Ты вышел из чата."
    else:
        if user_id in waiting_users:
            waiting_users.remove(user_id)
        text = "Ты не в чате."
    
    if callback: await callback.message.answer(text, reply_markup=get_main_keyboard())
    else: await message.answer(text, reply_markup=get_main_keyboard())

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я бот для анонимного общения.\nНажми кнопку ниже, чтобы найти собеседника.",
        reply_markup=get_main_keyboard()
    )

# --- Обработчики кнопок (Callback Query) ---
@dp.callback_query(F.data == "find_partner")
async def cb_find(callback: CallbackQuery):
    await callback.answer() # Убирает часики на кнопке
    await find_partner(callback.from_user.id, callback=callback)

@dp.callback_query(F.data == "stop_chat")
async def cb_stop(callback: CallbackQuery):
    await callback.answer()
    await stop_chat(callback.from_user.id, callback=callback)

# --- Пересылка сообщений (текст, фото, голосовые, стикеры) ---
@dp.message()
async def relay_message(message: Message):
    user_id = message.from_user.id
    partner = pairs.get(user_id)
    
    if partner:
        # copy_to умеет пересылать всё: текст, фото, видео, голосовые, стикеры
        try:
            await message.copy_to(chat_id=partner)
        except Exception as e:
            await message.answer("⚠️ Не удалось отправить это сообщение. Попробуй другое.")
            logging.error(f"Ошибка пересылки: {e}")
    else:
        await message.answer(
            "Ты не в чате. Нажми кнопку ниже, чтобы найти собеседника.",
            reply_markup=get_main_keyboard()
        )

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
