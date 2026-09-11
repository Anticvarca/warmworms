import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

TOKEN = "8653439919:AAFUF8XPbhGpjgzZSzx9lgcop7JBhYf910k"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Хранилища
waiting_users = []          # очередь ожидающих
pairs = {}                  # {user_id: partner_id}

@dp.message(Command("start"))
async def start(message: Message):
    uid = message.from_user.id
    if uid in pairs:
        await message.answer("Ты уже в чате. Напиши /stop чтобы выйти.")
        return

    if uid in waiting_users:
        await message.answer("Ты уже в очереди, ждём собеседника...")
        return

    if waiting_users:
        partner = waiting_users.pop(0)
        pairs[uid] = partner
        pairs[partner] = uid
        await message.answer("✅ Собеседник найден! Можешь писать.")
        await bot.send_message(partner, "✅ Собеседник найден! Можешь писать.")
    else:
        waiting_users.append(uid)
        await message.answer("🔎 Ищем собеседника...")

@dp.message(Command("stop"))
async def stop(message: Message):
    uid = message.from_user.id
    partner = pairs.pop(uid, None)
    if partner:
        pairs.pop(partner, None)
        await bot.send_message(partner, "❌ Собеседник вышел из чата. Напиши /start чтобы найти нового.")
        await message.answer("Ты вышел из чата.")
    else:
        if uid in waiting_users:
            waiting_users.remove(uid)
        await message.answer("Ты не в чате.")

@dp.message(F.text)
async def relay(message: Message):
    uid = message.from_user.id
    partner = pairs.get(uid)
    if partner:
        await bot.send_message(partner, message.text)
    else:
        await message.answer("Ты не в чате. Напиши /start чтобы найти собеседника.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())