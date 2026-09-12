import asyncio
import logging
import os
import time
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- Хранилища ---
waiting_users = []      # очередь ожидающих
pairs = {}              # {user_id: partner_id}
reports = {}            # {user_id: количество жалоб}
banned_until = {}       # {user_id: timestamp окончания бана}

# --- Настройки ---
BAN_THRESHOLD = 3       # сколько жалоб до бана
BAN_DURATION = 3600     # длительность бана в секундах (1 час)

# --- Клавиатуры ---
def kb_idle():
    """Клавиатура, когда пользователь не в чате и не в очереди."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти собеседника", callback_data="find_partner")]
    ])

def kb_searching():
    """Клавиатура, когда пользователь в очереди."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить поиск", callback_data="cancel_search")]
    ])

def kb_in_chat():
    """Клавиатура, когда пользователь в чате."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛔ Остановить чат", callback_data="stop_chat")],
        [InlineKeyboardButton(text="⚠️ Пожаловаться", callback_data="report_user")]
    ])

# --- Проверка бана ---
def is_banned(user_id):
    if user_id in banned_until:
        if time.time() < banned_until[user_id]:
            return True
        else:
            # Время бана истекло — снимаем
            del banned_until[user_id]
            reports.pop(user_id, None)
    return False

# --- Функция поиска собеседника ---
async def find_partner(user_id, message: Message = None, callback: CallbackQuery = None):
    async def send(text, keyboard=None):
        if callback:
            await callback.message.answer(text, reply_markup=keyboard)
        else:
            await message.answer(text, reply_markup=keyboard)

    # Проверка на бан
    if is_banned(user_id):
        left = int((banned_until[user_id] - time.time()) / 60)
        await send(f"🚫 Ты временно заблокирован за жалобы. Осталось: {left} мин.")
        return

    if user_id in pairs:
        await send("Ты уже в чате.", kb_in_chat())
        return

    if user_id in waiting_users:
        await send("Ты уже в очереди, ждём собеседника...", kb_searching())
        return

    if waiting_users:
        # Ищем подходящего партнёра (не забаненного)
        partner = None
        while waiting_users:
            candidate = waiting_users.pop(0)
            if not is_banned(candidate):
                partner = candidate
                break
        
        if partner is None:
            # Все в очереди оказались забанены — встаем сами
            waiting_users.append(user_id)
            await send("🔎 Ищем собеседника...", kb_searching())
            return

        pairs[user_id] = partner
        pairs[partner] = user_id
        await send("✅ Собеседник найден! Можешь писать.", kb_in_chat())
        await bot.send_message(partner, "✅ Собеседник найден! Можешь писать.", reply_markup=kb_in_chat())
    else:
        waiting_users.append(user_id)
        await send("🔎 Ищем собеседника...", kb_searching())

# --- Функция отмены поиска ---
async def cancel_search(user_id, message: Message = None, callback: CallbackQuery = None):
    async def send(text, keyboard=None):
        if callback:
            await callback.message.answer(text, reply_markup=keyboard)
        else:
            await message.answer(text, reply_markup=keyboard)

    if user_id in waiting_users:
        waiting_users.remove(user_id)
        await send("🚫 Поиск отменён.", kb_idle())
    else:
        await send("Ты не в поиске.", kb_idle())

# --- Функция остановки чата ---
async def stop_chat(user_id, message: Message = None, callback: CallbackQuery = None, notify_partner=True):
    async def send(text, keyboard=None):
        if callback:
            await callback.message.answer(text, reply_markup=keyboard)
        else:
            await message.answer(text, reply_markup=keyboard)

    partner = pairs.pop(user_id, None)
    if partner:
        pairs.pop(partner, None)
        if notify_partner:
            await bot.send_message(
                partner,
                "❌ Собеседник вышел из чата. Нажми «Найти собеседника», чтобы найти нового.",
                reply_markup=kb_idle()
            )
        await send("Ты вышел из чата.", kb_idle())
    else:
        if user_id in waiting_users:
            waiting_users.remove(user_id)
        await send("Ты не в чате.", kb_idle())

# --- Функция жалобы ---
async def report_user(user_id, callback: CallbackQuery):
    partner = pairs.get(user_id)
    if not partner:
        await callback.message.answer("Не на кого жаловаться.", reply_markup=kb_idle())
        return

    # Считаем жалобу
    reports[partner] = reports.get(partner, 0) + 1
    count = reports[partner]

    # Разрываем чат
    pairs.pop(user_id, None)
    pairs.pop(partner, None)

    # Уведомляем нарушителя
    try:
        await bot.send_message(partner, "❌ Собеседник пожаловался на тебя. Чат завершён.", reply_markup=kb_idle())
    except Exception:
        pass

    # Проверяем, не пора ли банить
    if count >= BAN_THRESHOLD:
        banned_until[partner] = time.time() + BAN_DURATION
        reports[partner] = 0
        text = "✅ Жалоба принята. Пользователь заблокирован на 1 час."
    else:
        text = f"✅ Жалоба принята. Всего жалоб на пользователя: {count}/{BAN_THRESHOLD}."

    await callback.message.answer(text, reply_markup=kb_idle())

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if is_banned(message.from_user.id):
        left = int((banned_until[message.from_user.id] - time.time()) / 60)
        await message.answer(f"🚫 Ты заблокирован. Осталось: {left} мин.")
        return
    await message.answer(
        "👋 Привет! Я бот для анонимного общения.\nНажми кнопку ниже, чтобы найти собеседника.",
        reply_markup=kb_idle()
    )

# --- Обработчики кнопок ---
@dp.callback_query(F.data == "find_partner")
async def cb_find(callback: CallbackQuery):
    await callback.answer()
    await find_partner(callback.from_user.id, callback=callback)

@dp.callback_query(F.data == "cancel_search")
async def cb_cancel(callback: CallbackQuery):
    await callback.answer()
    await cancel_search(callback.from_user.id, callback=callback)

@dp.callback_query(F.data == "stop_chat")
async def cb_stop(callback: CallbackQuery):
    await callback.answer()
    await stop_chat(callback.from_user.id, callback=callback)

@dp.callback_query(F.data == "report_user")
async def cb_report(callback: CallbackQuery):
    await callback.answer()
    await report_user(callback.from_user.id, callback)

# --- Пересылка сообщений ---
@dp.message()
async def relay_message(message: Message):
    user_id = message.from_user.id

    if is_banned(user_id):
        left = int((banned_until[user_id] - time.time()) / 60)
        await message.answer(f"🚫 Ты заблокирован. Осталось: {left} мин.")
        return

    partner = pairs.get(user_id)
    if partner:
        try:
            await message.copy_to(chat_id=partner)
        except Exception as e:
            await message.answer("⚠️ Не удалось отправить это сообщение.")
            logging.error(f"Ошибка пересылки: {e}")
    else:
        await message.answer(
            "Ты не в чате. Нажми кнопку ниже, чтобы найти собеседника.",
            reply_markup=kb_idle()
        )

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
