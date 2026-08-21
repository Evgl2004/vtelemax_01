"""Приём нажатий из интерактивных рассылок SAGUR в MAX."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from loguru import logger
from maxapi import Router
from maxapi.enums.parse_mode import ParseMode
from maxapi.filters.filter import BaseFilter
from maxapi.types.updates.message_callback import MessageCallback

from vtelemax.adapters.max.identity_adapter import MaxIdentityAdapter
from vtelemax.adapters.max.keyboard_renderer import render_max_keyboard
from vtelemax.adapters.sagur_message_interactions import (
    SagurMessageInteractionService,
    SagurMessageInteractionStorageError,
    platform_callback_fingerprint,
    utc_now,
)
from vtelemax.core.sagur_message_interactions import (
    SagurButtonPayload,
    SagurButtonPayloadError,
    SagurMessageInteractionIngress,
    SagurMessageKeyboardError,
    parse_sagur_button_payload,
    remove_sagur_rating_buttons_from_rows,
)


def _extract_field(source: Any, field: str) -> Any:
    """Извлекает поле из модели MAX либо словаря."""

    if isinstance(source, Mapping):
        return source.get(field)
    return getattr(source, field, None)


def _copy_with_update(source: Any, **updates: Any) -> Any:
    """Копирует модель MAX либо словарь, заменяя только указанные поля."""

    model_copy = getattr(source, "model_copy", None)
    if callable(model_copy):
        return model_copy(update=updates)
    if isinstance(source, Mapping):
        result = copy.deepcopy(dict(source))
        result.update(updates)
        return result
    raise SagurMessageKeyboardError("max_keyboard_object_cannot_be_copied")


def _normalized_type(value: Any) -> str:
    """Возвращает строковое значение типа вложения или кнопки MAX."""

    return str(getattr(value, "value", value))


def _button_payload(button: Any) -> str | Mapping[str, Any] | None:
    """Возвращает служебные данные только callback-кнопки MAX."""

    if _normalized_type(_extract_field(button, "type")) != "callback":
        return None
    payload = _extract_field(button, "payload")
    return payload if isinstance(payload, (str, Mapping)) else None


def build_max_attachments_without_rating(
    attachments: Any,
    *,
    clicked_payload: SagurButtonPayload,
) -> list[Any]:
    """Удаляет оценки из фактической клавиатуры, сохраняя остальные вложения."""

    if not isinstance(attachments, list):
        raise SagurMessageKeyboardError("max_attachments_are_not_list")
    keyboard_indexes = [
        index
        for index, attachment in enumerate(attachments)
        if _normalized_type(_extract_field(attachment, "type")) == "inline_keyboard"
    ]
    if len(keyboard_indexes) != 1:
        raise SagurMessageKeyboardError("max_inline_keyboard_count_is_not_one")

    keyboard_index = keyboard_indexes[0]
    keyboard = attachments[keyboard_index]
    keyboard_payload = _extract_field(keyboard, "payload")
    rows = _extract_field(keyboard_payload, "buttons")
    if not isinstance(rows, list) or any(not isinstance(row, list) for row in rows):
        raise SagurMessageKeyboardError("max_keyboard_rows_invalid")

    updated_rows = remove_sagur_rating_buttons_from_rows(
        rows,
        clicked_payload=clicked_payload,
        payload_getter=_button_payload,
    )
    updated_payload = _copy_with_update(
        keyboard_payload,
        buttons=[list(row) for row in updated_rows],
    )
    updated_keyboard = _copy_with_update(keyboard, payload=updated_payload)
    result = list(attachments)
    result[keyboard_index] = updated_keyboard
    return result


def _positive_user_id(value: Any) -> int | None:
    """Возвращает положительный идентификатор MAX без неявного приведения типов."""

    return value if type(value) is int and value > 0 else None


def build_max_bot_scope(event: MessageCallback, *, configured_username: str = "") -> str:
    """Возвращает устойчивую область бота из профиля MAX либо настройки."""

    bot = getattr(event, "bot", None)
    bot_user_id = _positive_user_id(_extract_field(getattr(bot, "me", None), "user_id"))
    if bot_user_id is not None:
        return f"bot_id:{bot_user_id}"

    message = getattr(event, "message", None)
    sender = _extract_field(message, "sender")
    sender_user_id = _positive_user_id(_extract_field(sender, "user_id"))
    if sender_user_id is not None and _extract_field(sender, "is_bot") is True:
        return f"bot_id:{sender_user_id}"

    normalized_username = configured_username.strip().lstrip("@").casefold()
    if normalized_username:
        return f"username:{normalized_username}"
    raise ValueError("Не удалось определить устойчивую область MAX-бота.")


def _callback_user_id(event: MessageCallback) -> int:
    """Извлекает идентификатор пользователя, нажавшего кнопку MAX."""

    callback = getattr(event, "callback", None)
    user_id = _positive_user_id(_extract_field(_extract_field(callback, "user"), "user_id"))
    if user_id is None:
        raise ValueError("MAX не передал идентификатор пользователя callback-события.")
    return user_id


def _callback_id(event: MessageCallback) -> str:
    """Извлекает уникальный идентификатор одного callback-события MAX."""

    value = _extract_field(getattr(event, "callback", None), "callback_id")
    if not isinstance(value, str) or not value:
        raise ValueError("MAX не передал идентификатор callback-события.")
    return value


async def _answer_safely(event: MessageCallback, *, notification: str = "") -> bool:
    """Подтверждает callback штатным методом MAX и локализует ошибку API."""

    try:
        answer = getattr(event, "answer", None)
        if not callable(answer):
            raise ValueError("MAX не предоставил метод подтверждения callback-события.")
        # Штатный answer сохраняет исходное сообщение в callback-ответе.
        # Низкоуровневый пустой ответ `{}` платформа отклоняет.
        await answer(notification)
    except Exception as error:  # noqa: BLE001
        logger.bind(
            platform="max",
            component="sagur_message_interactions",
            stage="callback_answer",
        ).error(
            "Не удалось подтвердить нажатие MAX; error_type={error_type}.",
            error_type=type(error).__name__,
        )
        return False
    return True


async def _perform_rating_action(
    event: MessageCallback,
    payload: SagurButtonPayload,
) -> None:
    """Редактирует фактическое сообщение MAX без потери текста и вложений."""

    message = getattr(event, "message", None)
    body = _extract_field(message, "body")
    text = _extract_field(body, "text")
    attachments = _extract_field(body, "attachments")
    markup = _extract_field(body, "markup")
    edit_message = getattr(message, "edit", None)
    if not isinstance(text, str) or not callable(edit_message):
        raise SagurMessageKeyboardError("max_message_is_not_editable")
    if markup not in (None, [], ()):
        raise SagurMessageKeyboardError("max_message_markup_cannot_be_preserved")

    updated_attachments = build_max_attachments_without_rating(
        attachments,
        clicked_payload=payload,
    )
    await edit_message(
        text=text,
        attachments=updated_attachments,
        notify=False,
    )


def _resolve_parse_mode(value: str | None) -> ParseMode | None:
    """Преобразует внутреннее имя разметки в режим MAX."""

    if value == "markdown":
        return ParseMode.MARKDOWN
    if value == "html":
        return getattr(ParseMode, "HTML", None)
    return None


async def _perform_navigation_action(
    event: MessageCallback,
    payload: SagurButtonPayload,
    *,
    identity_adapter: MaxIdentityAdapter,
) -> None:
    """Отправляет новый экран меню или купонов, не изменяя рассылку."""

    user_id = _callback_user_id(event)
    response = identity_adapter.handle_sagur_navigation(user_id, payload.action)
    bot = getattr(event, "bot", None)
    send_message = getattr(bot, "send_message", None)
    if not callable(send_message):
        raise ValueError("MAX не предоставил метод отправки сообщения.")

    kwargs: dict[str, Any] = {
        "user_id": user_id,
        "text": response.text,
    }
    message = getattr(event, "message", None)
    chat_id = _positive_user_id(_extract_field(_extract_field(message, "recipient"), "chat_id"))
    if chat_id is not None:
        kwargs.pop("user_id")
        kwargs["chat_id"] = chat_id

    keyboard = render_max_keyboard(response.screen)
    if keyboard is not None:
        kwargs["attachments"] = [keyboard]
    parse_mode_name = response.parse_mode or _extract_field(response.screen, "parse_mode")
    parse_mode = _resolve_parse_mode(parse_mode_name)
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    await send_message(**kwargs)


def _mark_user_action_safely(
    *,
    event_id: UUID,
    attempted_at: datetime,
    action: Callable[..., None],
    action_kwargs: dict[str, str] | None = None,
) -> None:
    """Сохраняет итог действия, не повторяя уже выполненный вызов MAX."""

    try:
        action(event_id, attempted_at=attempted_at, **(action_kwargs or {}))
    except Exception as error:  # noqa: BLE001
        logger.bind(
            platform="max",
            component="sagur_message_interactions",
            stage="user_action_state",
        ).exception(
            "Не удалось сохранить состояние пользовательского действия MAX; "
            "error_type={error_type}.",
            error_type=type(error).__name__,
        )


async def handle_max_sagur_interaction(
    event: MessageCallback,
    *,
    service: SagurMessageInteractionService,
    identity_adapter: MaxIdentityAdapter,
    configured_username: str = "",
    sagur_payload: SagurButtonPayload | None = None,
    sagur_payload_error: SagurButtonPayloadError | None = None,
) -> None:
    """Долговечно фиксирует событие до подтверждения и действия MAX."""

    try:
        user_id: int | str = _callback_user_id(event)
    except ValueError:
        user_id = "-"
    event_logger = logger.bind(
        platform="max",
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
            event,
            notification="Кнопка содержит некорректные служебные данные.",
        )
        return

    try:
        callback_id = _callback_id(event)
        _callback_user_id(event)
        bot_scope = build_max_bot_scope(event, configured_username=configured_username)
        message_id = _extract_field(_extract_field(getattr(event, "message", None), "body"), "mid")
        event_logger.info(
            "Получено нажатие SAGUR; interaction_id={interaction_id}; action={action}; "
            "message_id={message_id}; callback_id_fingerprint={fingerprint}.",
            interaction_id=sagur_payload.interaction_id,
            action=sagur_payload.action,
            message_id=message_id,
            fingerprint=platform_callback_fingerprint(callback_id),
        )
        insert_result = service.record_event(
            SagurMessageInteractionIngress(
                platform="max",
                bot_scope=bot_scope,
                platform_callback_id=callback_id,
                interaction_id=sagur_payload.interaction_id,
                action=sagur_payload.action,
                provider_message_id=message_id if isinstance(message_id, str) else None,
            )
        )
    except (SagurMessageInteractionStorageError, ValueError):
        event_logger.exception(
            "Нажатие MAX не сохранено; пользовательское действие не выполняется."
        )
        await _answer_safely(
            event,
            notification="Не удалось сохранить нажатие. Повторите попытку.",
        )
        return

    if not insert_result.created:
        if not insert_result.immutable_fields_match:
            event_logger.error("Повторный платформенный ключ содержит другие неизменяемые данные.")
        await _answer_safely(event)
        return

    # Подтверждение выполняется перед отдельным редактированием. Иначе
    # callback-ответ с исходной клавиатурой способен перезаписать результат.
    await _answer_safely(event)
    attempted_at = utc_now()
    try:
        if sagur_payload.action in {"l", "d"}:
            await _perform_rating_action(event, sagur_payload)
        else:
            await _perform_navigation_action(
                event,
                sagur_payload,
                identity_adapter=identity_adapter,
            )
    except Exception as error:  # noqa: BLE001
        event_logger.bind(stage="user_action_failed").exception(
            "Пользовательское действие MAX не выполнено; error_type={error_type}.",
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
        "Пользовательское действие MAX выполнено."
    )


class MaxSagurInteractionFilter(BaseFilter):
    """Распознаёт служебный JSON SAGUR и отдельно передаёт ошибку контракта."""

    async def __call__(
        self,
        event: Any,
    ) -> dict[str, SagurButtonPayload | SagurButtonPayloadError] | bool:
        if not isinstance(event, MessageCallback):
            return False
        try:
            payload = parse_sagur_button_payload(_extract_field(event.callback, "payload"))
        except SagurButtonPayloadError as error:
            return {"sagur_payload_error": error}
        if payload is None:
            return False
        return {"sagur_payload": payload}


def build_max_sagur_interaction_router(
    *,
    service: SagurMessageInteractionService,
    identity_adapter: MaxIdentityAdapter,
    configured_username: str = "",
) -> Router:
    """Создаёт приоритетный маршрутизатор интерактивных сообщений SAGUR."""

    router = Router(router_id="max_sagur_message_interactions")

    async def handler(
        event: MessageCallback,
        sagur_payload: SagurButtonPayload | None = None,
        sagur_payload_error: SagurButtonPayloadError | None = None,
    ) -> None:
        await handle_max_sagur_interaction(
            event,
            service=service,
            identity_adapter=identity_adapter,
            configured_username=configured_username,
            sagur_payload=sagur_payload,
            sagur_payload_error=sagur_payload_error,
        )

    router.message_callback.register(handler, MaxSagurInteractionFilter())
    return router
