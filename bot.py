import asyncio
import logging
import os
import time
from urllib.parse import quote
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
blacklist = {}
user_stats = {}
reports_log = []        # [(reporter_id, target_id, timestamp, reason)]
start_time = time.time()
BOT_USERNAME = None

BAN_THRESHOLD = 3
BAN_DURATION = 3600
AUTO_DELETE_DELAY = 15

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
    return b in blacklist.get(a, set()) or a in blacklist.get(b, set())

def fmt_time(seconds):
    if seconds == float('inf'): return "навсегда"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d: return f"{d}д {h}ч"
    if h: return f"{h}ч {m}м"
    if m: return f"{m}м"
    return f"{s}с"

async def auto_delete(message: Message, delay: int = AUTO_DELETE_DELAY):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass

async def reply_temp(message: Message, text: str, kb=None, delay: int = AUTO_DELETE_DELAY):
    """Отправляет сообщение, которое удалится через delay секунд."""
    msg = await message.answer(text, reply_markup=kb)
    asyncio.create_task(auto_delete(msg, delay))
    return msg

def share_url():
    if not BOT_USERNAME:
        return "https://t.me"
    txt = quote("Попробуй бота для анонимного общения! 🔥")
    return f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}&text={txt}"

# --- Клавиатуры ---
def kb_idle():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти собеседника", callback_data="find_partner")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile"),
         InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
        [InlineKeyboardButton(text="🔗 Поделиться ботом", url=share_url())],
    ])

def kb_searching():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить поиск", callback_data="cancel_search")]
    ])

def kb_in_chat():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛔ Остановить чат", callback_data="stop_chat")],
        [InlineKeyboardButton(text="⚠️ Пожаловаться", callback_data="report_user"),
         InlineKeyboardButton(text="🚫 Заблокировать", callback_data="block_user")],
    ])

# --- Логика ---
async def find_partner(user_id, message=None, callback=None):
    async def send(text, kb=None, temp=True):
        target = callback.message if callback else message
        if temp:
            await reply_temp(target, text, kb)
        else:
            await target.answer(text, reply_markup=kb)

    if is_banned(user_id):
        await send(f"🚫 Ты временно заблокирован.")
        return
    if user_id in pairs:
        await send("Ты уже в чате.", kb_in_chat(), temp=False)
        return
    if user_id in waiting_users:
        await send("Ты уже в очереди, ждём собеседника...", kb_searching())
        return

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
    await send("✅ Собеседник найден! Можешь писать.", kb_in_chat(), temp=False)
    try:
        await bot.send_message(partner, "✅ Собеседник найден! Можешь писать.", reply_markup=kb_in_chat())
    except Exception: pass

async def cancel_search(user_id, message=None, callback=None):
    target = callback.message if callback else message
    if user_id in waiting_users:
        waiting_users.remove(user_id)
        await reply_temp(target, "🚫 Поиск отменён.", kb_idle())
    else:
        await reply_temp(target, "Ты не в поиске.", kb_idle())

async def stop_chat(user_id, message=None, callback=None, notify=True):
    target = callback.message if callback else message
    partner = pairs.pop(user_id, None)
    if partner:
        pairs.pop(partner, None)
        if notify:
            try:
                await bot.send_message(partner, "❌ Собеседник вышел из чата.", reply_markup=kb_idle())
            except Exception: pass
        await reply_temp(target, "Ты вышел из чата.", kb_idle())
    else:
        if user_id in waiting_users: waiting_users.remove(user_id)
        await reply_temp(target, "Ты не в чате.", kb_idle())

async def report_user(user_id, callback):
    partner = pairs.get(user_id)
    if not partner:
        await reply_temp(callback.message, "Не на кого жаловаться.", kb_idle())
        return
    reports[partner] = reports.get(partner, 0) + 1
    get_stats(partner)['rep_recv'] += 1
    get_stats(user_id)['rep_given'] += 1
    count = reports[partner]
    reports_log.append((user_id, partner, time.time()))
    if len(reports_log) > 100:
        reports_log.pop(0)

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
        text = f"✅ Жалоба принята. Жалоб: {count}/{BAN_THRESHOLD}."
    await reply_temp(callback.message, text, kb_idle())

async def block_user(user_id, callback):
    partner = pairs.get(user_id)
    if not partner:
        await reply_temp(callback.message, "Некого блокировать.", kb_idle())
        return
    blacklist.setdefault(user_id, set()).add(partner)
    pairs.pop(user_id, None)
    pairs.pop(partner, None)
    try:
        await bot.send_message(partner, "❌ Собеседник завершил чат.", reply_markup=kb_idle())
    except Exception: pass
    await reply_temp(callback.message, "🚫 Пользователь в чёрном списке.", kb_idle())

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
    "🔍 <b>Найти собеседника</b> — ставит в очередь на поиск.\n"
    "❌ <b>Отменить поиск</b> — выйти из очереди.\n"
    "⛔ <b>Остановить чат</b> — разорвать диалог.\n"
    "⚠️ <b>Пожаловаться</b> — 3 жалобы = бан на час.\n"
    "🚫 <b>Заблокировать</b> — добавить в личный ЧС.\n"
    "👤 <b>Профиль</b> — твоя статистика.\n"
    "🔗 <b>Поделиться</b> — прислать бота другу.\n\n"
    "📎 Можно отправлять текст, фото, видео, голосовые, стикеры — всё пересылается собеседнику.\n\n"
    "💡 Подсказка: сервисные сообщения бота автоматически исчезают через 15 секунд."
)

ABOUT_TEXT = (
    "ℹ️ <b>О боте</b>\n\n"
    "«Тёплые Черви» — бот для анонимного общения.\n"
    "Соединяет двух случайных людей, чтобы они могли поболтать.\n\n"
    "🔒 Мы не собираем личные данные.\n"
    "⚡ Работает 24/7.\n\n"
    "Нашёл баг или есть идея — напиши разработчику: @твой_ник"
)

# --- Команды ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if is_banned(message.from_user.id):
        left = fmt_time(banned_until[message.from_user.id] - time.time())
        await message.answer(f"🚫 Ты заблокирован. Осталось: {left}")
        return
    get_stats(message.from_user.id)
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
        await message.answer("⛔ Только для админа.")
        return
    total_users = len(user_stats)
    in_queue = len(waiting_users)
    in_chats = len(pairs) // 2
    banned = len([u for u in banned_until if time.time() < banned_until[u]])
    total_chats = sum(s['chats'] for s in user_stats.values()) // 2
    uptime = fmt_time(time.time() - start_time)
    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"💬 Чатов создано: {total_chats}\n"
        f"🔎 В очереди: {in_queue}\n"
        f"💭 В чатах: {in_chats}\n"
        f"🚫 Забанено: {banned}\n"
        f"📋 Жалоб в логе: {len(reports_log)}\n"
        f"⏱ Аптайм: {uptime}"
    )
    await message.answer(text, parse_mode="HTML")

# --- Админ-панель ---
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Только для админа.")
        return
    text = (
        "🛠 <b>Админ-панель</b>\n\n"
        "<b>Команды:</b>\n"
        "📊 /stats — статистика\n"
        "📋 /reports — последние жалобы\n"
        "🚫 /ban &lt;id&gt; [причина] — забанить навсегда\n"
        "✅ /unban &lt;id&gt; — разбанить\n"
        "📢 /broadcast &lt;текст&gt; — рассылка всем пользователям\n\n"
        f"👥 Пользователей в базе: {len(user_stats)}"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Использование: /ban <id> [причина]")
        return
    try:
        target = int(parts[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    reason = parts[2] if len(parts) > 2 else "не указана"
    banned_until[target] = float('inf')
    reports[target] = 0
    await message.answer(f"🚫 Пользователь <code>{target}</code> забанен.\nПричина: {reason}", parse_mode="HTML")
    try:
        await bot.send_message(target, "🚫 Ты заблокирован администратором.")
    except Exception: pass

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /unban <id>")
        return
    try:
        target = int(parts[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    banned_until.pop(target, None)
    reports.pop(target, None)
    await message.answer(f"✅ Пользователь <code>{target}</code> разбанен.", parse_mode="HTML")
    try:
        await bot.send_message(target, "✅ Ты разбанен. Можешь снова пользоваться ботом.")
    except Exception: pass

@dp.message(Command("reports"))
async def cmd_reports(message: Message):
    if message.from_user.id != ADMIN_ID: return
    if not reports_log:
        await message.answer("📋 Жалоб пока нет.")
        return
    lines = ["📋 <b>Последние жалобы:</b>\n"]
    for rep, tgt, ts in reports_log[-10:]:
        when = time.strftime("%d.%m %H:%M", time.localtime(ts))
        lines.append(f"• <code>{rep}</code> → <code>{tgt}</code> ({when})")
    await message.answer("\n".join(lines), parse_mode="HTML")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /broadcast <текст>")
        return
    text = parts[1]
    ok, fail = 0, 0
    status = await message.answer(f"📢 Начинаю рассылку на {len(user_stats)} пользователей...")
    for uid in list(user_stats.keys()):
        try:
            await bot.send_message(uid, f"📢 <b>Сообщение от админа:</b>\n\n{text}", parse_mode="HTML")
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await status.edit_text(f"✅ Рассылка завершена.\nДоставлено: {ok}\nОшибок: {fail}")

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

# --- Пересылка ---
@dp.message()
async def relay_message(message: Message):
    uid = message.from_user.id
    get_stats(uid)
    if is_banned(uid):
        left = fmt_time(banned_until[uid] - time.time())
        await reply_temp(message, f"🚫 Ты заблокирован. Осталось: {left}")
        return
    partner = pairs.get(uid)
    if partner:
        try:
            await message.copy_to(chat_id=partner)
        except Exception as e:
            await reply_temp(message, "⚠️ Не удалось отправить сообщение.")
            logging.error(f"Ошибка пересылки: {e}")
    else:
        await reply_temp(message, "Ты не в чате. Нажми кнопку ниже.", kb_idle())

async def main():
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username
    logging.info(f"Бот запущен: @{BOT_USERNAME}")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
