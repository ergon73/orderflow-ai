import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist

from ai_parser.services import process_intake_message
from integrations.apiship import apiship_auto_create_on_confirmed, create_shipment_for_order_safe
from integrations.sync import sync_order_to_bpium_safe
from orders.models import Order
from orders.services import (
    change_order_status,
    create_telegram_intake,
    get_active_needs_info_order,
    get_or_create_telegram_customer,
    request_order_edit,
)

from .keyboards import order_action_keyboard

logger = logging.getLogger(__name__)
router = Router()
ACTIVE_ORDER_CONTEXT: dict[int, int] = {}


def _build_order_summary(order: Order, missing_fields: list[str]) -> str:
    items = ", ".join(f"{item.quantity}x {item.title}" for item in order.items.all())
    if not items:
        items = "не распознаны"

    lines = [
        f"Заказ #{order.id}",
        f"Товары: {items}",
        f"Адрес: {order.delivery_address or 'не указан'}",
        f"Статус: {order.get_status_display()}",
    ]
    if missing_fields:
        lines.append(f"Нужно уточнить: {', '.join(missing_fields)}")
    return "\n".join(lines)


async def _load_order(order_id: int) -> Order:
    return await sync_to_async(
        lambda: Order.objects.select_related("customer")
        .prefetch_related("items")
        .get(id=order_id)
    )()


async def _load_context_order(telegram_user_id: int, customer_id: int) -> Order | None:
    order_id = ACTIVE_ORDER_CONTEXT.get(telegram_user_id)
    if not order_id:
        return None
    try:
        return await sync_to_async(
            lambda: Order.objects.select_related("customer")
            .prefetch_related("items")
            .get(
                id=order_id,
                customer_id=customer_id,
                status=Order.Status.NEEDS_INFO,
                needs_manual_review=False,
            )
        )()
    except ObjectDoesNotExist:
        ACTIVE_ORDER_CONTEXT.pop(telegram_user_id, None)
        return None


def _parse_order_id(callback_data: str | None) -> int | None:
    if not callback_data:
        return None
    try:
        return int(callback_data.split(":")[-1])
    except (ValueError, IndexError):
        return None


def _is_order_owner(order: Order, telegram_user_id: int) -> bool:
    return order.customer.telegram_id == telegram_user_id


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "Привет. Отправьте заказ в свободной форме, например: "
        "'Хочу 2 кружки на Ленина 10, телефон 89161234567'."
    )


@router.message(F.text)
async def order_message_handler(message: Message) -> None:
    if not message.from_user:
        return

    logger.info("intake_received chat_id=%s message_id=%s", message.chat.id, message.message_id)
    customer = await sync_to_async(get_or_create_telegram_customer)(
        telegram_id=message.from_user.id,
        display_name=message.from_user.full_name or message.from_user.username,
    )
    intake, created = await sync_to_async(create_telegram_intake)(
        customer=customer,
        text=message.text,
        chat_id=message.chat.id,
        message_id=message.message_id,
    )

    if not created:
        await message.answer("Это сообщение уже обработано, дубль проигнорирован.")
        return

    pending_order = await _load_context_order(message.from_user.id, customer.id)
    if pending_order is None:
        pending_order = await sync_to_async(get_active_needs_info_order)(customer)

    try:
        order, attempt = await sync_to_async(process_intake_message)(
            intake=intake,
            order=pending_order,
        )
    except Exception as exc:
        logger.exception(
            "intake_processing_failed chat_id=%s message_id=%s error=%s",
            message.chat.id,
            message.message_id,
            exc,
        )
        await message.answer(
            "Не удалось обработать заказ из-за временной ошибки. "
            "Попробуйте еще раз через 10-20 секунд."
        )
        return

    if order.needs_manual_review:
        ACTIVE_ORDER_CONTEXT.pop(message.from_user.id, None)
        await message.answer(
            f"Заказ #{order.id} передан на ручную обработку. Менеджер свяжется с вами."
        )
        return

    if order.status == Order.Status.NEEDS_INFO:
        ACTIVE_ORDER_CONTEXT[message.from_user.id] = order.id
    else:
        ACTIVE_ORDER_CONTEXT.pop(message.from_user.id, None)

    summary = await sync_to_async(_build_order_summary)(order, attempt.missing_fields)
    if order.status == Order.Status.NEEDS_INFO:
        questions = attempt.result_json.get("clarifying_questions", [])
        question_text = ""
        if questions:
            question_text = "\n" + "\n".join(f"- {q}" for q in questions)
        summary += "\n\nУточните данные, пожалуйста." + question_text

    await message.answer(summary, reply_markup=order_action_keyboard(order.id))


@router.callback_query(F.data.startswith("order:confirm:"))
async def confirm_order_handler(callback: CallbackQuery) -> None:
    if not callback.from_user:
        await callback.answer()
        return

    order_id = _parse_order_id(callback.data)
    if order_id is None:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    try:
        order = await _load_order(order_id)
    except ObjectDoesNotExist:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    if not _is_order_owner(order, callback.from_user.id):
        await callback.answer("Это не ваш заказ", show_alert=True)
        return

    try:
        old_status = order.status
        order = await sync_to_async(change_order_status)(
            order=order,
            new_status=Order.Status.CONFIRMED,
            actor=f"telegram_user:{callback.from_user.id}",
            comment="confirmed by client",
        )
        if old_status != order.status:
            sync_ok = await sync_to_async(sync_order_to_bpium_safe)(order)
            if not sync_ok:
                logger.warning("bpium_sync_failed_from_bot order_id=%s action=confirm", order.id)
            if order.status == Order.Status.CONFIRMED and apiship_auto_create_on_confirmed():
                await sync_to_async(create_shipment_for_order_safe)(order)
        ACTIVE_ORDER_CONTEXT.pop(callback.from_user.id, None)
        await callback.message.answer(f"Заказ #{order_id} подтверждён.")
    except ValueError as exc:
        await callback.message.answer(f"Нельзя подтвердить заказ: {exc}")
    await callback.answer()


@router.callback_query(F.data.startswith("order:edit:"))
async def edit_order_handler(callback: CallbackQuery) -> None:
    if not callback.from_user:
        await callback.answer()
        return

    order_id = _parse_order_id(callback.data)
    if order_id is None:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    try:
        order = await _load_order(order_id)
    except ObjectDoesNotExist:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    if not _is_order_owner(order, callback.from_user.id):
        await callback.answer("Это не ваш заказ", show_alert=True)
        return

    await sync_to_async(request_order_edit)(
        order=order,
        actor=f"telegram_user:{callback.from_user.id}",
        comment="client requested correction",
    )
    ACTIVE_ORDER_CONTEXT[callback.from_user.id] = order.id
    await callback.message.answer(
        f"Заказ #{order_id} переведён в уточнение. Напишите исправления одним сообщением."
    )
    await callback.answer()


@router.callback_query(F.data.startswith("order:cancel:"))
async def cancel_order_handler(callback: CallbackQuery) -> None:
    if not callback.from_user:
        await callback.answer()
        return

    order_id = _parse_order_id(callback.data)
    if order_id is None:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    try:
        order = await _load_order(order_id)
    except ObjectDoesNotExist:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    if not _is_order_owner(order, callback.from_user.id):
        await callback.answer("Это не ваш заказ", show_alert=True)
        return

    try:
        old_status = order.status
        order = await sync_to_async(change_order_status)(
            order=order,
            new_status=Order.Status.CANCELLED,
            actor=f"telegram_user:{callback.from_user.id}",
            comment="cancelled by client",
        )
        if old_status != order.status:
            sync_ok = await sync_to_async(sync_order_to_bpium_safe)(order)
            if not sync_ok:
                logger.warning("bpium_sync_failed_from_bot order_id=%s action=cancel", order.id)
        ACTIVE_ORDER_CONTEXT.pop(callback.from_user.id, None)
        await callback.message.answer(f"Заказ #{order_id} отменён.")
    except ValueError as exc:
        await callback.message.answer(f"Нельзя отменить заказ: {exc}")
    await callback.answer()
