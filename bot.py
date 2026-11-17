
import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, InlineKeyboardMarkup,
    InlineKeyboardButton, CallbackQuery
)

TOKEN = os.getenv("BOT_TOKEN")
FUNPAY_URL = os.getenv(
    "FUNPAY_URL",
    "https://funpay.com/lots/offer?id=82465245"
)
ADMIN_ID = os.getenv("ADMIN_ID", "")

bot = Bot(token=TOKEN)
dp = Dispatcher()

users = {}

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Вирты", callback_data="virts")],
        [InlineKeyboardButton(text="🛠 Услуги", callback_data="services")]
    ])

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🌑 ROBRUN SHOP\n\nВыбери, что тебя интересует:",
        reply_markup=menu()
    )

@dp.callback_query(F.data == "virts")
async def virts(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{i} млн", callback_data=f"amount:{i}")]
        for i in range(1, 6)
    ])
    await call.message.answer("💰 Выбери количество виртов:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("amount:"))
async def amount(call: CallbackQuery):
    value = call.data.split(":")[1]
    users[call.from_user.id] = {"type": "Вирты", "amount": value}
    await call.message.answer(f"Выбрано: {value} млн.\n\nНапиши название своего сервера:")
    await call.answer()

@dp.callback_query(F.data == "services")
async def services(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сопровождение 2 читеров на рейд", callback_data="service:raid")],
        [InlineKeyboardButton(text="Сопровождение 2 читеров на продажу в ангаре", callback_data="service:hangar")]
    ])
    await call.message.answer("🛠 Выбери услугу:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("service:"))
async def service(call: CallbackQuery):
    value = call.data.split(":")[1]
    name = "Сопровождение 2 читеров на рейд" if value == "raid" else "Сопровождение 2 читеров на продажу в ангаре"
    users[call.from_user.id] = {"type": name}
    await call.message.answer("Напиши название своего сервера:")
    await call.answer()

@dp.message(F.text)
async def server(message: Message):
    data = users.get(message.from_user.id)
    if not data:
        return
    server_name = message.text.strip()
    data["server"] = server_name
    details = f"Заказ: {data['type']}\n"
    if "amount" in data:
        details += f"Количество: {data['amount']} млн\n"
    details += f"Сервер: {server_name}"
    await message.answer(
        f"✅ Заказ оформлен!\n\n{details}\n\n"
        f"Для завершения покупки перейди на FunPay:\n{FUNPAY_URL}"
    )
    if ADMIN_ID:
        try:
            await bot.send_message(int(ADMIN_ID), "🛒 Новый заказ!\n" + details)
        except Exception:
            pass
    users.pop(message.from_user.id, None)

async def health(request):
    return web.Response(text="Bot is running")

async def main():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "10000")))
    await site.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
