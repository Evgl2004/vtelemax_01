"""Приём нажатий из интерактивных рассылок SAGUR в Telegram."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from aiogram import Router
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from loguru import logger

from vtelemax.adapters.sagur_message_interactions import (
    SagurMessageInteractionService,
    SagurMessageInteractionStorageError,
    platform_callback_fingerprint,
    utc_now,
)
from vtelemax.adapters.telegram.identity_adapter import TelegramIdentityAdapter
from vtelemax.adapters.telegram.menu import (
    build_coupons_root_inline_keyboard,
    build_main_menu_inline_keyboard,
)
from vtelemax.core.sagur_message_interactions import (
    SagurButtonPayload,
    SagurButtonPayloadError,
    SagurMessageInteractionIngress,
    remove_sagur_rating_buttons_from_rows,
    parse_sagur_button_payload,
)


TELEGRAM_CALLBACK_DATA_MAX_BYTES = 64


class TelegramSagurInteractionFilter(Filter):
    """Перехватывает только корректные либо заявленные, но ошибочные данные SAGUR."""

    async def __call__(
        self,
        callback: CallbackQuery,
    ) -> bool | dict[str, SagurButtonPayload | SagurButtonPayloadError]:
        try:
            payload = parse_sagur_button_payload(
                callback.data,
                max_bytes=TELEGRAM_CALLBACK_DATA_MAX_BYTES,
            )
        except SagurButtonPayloadError as error:
            return {"sagur_payload_error": error}
        if payload is None:
            return False
        return {"sagur_payload": payload}


def build_telegram_bot_scope(*, token: str, username: str = "") -> str:
    """Возвращает устойчивую область бота без сохранения секретной части токена."""

    bot_id = token.partition(":")[0].strip()
    if bot_id.isdecimal():
        return f"bot_id:{bot_id}"

    normalized_username = username.strip().lstrip("@").casefold()
    if normalized_username:
        return f"username:{normalized_username}"
    raise ValueError("Не удалось определить устойчивую область Telegram-бота.")


async def _answer_safely(
    callback: CallbackQuery,
    *,
    text: str,
    show_alert: bool = False,
) -> bool:
    """Отправляет технический ответ Telegram и локализует ошибку платформы."""

    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception as error:  # noqa: BLE001
        logger.bind(
            platform="telegram",
            component="sagur_message_interactions",
            stage="callback_answer",
        ).error(
            "Не удалось подтвердить нажатие Telegram; error_type={error_type}.",
            error_type=type(error).__name__,
        )
        return False
    return True


def _navigation_markup(
    status: str, coupon_scope_buttons: tuple[tuple[str, str], ...]
) -> InlineKeyboardMarkup | None:
    """Строит клавиатуру нового навигационного экрана без изменения исходного сообщения."""

    if status == "menu":
        return build_main_menu_inline_keyboard()
    if status == "coupons_root":
        return build_coupons_root_inline_keyboard(scope_buttons=coupon_scope_buttons)
    return None


async def _perform_rating_action(
    callback: CallbackQuery,
    payload: SagurButtonPayload,
) -> None:
    """Удаляет оценки из фактической Telegram-клавиатуры и сохраняет остальные кнопки."""

    message = callback.message
    if not isinstance(message, Message) or not isinstance(
        message.reply_markup,
        InlineKeyboardMarkup,
    ):
        raise ValueError("Исходное сообщение Telegram недоступно для изменения клавиатуры.")

    updated_rows = remove_sagur_rating_buttons_from_rows(
        message.reply_markup.inline_keyboard,
        clicked_payload=payload,
        payload_getter=lambda button: button.callback_data,
    )
    await message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[list(row) for row in updated_rows],
        )
    )


async def _perform_navigation_action(
    callback: CallbackQuery,
    payload: SagurButtonPayload,
    *,
    identity_adapter: TelegramIdentityAdapter,
) -> None:
    """Отправляет новое главное меню или новый корневой экран купонов."""

    user_id = callback.from_user.id
    result = identity_adapter.handle_sagur_navigation(user_id, payload.action)
    message = callback.message
    chat_id = message.chat.id if isinstance(message, Message) else user_id
    await callback.bot.send_message(
        chat_id=chat_id,
        text=result.message,
        parse_mode=result.parse_mode,
        reply_markup=_navigation_markup(result.status, result.coupon_scope_buttons),
    )


def _mark_user_action_safely(
    *,
    event_id: UUID,
    attempted_at: datetime,
    action: Callable[..., None],
    action_kwargs: dict[str, str] | None = None,
) -> None:
    """Фиксирует итог платформенного действия, не повторяя уже выполненное действие."""

    try:
        action(event_id, attempted_at=attempted_at, **(action_kwargs or {}))
    except Exception as error:  # noqa: BLE001
        logger.bind(
            platform="telegram",
            component="sagur_message_interactions",
            stage="user_action_state",
        ).exception(
            "Не удалось сохранить состояние пользовательского действия; error_type={error_type}.",
            error_type=type(error).__name__,
        )


async def handle_telegram_sagur_interaction(
    callback: CallbackQuery,
    *,
    service: SagurMessageInteractionService,
    identity_adapter: TelegramIdentityAdapter,
    bot_scope: str,
    sagur_payload: SagurButtonPayload | None = None,
    sagur_payload_error: SagurButtonPayloadError | None = None,
) -> None:
    """Долговечно фиксирует нажатие до ответа и выполняет действие Telegram."""

    user_id = callback.from_user.id
    event_logger = logger.bind(
        platform="telegram",
        component="sagur_message_interactions",
        user_id=str(user_id),
        stage="callback_received",
    )
    if sagur_payload_error is not None or sagur_payload is None:
        error_code = (
            sagur_payload_error.code if sagur_payload_error is not None else "payload_missing"
        )
        event_logger.warning(
            "Отклонены некорректные служебные данные SAGUR; error_code={error_code}.",
            error_code=error_code,
        )
        await _answer_safely(
            callback,
            text="Кнопка содержит некорректные служебные данные.",
            show_alert=True,
        )
        return

    callback_id = str(callback.id)
    message_id = getattr(callback.message, "message_id", None)
    event_logger.info(
        "Получено нажатие SAGUR; interaction_id={interaction_id}; action={action}; "
        "message_id={message_id}; callback_id_fingerprint={fingerprint}.",
        interaction_id=sagur_payload.interaction_id,
        action=sagur_payload.action,
        message_id=message_id,
        fingerprint=platform_callback_fingerprint(callback_id),
    )
    try:
        insert_result = service.record_event(
            SagurMessageInteractionIngress(
                platform="telegram",
                bot_scope=bot_scope,
                platform_callback_id=callback_id,
                interaction_id=sagur_payload.interaction_id,
                action=sagur_payload.action,
                provider_message_id=str(message_id) if message_id is not None else None,
            )
        )
    except SagurMessageInteractionStorageError:
        event_logger.error("Нажатие не сохранено; пользовательское действие не выполняется.")
        await _answer_safely(
            callback,
            text="Не удалось сохранить нажатие. Повторите попытку.",
            show_alert=True,
        )
        return

    if not insert_result.created:
        if not insert_result.immutable_fields_match:
            event_logger.error("Повторный платформенный ключ содержит другие неизменяемые данные.")
        await _answer_safely(callback, text="Нажатие уже принято.")
        return

    await _answer_safely(callback, text="Нажатие принято.")
    attempted_at = utc_now()
    try:
        if sagur_payload.action in {"l", "d"}:
            await _perform_rating_action(callback, sagur_payload)
        else:
            await _perform_navigation_action(
                callback,
                sagur_payload,
                identity_adapter=identity_adapter,
            )
    except Exception as error:  # noqa: BLE001
        event_logger.bind(stage="user_action_failed").exception(
            "Пользовательское действие Telegram не выполнено; error_type={error_type}.",
            error_type=type(error).__name__,
        )
        _mark_user_action_safely(
            event_id=insert_result.event.event_id,
            attempted_at=attempted_at,
            action=service.mark_user_action_failed,
            action_kwargs={
                "error_code": type(error).__name__,
                "error_text": str(error)[:1000],
            },
        )
        return

    _mark_user_action_safely(
        event_id=insert_result.event.event_id,
        attempted_at=attempted_at,
        action=service.mark_user_action_succeeded,
    )
    event_logger.bind(stage="user_action_succeeded").info(
        "Пользовательское действие Telegram выполнено."
    )


def build_telegram_sagur_interaction_router(
    *,
    service: SagurMessageInteractionService,
    identity_adapter: TelegramIdentityAdapter,
    bot_scope: str,
) -> Router:
    """Создаёт приоритетный маршрутизатор интерактивных сообщений SAGUR."""

    router = Router(name="telegram_sagur_message_interactions")

    async def handler(
        callback: CallbackQuery,
        sagur_payload: SagurButtonPayload | None = None,
        sagur_payload_error: SagurButtonPayloadError | None = None,
    ) -> None:
        await handle_telegram_sagur_interaction(
            callback,
            service=service,
            identity_adapter=identity_adapter,
            bot_scope=bot_scope,
            sagur_payload=sagur_payload,
            sagur_payload_error=sagur_payload_error,
        )

    router.callback_query.register(handler, TelegramSagurInteractionFilter())
    return router
