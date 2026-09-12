import asyncio
import logging
import os
import time
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- Хранилища ---
waiting_users = []
pairs = {}
reports = {}
banned_until = {}
blacklist = {}       # {user_id: set(заблокированные_id)}
user_stats = {}      # {user_id: {'chats': N, 'rep_given': N, 'rep_recv': N, 'since': ts}}
start_time = time.time()

BAN_THRESHOLD = 3
BAN_DURATION = 3600

# --- Вспомогательные ---
def get_stats(uid):
    if uid not in user_stats:
        user_stats[uid] = {'chats': 0, 'rep_given': 0, 'rep_recv': 0, 'since': time.time()}
    return user_stats[uid]

def is_banned(user_id):
    if user_id in banned_until:
        if time.time() < banned_until[user_id]:
            return True
        del banned_until[user_id]
        reports.pop(user_id, None)
    return False

def is_blocked(a, b):
    """Проверяет, блокировал ли кто-то кого-то."""
    return b in blacklist.get(a, set()) or a in blacklist.get(b, set())

def fmt_time(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h: return f"{h}ч {m}м"
    if m: return f"{m}м {s}с"
    return f"{s}с"

# --- Клавиатуры ---
def kb_idle():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти собеседника", callback_data="find_partner")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
    ])

def kb_searching():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить поиск", callback_data="cancel_search")]
    ])

def kb_in_chat():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛔ Остановить чат", callback_data="stop_chat")],
        [InlineKeyboardButton(text="⚠️ Пожаловаться", callback_data="report_user")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data="block_user")],
    ])

# --- Функции ---
async def find_partner(user_id, message=None, callback=None):
    async def send(text, kb=None):
        if callback: await callback.message.answer(text, reply_markup=kb)
        else: await message.answer(text, reply_markup=kb)

    if is_banned(user_id):
        left = int((banned_until[user_id] - time.time()) / 60)
        await send(f"🚫 Ты временно заблокирован. Осталось: {left} мин.")
        return
    if user_id in pairs:
        await send("Ты уже в чате.", kb_in_chat())
        return
    if user_id in waiting_users:
        await send("Ты уже в очереди, ждём собеседника...", kb_searching())
        return

    # Ищем партнёра (не забаненного и не в чёрном списке)
    partner = None
    while waiting_users:
        candidate = waiting_users.pop(0)
        if is_banned(candidate): continue
        if is_blocked(user_id, candidate): continue
        partner = candidate
        break

    if partner is None:
        waiting_users.append(user_id)
        await send("🔎 Ищем собеседника...", kb_searching())
        return

    pairs[user_id] = partner
    pairs[partner] = user_id
    get_stats(user_id)['chats'] += 1
    get_stats(partner)['chats'] += 1
    await send("✅ Собеседник найден! Можешь писать.", kb_in_chat())
    await bot.send_message(partner, "✅ Собеседник найден! Можешь писать.", reply_markup=kb_in_chat())

async def cancel_search(user_id, message=None, callback=None):
    async def send(text, kb=None):
        if callback: await callback.message.answer(text, reply_markup=kb)
        else: await message.answer(text, reply_markup=kb)
    if user_id in waiting_users:
        waiting_users.remove(user_id)
        await send("🚫 Поиск отменён.", kb_idle())
    else:
        await send("Ты не в поиске.", kb_idle())

async def stop_chat(user_id, message=None, callback=None, notify=True):
    async def send(text, kb=None):
        if callback: await callback.message.answer(text, reply_markup=kb)
        else: await message.answer(text, reply_markup=kb)
    partner = pairs.pop(user_id, None)
    if partner:
        pairs.pop(partner, None)
        if notify:
            try:
                await bot.send_message(partner, "❌ Собеседник вышел из чата.", reply_markup=kb_idle())
            except Exception: pass
        await send("Ты вышел из чата.", kb_idle())
    else:
        if user_id in waiting_users: waiting_users.remove(user_id)
        await send("Ты не в чате.", kb_idle())

async def report_user(user_id, callback):
    partner = pairs.get(user_id)
    if not partner:
        await callback.message.answer("Не на кого жаловаться.", reply_markup=kb_idle())
        return
    reports[partner] = reports.get(partner, 0) + 1
    get_stats(partner)['rep_recv'] += 1
    get_stats(user_id)['rep_given'] += 1
    count = reports[partner]
    pairs.pop(user_id, None)
    pairs.pop(partner, None)
    try:
        await bot.send_message(partner, "❌ Собеседник пожаловался на тебя. Чат завершён.", reply_markup=kb_idle())
    except Exception: pass
    if count >= BAN_THRESHOLD:
        banned_until[partner] = time.time() + BAN_DURATION
        reports[partner] = 0
        text = "✅ Жалоба принята. Пользователь забанен на 1 час."
    else:
        text = f"✅ Жалоба принята. Жалоб на пользователя: {count}/{BAN_THRESHOLD}."
    await callback.message.answer(text, reply_markup=kb_idle())

async def block_user(user_id, callback):
    partner = pairs.get(user_id)
    if not partner:
        await callback.message.answer("Некого блокировать.", reply_markup=kb_idle())
        return
    blacklist.setdefault(user_id, set()).add(partner)
    pairs.pop(user_id, None)
    pairs.pop(partner, None)
    try:
        await bot.send_message(partner, "❌ Собеседник завершил чат.", reply_markup=kb_idle())
    except Exception: pass
    await callback.message.answer(
        "🚫 Пользователь добавлен в чёрный список. Бот больше никогда вас не соединит.",
        reply_markup=kb_idle()
    )

async def show_profile(user_id, callback):
    s = get_stats(user_id)
    age = fmt_time(time.time() - s['since'])
    blocked_count = len(blacklist.get(user_id, set()))
    text = (
        f"👤 <b>Твой профиль</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💬 Чатов: {s['chats']}\n"
        f"⚠️ Жалоб отправлено: {s['rep_given']}\n"
        f"🚨 Жалоб получено: {s['rep_recv']}\n"
        f"🚫 В чёрном списке: {blocked_count}\n"
        f"⏱ В боте: {age}"
    )
    await callback.message.answer(text, reply_markup=kb_idle(), parse_mode="HTML")

HELP_TEXT = (
    "❓ <b>Помощь</b>\n\n"
    "🔍 <b>Найти собеседника</b> — ставит тебя в очередь. Когда найдётся пара, бот соединит вас.\n\n"
    "❌ <b>Отменить поиск</b> — выйти из очереди, если передумал.\n\n"
    "⛔ <b>Остановить чат</b> — разорвать текущий диалог.\n\n"
    "⚠️ <b>Пожаловаться</b> — жалуешься на собеседника. После 3 жалоб его банят на час.\n\n"
    "🚫 <b>Заблокировать</b> — добавляет пользователя в личный чёрный список. Бот больше вас не соединит.\n\n"
    "👤 <b>Профиль</b> — твоя личная статистика.\n\n"
    "📝 Можно отправлять текст, фото, видео, голосовые, стикеры и кружочки — всё пересылается собеседнику."
)

ABOUT_TEXT = (
    "ℹ️ <b>О боте</b>\n\n"
    "«Тёплые Черви» — бот для анонимного общения.\n"
    "Соединяет двух случайных людей, чтобы они могли поболтать.\n\n"
    "🔒 Мы не собираем личные данные.\n"
    "⚡ Работает 24/7.\n\n"
    "Если нашёл баг или есть идея — напиши разработчику: @anticvarca"
)

# --- Команды ---
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

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, reply_markup=kb_idle(), parse_mode="HTML")

@dp.message(Command("about"))
async def cmd_about(message: Message):
    await message.answer(ABOUT_TEXT, reply_markup=kb_idle(), parse_mode="HTML")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Команда только для админа.")
        return
    total_users = len(user_stats)
    in_queue = len(waiting_users)
    in_chats = len(pairs) // 2
    banned = len([u for u in banned_until if time.time() < banned_until[u]])
    total_chats = sum(s['chats'] for s in user_stats.values()) // 2
    uptime = fmt_time(time.time() - start_time)
    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"💬 Всего чатов создано: {total_chats}\n"
        f"🔎 Сейчас в очереди: {in_queue}\n"
        f"💭 Сейчас в чатах: {in_chats}\n"
        f"🚫 Забанено: {banned}\n"
        f"⏱ Аптайм: {uptime}"
    )
    await message.answer(text, parse_mode="HTML")

# --- Колбэки ---
@dp.callback_query(F.data == "find_partner")
async def cb_find(cb: CallbackQuery):
    await cb.answer()
    await find_partner(cb.from_user.id, callback=cb)

@dp.callback_query(F.data == "cancel_search")
async def cb_cancel(cb: CallbackQuery):
    await cb.answer()
    await cancel_search(cb.from_user.id, callback=cb)

@dp.callback_query(F.data == "stop_chat")
async def cb_stop(cb: CallbackQuery):
    await cb.answer()
    await stop_chat(cb.from_user.id, callback=cb)

@dp.callback_query(F.data == "report_user")
async def cb_report(cb: CallbackQuery):
    await cb.answer()
    await report_user(cb.from_user.id, cb)

@dp.callback_query(F.data == "block_user")
async def cb_block(cb: CallbackQuery):
    await cb.answer()
    await block_user(cb.from_user.id, cb)

@dp.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery):
    await cb.answer()
    await show_profile(cb.from_user.id, cb)

@dp.callback_query(F.data == "help")
async def cb_help(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer(HELP_TEXT, reply_markup=kb_idle(), parse_mode="HTML")

# --- Пересылка сообщений ---
@dp.message()
async def relay_message(message: Message):
    uid = message.from_user.id
    if is_banned(uid):
        left = int((banned_until[uid] - time.time()) / 60)
        await message.answer(f"🚫 Ты заблокирован. Осталось: {left} мин.")
        return
    partner = pairs.get(uid)
    if partner:
        try:
            await message.copy_to(chat_id=partner)
        except Exception as e:
            await message.answer("⚠️ Не удалось отправить сообщение.")
            logging.error(f"Ошибка пересылки: {e}")
    else:
        await message.answer("Ты не в чате.", reply_markup=kb_idle())

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
