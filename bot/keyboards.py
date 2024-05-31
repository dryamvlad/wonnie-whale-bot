from aiogram.types import InlineKeyboardButton as Button
from aiogram.types import InlineKeyboardMarkup as Markup
from bot.config import Settings


async def kb_buy_won(settings: Settings, price, disconnect=False) -> Markup:
    amount = int(settings.THRESHOLD_BALANCE * price * 1e9)
    buy_url = f"https://dedust.io/swap/TON/{settings.WON_ADDR}?amount={amount}"
    buy_btn = Button(
        text="Купить WON",
        url=buy_url,
    )
    if disconnect:
        return Markup(
            inline_keyboard=[
                [
                    Button(
                        text="Отключиться",
                        callback_data="disconnect",
                    )
                ],
                [buy_btn],
            ]
        )
    else:
        return Markup(
            inline_keyboard=[
                [buy_btn],
            ]
        )
