import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# --- Настройки ---
# Токен и URL будут браться из переменных окружения хостинга
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Это адрес, который выдаст хостинг после запуска
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0") 
WEBHOOK_PORT = int(os.getenv("PORT", 8080))
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN') or os.getenv('APP_DOMAIN') or 'your-app-domain.justrunmy.app'}{WEBHOOK_PATH}"

# --- Логика бота ---
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Хранилища
waiting_users = []
pairs = {}

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

# --- Запуск Webhook ---
async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook set to {WEBHOOK_URL}")

def main():
    # Настраиваем веб-сервер для приема сообщений от Telegram
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    
    # Запускаем сервер на порту, который выдал хостинг
    web.run_app(app, host=WEBHOOK_HOST, port=WEBHOOK_PORT)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())