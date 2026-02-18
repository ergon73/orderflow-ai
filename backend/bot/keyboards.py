from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def order_action_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить", callback_data=f"order:confirm:{order_id}"
                ),
                InlineKeyboardButton(
                    text="Исправить", callback_data=f"order:edit:{order_id}"
                ),
                InlineKeyboardButton(
                    text="Отменить", callback_data=f"order:cancel:{order_id}"
                ),
            ]
        ]
    )

