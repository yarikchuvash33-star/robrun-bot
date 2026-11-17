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
FUNPAY_URL = os.getenv(
    "FUNPAY_URL",
    "https://funpay.com/lots/offer?id=82465245"
)

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
        con.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                order_type TEXT,
                amount REAL,
                server TEXT,
                status TEXT DEFAULT 'Новый',
                created_at TEXT
            )
        """)


def is_admin(user_id):
    return user_id == ADMIN_ID


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💰 Купить вирты", callback_data="buy"
        )],
        [InlineKeyboardButton(
            text="🛠 Услуги", callback_data="services"
        )],
        [InlineKeyboardButton(
            text="📦 Мои заказы", callback_data="history"
        )]
    ])


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="📋 Заказы", callback_data="adm:orders:0")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast")],
    ])


def amount_menu():
    values = [
        ("500 тыс.", 0.5),
        ("1 млн", 1),
        ("1,5 млн", 1.5),
        ("2 млн", 2),
        ("2,5 млн", 2.5),
        ("3 млн", 3),
        ("3,5 млн", 3.5),
        ("4 млн", 4),
        ("4,5 млн", 4.5),
        ("5 млн", 5)
    ]

    buttons = []
    for i in range(0, len(values), 2):
        buttons.append([
            InlineKeyboardButton(
                text=values[i][0],
                callback_data=f"amount:{values[i][1]}"
            ),
            InlineKeyboardButton(
                text=values[i + 1][0],
                callback_data=f"amount:{values[i + 1][1]}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="✏️ Ввести количество вручную",
            callback_data="manual"
        )
    ])
    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад", callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_amount(value):
    number = Decimal(str(value))
    if number == number.to_integral_value():
        return f"{int(number)} млн"
    return f"{str(number).replace('.', ',')} млн"


def create_order(user, order_type, amount, server):
    with db() as con:
        cur = con.execute("""
            INSERT INTO orders
            (user_id, username, order_type, amount, server, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            order_type,
            amount,
            server,
            datetime.now().strftime("%d.%m.%Y %H:%M")
        ))
        return cur.lastrowid


def order_keyboard(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ Отменить заказ",
            callback_data=f"cancel:{order_id}"
        )],
        [InlineKeyboardButton(
            text="🛒 Перейти на FunPay",
            url=FUNPAY_URL
        )],
        [InlineKeyboardButton(
            text="🏠 Главное меню", callback_data="home"
        )]
    ])


@dp.message(CommandStart())
async def start(message: Message):
    users.pop(message.from_user.id, None)
    await message.answer(
        "🌑 <b>ROBRUN SHOP</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Добро пожаловать в магазин!\n\n"
        "💎 Покупай вирты и заказывай услуги.\n"
        "📦 Следи за своими заказами в истории.\n\n"
        "Выбери нужный раздел:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


@dp.message(Command("cancel"))
async def stop_input(message: Message):
    users.pop(message.from_user.id, None)
    await message.answer(
        "Ввод отменён. Возвращаемся в меню.",
        reply_markup=main_menu()
    )


# ============ АДМИНКА ============

@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_menu(), parse_mode="HTML")


@dp.message(Command("backup"))
async def backup_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    with db() as con:
        rows = con.execute("""
            SELECT id, user_id, username, order_type, amount, server, status, created_at
            FROM orders ORDER BY id
        """).fetchall()
    if not rows:
        return await message.answer("Заказов нет.")
    buf = io.StringIO()
    buf.write("id,user_id,username,order_type,amount,server,status,created_at\n")
    for r in rows:
        buf.write(",".join(str(x).replace(",", ";") for x in r) + "\n")
    buf.seek(0)
    file = BufferedInputFile(buf.read().encode(), filename="orders_backup.csv")
    await message.answer_document(file, caption=f"📦 Бэкап, {len(rows)} заказов")


@dp.callback_query(F.data == "adm:stats")
async def adm_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    with db() as con:
        total = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        new = con.execute("SELECT COUNT(*) FROM orders WHERE status='Новый'").fetchone()[0]
        done = con.execute("SELECT COUNT(*) FROM orders WHERE status='Выполнен'").fetchone()[0]
        cancelled = con.execute("SELECT COUNT(*) FROM orders WHERE status='Отменён'").fetchone()[0]
    text = (
        "📊 <b>СТАТИСТИКА</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"🧾 Всего заказов: <b>{total}</b>\n"
        f"🟡 Новых: <b>{new}</b>\n"
        f"🟢 Выполнено: <b>{done}</b>\n"
        f"🔴 Отменено: <b>{cancelled}</b>"
    )
    await call.message.answer(text, parse_mode="HTML", reply_markup=admin_menu())
    await call.answer()


@dp.callback_query(F.data.startswith("adm:orders:"))
async def adm_orders(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    with db() as con:
        rows = con.execute("""
            SELECT id, username, order_type, status
            FROM orders ORDER BY id DESC LIMIT 10
        """).fetchall()
    if not rows:
        return await call.answer("Заказов нет", show_alert=True)
    kb = []
    for oid, uname, kind, st in rows:
        e = {"Новый": "🟡", "Выполнен": "🟢", "Отменён": "🔴"}.get(st, "⚪")
        kb.append([InlineKeyboardButton(
            text=f"{e} #{oid} @{uname or '—'} — {kind[:20]}",
            callback_data=f"adm:order:{oid}"
        )])
    kb.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="adm:menu")])
    await call.message.answer(
        "📋 <b>Заказы</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="HTML"
    )
    await call.answer()


@dp.callback_query(F.data.startswith("adm:order:"))
async def adm_order_view(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    oid = int(call.data.split(":")[2])
    with db() as con:
        row = con.execute("""
            SELECT user_id, username, order_type, amount, server, status, created_at
            FROM orders WHERE id=?
        """, (oid,)).fetchone()
    if not row:
        return await call.answer("Не найден", show_alert=True)
    uid, uname, kind, amt, srv, st, date = row
    text = (
        f"🧾 <b>Заказ #{oid}</b>\n"
        f"👤 @{uname or '—'} (<code>{uid}</code>)\n"
        f"📌 {kind}\n"
        f"💰 {amt or '—'}\n"
        f"🌐 {srv}\n"
        f"📅 {date}\n"
        f"📊 Статус: <b>{st}</b>"
    )
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
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    _, _, oid, new_st = call.data.split(":")
    oid = int(oid)
    with db() as con:
        con.execute("UPDATE orders SET status=? WHERE id=?", (new_st, oid))
        row = con.execute("SELECT user_id, order_type, server FROM orders WHERE id=?", (oid,)).fetchone()
    if row:
        uid, kind, srv = row
        try:
            await bot.send_message(
                uid,
                f"📢 <b>Статус заказа #{oid} изменён</b>\n\n"
                f"📌 {kind}\n🌐 {srv}\n\n"
                f"Новый статус: <b>{new_st}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
    await call.answer(f"Статус: {new_st}", show_alert=True)


@dp.callback_query(F.data == "adm:menu")
async def adm_back(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    await call.message.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_menu(), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "adm:broadcast")
async def adm_broadcast(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    users[call.from_user.id] = {"step": "adm_broadcast"}
    await call.message.answer("📢 Отправь текст для рассылки. Отмена: /cancel")
    await call.answer()

# ============ КОНЕЦ АДМИНКИ ============


@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    users.pop(call.from_user.id, None)
    await call.message.answer(
        "🏠 <b>Главное меню</b>",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@dp.callback_query(F.data == "buy")
async def buy(call: CallbackQuery):
    users[call.from_user.id] = {"step": "amount"}
    await call.message.answer(
        "💰 <b>ПОКУПКА ВИРТОВ</b>\n\n"
        "Выбери количество от 500 тысяч до 5 миллионов "
        "или введи своё число.",
        reply_markup=amount_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@dp.callback_query(F.data.startswith("amount:"))
async def choose_amount(call: CallbackQuery):
    amount = float(call.data.split(":")[1])
    users[call.from_user.id] = {
        "step": "server",
        "type": "Вирты",
        "amount": amount
    }
    await call.message.answer(
        f"✅ Выбрано: <b>{format_amount(amount)}</b>\n\n"
        "🌐 Теперь напиши название своего сервера:",
        parse_mode="HTML"
    )
    await call.answer()


@dp.callback_query(F.data == "manual")
async def manual(call: CallbackQuery):
    users[call.from_user.id] = {"step": "manual"}
    await call.message.answer(
        "✏️ <b>ВВЕДИ КОЛИЧЕСТВО</b>\n\n"
        "Минимум: 500 000\n"
        "Максимум: 5 000 000\n\n"
        "Можно написать, например:\n"
        "• 1,5\n"
        "• 2,7\n"
        "• 500000\n\n"
        "Дробное число указывай в миллионах.",
        parse_mode="HTML"
    )
    await call.answer()


@dp.callback_query(F.data == "services")
async def services(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚔️ Сопровождение на рейд",
            callback_data="service:raid"
        )],
        [InlineKeyboardButton(
            text="🏠 Сопровождение на продажу в ангаре",
            callback_data="service:hangar"
        )],
        [InlineKeyboardButton(
            text="⬅️ Назад", callback_data="home"
        )]
    ])
    await call.message.answer(
        "🛠 <b>ВЫБЕРИ УСЛУГУ</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()


@dp.callback_query(F.data.startswith("service:"))
async def choose_service(call: CallbackQuery):
    key = call.data.split(":")[1]
    users[call.from_user.id] = {
        "step": "server",
        "type": SERVICES[key],
        "amount": None
    }
    await call.message.answer(
        "🌐 Напиши название своего сервера:"
    )
    await call.answer()


@dp.callback_query(F.data == "history")
async def history(call: CallbackQuery):
    with db() as con:
        rows = con.execute("""
            SELECT id, order_type, amount, server, status, created_at
            FROM orders
            WHERE user_id = ?
            ORDER BY id DESC LIMIT 10
        """, (call.from_user.id,)).fetchall()

    if not rows:
        await call.message.answer(
            "📦 У тебя пока нет заказов.",
            reply_markup=main_menu()
        )
        await call.answer()
        return

    text = "📦 <b>ТВОИ ПОСЛЕДНИЕ ЗАКАЗЫ</b>\n"
    for row in rows:
        order_id, kind, amount, server, status, date = row
        text += (
            f"\n━━━━━━━━━━━━━━\n"
            f"🧾 Заказ #{order_id}\n"
            f"📌 {kind}\n"
        )
        if amount is not None:
            text += f"💰 {format_amount(amount)}\n"
        text += (
            f"🌐 Сервер: {server}\n"
            f"📅 {date}\n"
            f"Статус: {status}\n"
        )

    await call.message.answer(
        text,
        reply_markup=main_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_order(call: CallbackQuery):
    order_id = int(call.data.split(":")[1])

    with db() as con:
        row = con.execute("""
            SELECT order_type, amount, server, status
            FROM orders
            WHERE id = ? AND user_id = ?
        """, (order_id, call.from_user.id)).fetchone()

        if not row:
            await call.answer("Заказ не найден.", show_alert=True)
            return

        if row[3] == "Отменён":
            await call.answer("Заказ уже отменён.", show_alert=True)
            return

        con.execute(
            "UPDATE orders SET status = 'Отменён' WHERE id = ?",
            (order_id,)
        )

    await call.message.answer(
        f"❌ Заказ #{order_id} отменён."
    )

    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"❌ <b>ЗАКАЗ ОТМЕНЁН</b>\n"
                f"Номер: #{order_id}\n"
                f"Пользователь: @{call.from_user.username or 'без username'}\n"
                f"ID: {call.from_user.id}",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await call.answer("Заказ отменён")


@dp.message(F.text)
async def text_handler(message: Message):
    data = users.get(message.from_user.id)
    if not data:
        return

    value = message.text.strip()

    if data["step"] == "adm_broadcast":
        if not is_admin(message.from_user.id):
            return
        with db() as con:
            ids = [r[0] for r in con.execute("SELECT DISTINCT user_id FROM orders").fetchall()]
        ok = fail = 0
        for uid in ids:
            try:
                await bot.send_message(uid, message.text)
                ok += 1
            except Exception:
                fail += 1
            await asyncio.sleep(0.05)
        users.pop(message.from_user.id, None)
        await message.answer(f"✅ Отправлено: {ok}\n❌ Ошибок: {fail}")
        return

    if data["step"] == "manual":
        try:
            raw = value.lower().replace("млн", "").replace(" ", "")
            raw = raw.replace(",", ".")
            amount = Decimal(raw)

            if amount >= 500000:
                amount = amount / Decimal("1000000")

            if amount < Decimal("0.5") or amount > Decimal("5"):
                raise ValueError()

            amount = float(amount)

        except (InvalidOperation, ValueError):
            await message.answer(
                "❌ Неверное количество.\n"
                "Введи число от 0,5 до 5 миллионов.\n"
                "Например: 1,5"
            )
            return

        data["amount"] = amount
        data["step"] = "server"
        await message.answer(
            f"✅ Выбрано: <b>{format_amount(amount)}</b>\n\n"
            "🌐 Теперь напиши название своего сервера:",
            parse_mode="HTML"
        )
        return

    if data["step"] == "server":
        if len(value) < 1 or len(value) > 80:
            await message.answer("❌ Напиши название сервера короче 80 символов.")
            return

        order_type = data["type"]
        amount = data.get("amount")
        order_id = create_order(
            message.from_user,
            order_type,
            amount,
            value
        )

        details = (
            f"🧾 <b>ЗАКАЗ #{order_id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌 {order_type}\n"
        )
        if amount is not None:
            details += f"💰 Количество: {format_amount(amount)}\n"
        details += (
            f"🌐 Сервер: {value}\n"
            f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
            f"🟡 Статус: Новый"
        )

        await message.answer(
            "✅ <b>ЗАКАЗ СОЗДАН!</b>\n\n"
            + details
            + "\n\nДля завершения покупки перейди на FunPay.",
            reply_markup=order_keyboard(order_id),
            parse_mode="HTML"
        )

        if ADMIN_ID:
            try:
                await bot.send_message(
                    ADMIN_ID,
                    "🔔 <b>НОВЫЙ ЗАКАЗ!</b>\n\n"
                    + details
                    + f"\n\n👤 Покупатель: @{message.from_user.username or 'без username'}"
                    + f"\n🆔 ID: {message.from_user.id}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        users.pop(message.from_user.id, None)


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
    
