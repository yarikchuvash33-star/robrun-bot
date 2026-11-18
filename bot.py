import os
import io
import asyncio
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, BufferedInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton
)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
FUNPAY_URL = os.getenv("FUNPAY_URL", "https://funpay.com/lots/offer?id=82465245")

# НАСТРОЙКИ ЦЕН
PRICE_PER_VIRT = 0.00117 # Базовая цена за 1 вирт
DISCOUNT_PERCENT = 0.20  # Скидка 20% на своих серверах

if not TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN в Render Environment")

bot = Bot(token=TOKEN)
dp = Dispatcher()

DB = "orders.db"
users = {}

SERVICES = {
    "raid": "Сопровождение 2 читеров на рейд",
    "hangar": "Сопровождение 2 читеров на продажу в ангаре"
}

def db():
    return sqlite3.connect(DB)

def init_db():
    with db() as con:
        # Заказы
        con.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                order_type TEXT,
                amount REAL,
                server TEXT,
                price REAL,
                status TEXT DEFAULT 'Новый',
                created_at TEXT
            )
        """)
        # Пользователи (для банов)
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                is_banned INTEGER DEFAULT 0
            )
        """)
        # Мои сервера (где скидка)
        con.execute("""
            CREATE TABLE IF NOT EXISTS my_servers (
                name TEXT PRIMARY KEY
            )
        """)

def is_admin(user_id):
    return user_id == ADMIN_ID

def is_banned(user_id):
    with db() as con:
        row = con.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,)).fetchone()
        return row[0] == 1 if row else False

def get_price(amount_mln, server_name):
    """Считает цену. amount_mln - количество в миллионах (например 1.5)"""
    virt_count = float(amount_mln) * 1_000_000
    base_price = virt_count * PRICE_PER_VIRT
    
    # Проверяем, есть ли сервер в списке счастливых
    with db() as con:
        is_my = con.execute("SELECT 1 FROM my_servers WHERE LOWER(name)=?", (server_name.lower(),)).fetchone()
    
    if is_my:
        return base_price * (1 - DISCOUNT_PERCENT)
    return base_price

def register_user(user):
    with db() as con:
        con.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user.id, user.username or ""))
        con.execute("UPDATE users SET username=? WHERE user_id=?", (user.username or "", user.id))

# ================= КЛАВИАТУРЫ =================

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Купить вирты", callback_data="buy")],
        [InlineKeyboardButton(text="🛠 Услуги", callback_data="services")],
        [InlineKeyboardButton(text="🌐 Мои сервера", callback_data="my_servers_list")],
        [InlineKeyboardButton(text="📦 Мои заказы", callback_data="history")]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="📋 Заказы", callback_data="adm:orders:0")],
        [InlineKeyboardButton(text="🌐 Сервера", callback_data="adm:servers")],
        [InlineKeyboardButton(text="👥 Юзеры / Баны", callback_data="adm:users")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast")],
    ])

def amount_menu():
    values = [("500 тыс.", 0.5), ("1 млн", 1), ("1,5 млн", 1.5), ("2 млн", 2),
              ("2,5 млн", 2.5), ("3 млн", 3), ("3,5 млн", 3.5), ("4 млн", 4),
              ("4,5 млн", 4.5), ("5 млн", 5)]
    buttons = []
    for i in range(0, len(values), 2):
        buttons.append([
            InlineKeyboardButton(text=values[i][0], callback_data=f"amount:{values[i][1]}"),
            InlineKeyboardButton(text=values[i+1][0], callback_data=f"amount:{values[i+1][1]}")
        ])
    buttons.append([InlineKeyboardButton(text="✏️ Ввести количество вручную", callback_data="manual")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def format_amount(value):
    number = Decimal(str(value))
    if number == number.to_integral_value():
        return f"{int(number)} млн"
    return f"{str(number).replace('.', ',')} млн"

# ================= КОМАНДЫ =================

@dp.message(CommandStart())
async def start(message: Message):
    register_user(message.from_user)
    if is_banned(message.from_user.id):
        return await message.answer("🚫 Вы забанены в этом боте.")
    users.pop(message.from_user.id, None)
    await message.answer(
        "🌑 <b>ROBRUN SHOP</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Добро пожаловать в магазин!\n\n"
        "💎 Покупай вирты и заказывай услуги.\n"
        "📦 Следи за своими заказами в истории.\n\n"
        "Выбери нужный раздел:",
        reply_markup=main_menu(), parse_mode="HTML")

@dp.message(Command("info"))
async def info_cmd(message: Message):
    await message.answer(
        "📖 <b>Информация о ROBRUN SHOP</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Мы предлагаем услуги для игры Rob Run:\n\n"
        "💰 <b>Вирты</b> — от 500 тыс. до 5 млн.\n"
        f"• Базовая цена: <b>{PRICE_PER_VIRT} ₽</b> за 1 вирт.\n"
        f"• На серверах из списка «🌐 Мои сервера» — скидка <b>{int(DISCOUNT_PERCENT*100)}%</b>.\n\n"
        "⚔️ <b>Услуги</b>:\n"
        "• Сопровождение на рейд (2 читера).\n"
        "• Сопровождение в ангар (2 читера).\n\n"
        "🛡 <b>Гарантии:</b>\n"
        "Все сделки проходят ТОЛЬКО через FunPay. Это безопасно и защищает покупателя.\n\n"
        "🎁 <b>Бонусы:</b>\n"
        "Каждый 5-й заказ — скидка 10%.\n\n"
        "👉 Для покупки нажми /start",
        parse_mode="HTML")

@dp.message(Command("cancel"))
async def stop_input(message: Message):
    users.pop(message.from_user.id, None)
    await message.answer("Ввод отменён. Возвращаемся в меню.", reply_markup=main_menu())

# ================= АДМИНКА =================

@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if not is_admin(message.from_user.id): return
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_menu(), parse_mode="HTML")

@dp.message(Command("backup"))
async def backup_cmd(message: Message):
    if not is_admin(message.from_user.id): return
    with db() as con:
        rows = con.execute("SELECT id, user_id, username, order_type, amount, server, status, created_at FROM orders ORDER BY id").fetchall()
    if not rows: return await message.answer("Заказов нет.")
    buf = io.StringIO()
    buf.write("id,user_id,username,order_type,amount,server,status,created_at\n")
    for r in rows: buf.write(",".join(str(x).replace(",", ";") for x in r) + "\n")
    buf.seek(0)
    file = BufferedInputFile(buf.read().encode(), filename="orders_backup.csv")
    await message.answer_document(file, caption=f"📦 Бэкап, {len(rows)} заказов")

@dp.callback_query(F.data == "adm:stats")
async def adm_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id): return await call.answer("Нет доступа", show_alert=True)
    with db() as con:
        total = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        new = con.execute("SELECT COUNT(*) FROM orders WHERE status='Новый'").fetchone()[0]
        done = con.execute("SELECT COUNT(*) FROM orders WHERE status='Выполнен'").fetchone()[0]
        usr_cnt = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        banned = con.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
    text = (f"📊 <b>СТАТИСТИКА</b>\n━━━━━━━━━━━━━━\n"
            f"👥 Юзеров: <b>{usr_cnt}</b> (забанено: {banned})\n"
            f"🧾 Заказов: <b>{total}</b>\n🟡 Новых: <b>{new}</b>\n🟢 Выполнено: <b>{done}</b>")
    await call.message.answer(text, parse_mode="HTML", reply_markup=admin_menu())
    await call.answer()

@dp.callback_query(F.data.startswith("adm:orders:"))
async def adm_orders(call: CallbackQuery):
    if not is_admin(call.from_user.id): return await call.answer("Нет доступа", show_alert=True)
    with db() as con:
        rows = con.execute("SELECT id, username, order_type, status FROM orders ORDER BY id DESC LIMIT 10").fetchall()
    if not rows: return await call.answer("Заказов нет", show_alert=True)
    kb = []
    for oid, uname, kind, st in rows:
        e = {"Новый": "🟡", "Выполнен": "🟢", "Отменён": "🔴"}.get(st, "⚪")
        kb.append([InlineKeyboardButton(text=f"{e} #{oid} @{uname or '—'} — {kind[:15]}", callback_data=f"adm:order:{oid}")])
    kb.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="adm:menu")])
    await call.message.answer("📋 <b>Заказы</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("adm:order:"))
async def adm_order_view(call: CallbackQuery):
    if not is_admin(call.from_user.id): return await call.answer("Нет доступа", show_alert=True)
    oid = int(call.data.split(":")[2])
    with db() as con:
        row = con.execute("SELECT user_id, username, order_type, amount, server, status, created_at, price FROM orders WHERE id=?", (oid,)).fetchone()
    if not row: return await call.answer("Не найден", show_alert=True)
    uid, uname, kind, amt, srv, st, date, price = row
    text = (f"🧾 <b>Заказ #{oid}</b>\n👤 @{uname or '—'} (<code>{uid}</code>)\n"
            f"📌 {kind}\n💰 {amt or '—'}\n🌐 {srv}\n💵 Сумма: {price:.2f} ₽\n📅 {date}\n📊 <b>{st}</b>")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 В работе", callback_data=f"adm:st:{oid}:В работе")],
        [InlineKeyboardButton(text="✅ Выполнен", callback_data=f"adm:st:{oid}:Выполнен")],
        [InlineKeyboardButton(text="❌ Отменён", callback_data=f"adm:st:{oid}:Отменён")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:orders:0")],
    ])
    await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("adm:st:"))
async def adm_set_status(call: CallbackQuery):
    if not is_admin(call.from_user.id): return await call.answer("Нет доступа", show_alert=True)
    _, _, oid, new_st = call.data.split(":")
    oid = int(oid)
    with db() as con:
        con.execute("UPDATE orders SET status=? WHERE id=?", (new_st, oid))
        row = con.execute("SELECT user_id, order_type, server FROM orders WHERE id=?", (oid,)).fetchone()
    if row:
        uid, kind, srv = row
        try:
            await bot.send_message(uid, f"📢 <b>Статус заказа #{oid} изменён</b>\n\n📌 {kind}\n🌐 {srv}\n\nНовый статус: <b>{new_st}</b>", parse_mode="HTML")
        except Exception: pass
    await call.answer(f"Статус: {new_st}", show_alert=True)

@dp.callback_query(F.data == "adm:menu")
async def adm_back(call: CallbackQuery):
    if not is_admin(call.from_user.id): return await call.answer()
    await call.message.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_menu(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "adm:broadcast")
async def adm_broadcast(call: CallbackQuery):
    if not is_admin(call.from_user.id): return await call.answer("Нет доступа", show_alert=True)
    users[call.from_user.id] = {"step": "adm_broadcast"}
    await call.message.answer("📢 Отправь текст для рассылки. Отмена: /cancel")
    await call.answer()

# --- УПРАВЛЕНИЕ СЕРВЕРАМИ В АДМИНКЕ ---

@dp.callback_query(F.data == "adm:servers")
async def adm_servers(call: CallbackQuery):
    if not is_admin(call.from_user.id): return await call.answer("Нет доступа", show_alert=True)
    with db() as con:
        servers = con.execute("SELECT name FROM my_servers").fetchall()
    text = "🌐 <b>Твои сервера со скидкой</b>\n\n"
    if not servers:
        text += "Пока пусто. Добавь первый!"
    else:
        for s in servers: text += f"• {s[0]}\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить сервер", callback_data="adm:addserver")],
        [InlineKeyboardButton(text="🗑 Удалить сервер", callback_data="adm:delserver")],
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="adm:menu")],
    ])
    await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "adm:addserver")
async def adm_addserver(call: CallbackQuery):
    if not is_admin(call.from_user.id): return await call.answer("Нет доступа", show_alert=True)
    users[call.from_user.id] = {"step": "adm_addserver"}
    await call.message.answer("Напиши название сервера, который нужно добавить (например: <code>MyBestServer</code>):", parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "adm:delserver")
async def adm_delserver(call: CallbackQuery):
    if not is_admin(call.from_user.id): return await call.answer("Нет доступа", show_alert=True)
    with db() as con:
        servers = con.execute("SELECT name FROM my_servers").fetchall()
    if not servers: return await call.answer("Серверов нет", show_alert=True)
    kb = []
    for s in servers:
        kb.append([InlineKeyboardButton(text=f"❌ {s[0]}", callback_data=f"adm:del:{s[0]}")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:servers")])
    await call.message.answer("Выбери сервер для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@dp.callback_query(F.data.startswith("adm:del:"))
async def adm_del_do(call: CallbackQuery):
    if not is_admin(call.from_user.id): return await call.answer("Нет доступа", show_alert=True)
    srv = call.data.split(":")[2]
    with db() as con:
        con.execute("DELETE FROM my_servers WHERE name=?", (srv,))
    await call.answer(f"Удалён: {srv}", show_alert=True)
    # Перерисовываем меню серверов
    await adm_servers(call)

# --- УПРАВЛЕНИЕ ЮЗЕРАМИ / БАНАМИ ---

@dp.callback_query(F.data == "adm:users")
async def adm_users(call: CallbackQuery):
    if not is_admin(call.from_user.id): return await call.answer("Нет доступа", show_alert=True)
    with db() as con:
        users_rows = con.execute("SELECT user_id, username, is_banned FROM users ORDER BY user_id DESC LIMIT 20").fetchall()
    
    kb = []
    for uid, uname, banned in users_rows:
        mark = "🚫" if banned else "✅"
        kb.append([InlineKeyboardButton(text=f"{mark} @{uname or '—'} ({uid})", callback_data=f"adm:user:{uid}")])
    kb.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="adm:menu")])
    
    await call.message.answer("👥 <b>Пользователи (последние 20)</b>\nНажми на юзера, чтобы забанить/разбанить:", 
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("adm:user:"))
async def adm_user_view(call: CallbackQuery):
    if not is_admin(call.from_user.id): return await call.answer("Нет доступа", show_alert=True)
    uid = int(call.data.split(":")[2])
    with db() as con:
        row = con.execute("SELECT username, is_banned FROM users WHERE user_id=?", (uid,)).fetchone()
        orders_cnt = con.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (uid,)).fetchone()[0]
    
    if not row: return await call.answer("Не найден", show_alert=True)
    uname, banned = row
    status = "🚫 Забанен" if banned else "✅ Активен"
    
    text = (f"👤 <b>Юзер</b>\nID: <code>{uid}</code>\nUsername: @{uname or '—'}\n"
            f"Статус: {status}\nЗаказов: {orders_cnt}")
    
    btn_text = "✅ Разбанить" if banned else "🚫 Забанить"
    action = "unban" if banned else "ban"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn_text, callback_data=f"adm:ban:{action}:{uid}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:users")],
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("adm:ban:"))
async def adm_ban_action(call: CallbackQuery):
    if not is_admin(call.from_user.id): return await call.answer("Нет доступа", show_alert=True)
    _, _, action, uid = call.data.split(":")
    uid = int(uid)
    val = 1 if action == "ban" else 0
    
    with db() as con:
        con.execute("UPDATE users SET is_banned=? WHERE user_id=?", (val, uid))
        
    await call.answer("Готово!", show_alert=True)
    # Возвращаемся в карточку
    call.data = f"adm:user:{uid}"
    await adm_user_view(call)

# ================= КЛИЕНТСКАЯ ЧАСТЬ =================

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    users.pop(call.from_user.id, None)
    await call.message.answer("🏠 <b>Главное меню</b>", reply_markup=main_menu(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "buy")
async def buy(call: CallbackQuery):
    if is_banned(call.from_user.id): return await call.answer("Вы забанены.", show_alert=True)
    users[call.from_user.id] = {"step": "amount"}
    await call.message.answer(
        "💰 <b>ПОКУПКА ВИРТОВ</b>\n\n"
        f"Базовая цена: <b>{PRICE_PER_VIRT} ₽</b> за 1 вирт.\n"
        f"На серверах из списка «🌐 Мои сервера» — скидка <b>{int(DISCOUNT_PERCENT*100)}%</b>.\n\n"
        "Выбери количество:",
        reply_markup=amount_menu(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("amount:"))
async def choose_amount(call: CallbackQuery):
    amount = float(call.data.split(":")[1])
    users[call.from_user.id] = {"step": "server", "type": "Вирты", "amount": amount}
    
    base_price = get_price(amount, "")
    text = (f"✅ Выбрано: <b>{format_amount(amount)}</b>\n"
            f"💰 Примерная цена: <b>{base_price:.2f} ₽</b> (без скидки)\n\n"
            "🌐 Напиши название своего сервера.\n"
            f"<i>(Если он в списке счастливых — цена уменьшится на {int(DISCOUNT_PERCENT*100)}%)</i>")
    await call.message.answer(text, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "manual")
async def manual(call: CallbackQuery):
    users[call.from_user.id] = {"step": "manual"}
    await call.message.answer("✏️ <b>ВВЕДИ КОЛИЧЕСТВО</b>\n\nМинимум: 500 000\nМаксимум: 5 000 000\n\nНапример: 1,5", parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "my_servers_list")
async def my_servers_list(call: CallbackQuery):
    with db() as con:
        servers = con.execute("SELECT name FROM my_servers").fetchall()
    
    if not servers:
        await call.message.answer("🌐 Пока нет серверов со скидкой. Следи за обновлениями!", reply_markup=main_menu())
    else:
        text = "🌐 <b>Сервера со скидкой</b>\n\nНа этих серверах цена виртов ниже на " + f"{int(DISCOUNT_PERCENT*100)}%:\n\n"
        for s in servers: text += f"• {s[0]}\n"
        await call.message.answer(text, reply_markup=main_menu(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "services")
async def services(call: CallbackQuery):
    if is_banned(call.from_user.id): return await call.answer("Вы забанены.", show_alert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Сопровождение на рейд", callback_data="service:raid")],
        [InlineKeyboardButton(text="🏠 Сопровождение в ангар", callback_data="service:hangar")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="home")],
    ])
    await call.message.answer("🛠 <b>ВЫБЕРИ УСЛУГУ</b>", reply_markup=kb, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("service:"))
async def choose_service(call: CallbackQuery):
    key = call.data.split(":")[1]
    users[call.from_user.id] = {"step": "server", "type": SERVICES[key], "amount": None}
    await call.message.answer("🌐 Напиши название своего сервера:")
    await call.answer()

@dp.callback_query(F.data == "history")
async def history(call: CallbackQuery):
    with db() as con:
        rows = con.execute("SELECT id, order_type, amount, server, status, created_at, price FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 10", (call.from_user.id,)).fetchall()
    if not rows:
        return await call.message.answer("📦 У тебя пока нет заказов.", reply_markup=main_menu())
    
    text = "📦 <b>ТВОИ ПОСЛЕДНИЕ ЗАКАЗЫ</b>\n"
    for oid, kind, amount, server, status, date, price in rows:
        text += f"\n━━━━━━━━━━━━━━\n🧾 Заказ #{oid}\n📌 {kind}\n"
        if amount is not None: text += f"💰 {format_amount(amount)}\n"
        if price: text += f"💵 Сумма: {price:.2f} ₽\n"
        text += f"🌐 Сервер: {server}\n📅 {date}\nСтатус: {status}\n"
    await call.message.answer(text, reply_markup=main_menu(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_order(call: CallbackQuery):
    order_id = int(call.data.split(":")[1])
    with db() as con:
        row = con.execute("SELECT status FROM orders WHERE id = ? AND user_id = ?", (order_id, call.from_user.id)).fetchone()
        if not row: return await call.answer("Заказ не найден.", show_alert=True)
        if row[0] == "Отменён": return await call.answer("Заказ уже отменён.", show_alert=True)
        con.execute("UPDATE orders SET status = 'Отменён' WHERE id = ?", (order_id,))
    await call.message.answer(f"❌ Заказ #{order_id} отменён.")
    if ADMIN_ID:
        try:
            await bot.send_message(ADMIN_ID, f"❌ <b>ЗАКАЗ ОТМЕНЁН</b>\nНомер: #{order_id}\nПользователь: @{call.from_user.username or 'без username'}", parse_mode="HTML")
        except Exception: pass
    await call.answer("Заказ отменён")

# ================= ОБРАБОТЧИК ТЕКСТА =================

@dp.message(F.text)
async def text_handler(message: Message):
    if is_banned(message.from_user.id):
        return
    data = users.get(message.from_user.id)
    if not data: return

    value = message.text.strip()

    # --- АДМИН ВВОД ---
    if data.get("step") == "adm_broadcast":
        if not is_admin(message.from_user.id): return
        with db() as con: ids = [r[0] for r in con.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()]
        ok = fail = 0
        for uid in ids:
            try:
                await bot.send_message(uid, message.text)
                ok += 1
            except Exception: fail += 1
            await asyncio.sleep(0.05)
        users.pop(message.from_user.id, None)
        return await message.answer(f"✅ Отправлено: {ok}\n❌ Ошибок: {fail}")

    if data.get("step") == "adm_addserver":
        if not is_admin(message.from_user.id): return
        with db() as con:
            con.execute("INSERT OR IGNORE INTO my_servers (name) VALUES (?)", (value,))
        users.pop(message.from_user.id, None)
        return await message.answer(f"✅ Сервер <b>{value}</b> добавлен со скидкой!", parse_mode="HTML")

    # --- КЛИЕНТ ВВОД ---
    if data["step"] == "manual":
        try:
            raw = value.lower().replace("млн", "").replace(" ", "").replace(",", ".")
            amount = Decimal(raw)
            if amount >= 500000: amount = amount / Decimal("1000000")
            if amount < Decimal("0.5") or amount > Decimal("5"): raise ValueError()
            amount = float(amount)
        except (InvalidOperation, ValueError):
            return await message.answer("❌ Неверное количество.\nВведи от 0,5 до 5 млн. Например: 1,5")

        data["amount"] = amount
        data["step"] = "server"
        return await message.answer(f"✅ Выбрано: <b>{format_amount(amount)}</b>\n\n🌐 Теперь напиши название своего сервера:", parse_mode="HTML")

    if data["step"] == "server":
        if len(value) < 1 or len(value) > 80:
            return await message.answer("❌ Напиши название сервера короче 80 символов.")
        
        order_type = data["type"]
        amount = data.get("amount")
        
        # Расчет цены
        price = get_price(amount, value) if amount is not None else 0.0
        
        with db() as con:
            cur = con.execute("INSERT INTO orders (user_id, username, order_type, amount, server, price, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (message.from_user.id, message.from_user.username or "", order_type, amount, value, price, datetime.now().strftime("%d.%m.%Y %H:%M")))
            order_id = cur.lastrowid

        details = f"🧾 <b>ЗАКАЗ #{order_id}</b>\n━━━━━━━━━━━━━━━━━━\n📌 {order_type}\n"
        if amount is not None:
            details += f"💰 Количество: {format_amount(amount)}\n"
            details += f"💵 Сумма: <b>{price:.2f} ₽</b>\n"
        details += f"🌐 Сервер: {value}\n📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n🟡 Статус: Новый"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"cancel:{order_id}")],
            [InlineKeyboardButton(text="🛒 Перейти на FunPay", url=FUNPAY_URL)],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")]
        ])

        await message.answer("✅ <b>ЗАКАЗ СОЗДАН!</b>\n\n" + details + "\n\nДля завершения покупки перейди на FunPay.", reply_markup=kb, parse_mode="HTML")

        if ADMIN_ID:
            try:
                await bot.send_message(ADMIN_ID, "🔔 <b>НОВЫЙ ЗАКАЗ!</b>\n\n" + details + f"\n\n👤 @{message.from_user.username or 'без username'}\n🆔 {message.from_user.id}", parse_mode="HTML")
            except Exception: pass

        users.pop(message.from_user.id, None)

# ================= ЗАПУСК =================

async def health(request):
    return web.Response(text="ROBRUN SHOP is running!")

async def main():
    init_db()
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
