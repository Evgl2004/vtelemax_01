"""Приём нажатий из интерактивных рассылок SAGUR во ВКонтакте."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from loguru import logger
from vkbottle.bot import MessageEvent
from vkbottle.dispatch.rules import ABCRule
from vkbottle_types.events import GroupEventType

from vtelemax.adapters.sagur_message_interactions import (
    SagurMessageInteractionService,
    SagurMessageInteractionStorageError,
    platform_callback_fingerprint,
    utc_now,
)
from vtelemax.adapters.vk.identity_adapter import VkIdentityAdapter
from vtelemax.adapters.vk.keyboard_renderer import render_vk_keyboard
from vtelemax.core.sagur_message_interactions import (
    SagurButtonPayload,
    SagurButtonPayloadError,
    SagurMessageInteractionIngress,
    SagurMessageKeyboardError,
    parse_sagur_button_payload,
    remove_sagur_rating_buttons_from_rows,
)


_EDITABLE_ATTACHMENT_FIELDS: dict[str, tuple[str, str, str]] = {
    "photo": ("photo", "owner_id", "id"),
    "video": ("video", "owner_id", "id"),
    "audio": ("audio", "owner_id", "id"),
    "doc": ("doc", "owner_id", "id"),
    "wall": ("wall", "from_id", "id"),
}


def _extract_field(source: Any, field: str) -> Any:
    """Извлекает поле из объекта ответа VK либо словаря."""

    if isinstance(source, Mapping):
        return source.get(field)
    return getattr(source, field, None)


def _to_plain_mapping(value: Any) -> dict[str, Any] | None:
    """Преобразует модель VK в независимый словарь без изменения источника."""

    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(by_alias=True, exclude_none=True)
        if isinstance(dumped, dict):
            return dumped
    return None


def _button_payload(button: Any) -> str | Mapping[str, Any] | None:
    """Возвращает служебные данные только callback-кнопки VK."""

    button_mapping = _to_plain_mapping(button)
    if button_mapping is None:
        return None
    action = _to_plain_mapping(button_mapping.get("action"))
    if action is None or action.get("type") != "callback":
        return None
    payload = action.get("payload")
    return payload if isinstance(payload, (str, Mapping)) else None


def build_vk_keyboard_without_rating(
    keyboard: Any,
    *,
    clicked_payload: SagurButtonPayload,
) -> dict[str, Any]:
    """Удаляет оценки и возвращает только разрешённые входные поля клавиатуры VK."""

    keyboard_mapping = _to_plain_mapping(keyboard)
    if (
        keyboard_mapping is None
        or keyboard_mapping.get("inline") is not True
        or keyboard_mapping.get("one_time") is not False
    ):
        raise SagurMessageKeyboardError("vk_keyboard_is_not_inline")
    rows = keyboard_mapping.get("buttons")
    if not isinstance(rows, list) or any(not isinstance(row, list) for row in rows):
        raise SagurMessageKeyboardError("vk_keyboard_rows_invalid")

    updated_rows = remove_sagur_rating_buttons_from_rows(
        rows,
        clicked_payload=clicked_payload,
        payload_getter=_button_payload,
    )
    return {
        "one_time": False,
        "inline": True,
        "buttons": [list(row) for row in updated_rows],
    }


def _attachment_reference(attachment: Any) -> str:
    """Преобразует редактируемое вложение VK в ссылку метода `messages.edit`."""

    raw_type = _extract_field(attachment, "type")
    attachment_type = getattr(raw_type, "value", raw_type)
    descriptor = _EDITABLE_ATTACHMENT_FIELDS.get(str(attachment_type))
    if descriptor is None:
        raise SagurMessageKeyboardError("vk_attachment_type_unsupported")
    field_name, owner_field, id_field = descriptor
    value = _extract_field(attachment, field_name)
    owner_id = _extract_field(value, owner_field)
    media_id = _extract_field(value, id_field)
    if type(owner_id) is not int or type(media_id) is not int:
        raise SagurMessageKeyboardError("vk_attachment_identifier_invalid")

    result = f"{attachment_type}{owner_id}_{media_id}"
    access_key = _extract_field(value, "access_key")
    if isinstance(access_key, str) and access_key:
        result = f"{result}_{access_key}"
    return result


def build_vk_attachment_value(attachments: Any) -> str | None:
    """Собирает значение `attachment`, сохраняя порядок исходных вложений."""

    if attachments in (None, [], ()):
        return None
    if not isinstance(attachments, Sequence) or isinstance(attachments, (str, bytes)):
        raise SagurMessageKeyboardError("vk_attachments_invalid")
    return ",".join(_attachment_reference(attachment) for attachment in attachments)


def _event_id(event: MessageEvent) -> str:
    """Извлекает уникальный идентификатор одного callback-события VK."""

    direct = getattr(event, "event_id", None)
    if direct is None:
        direct = getattr(getattr(event, "object", None), "event_id", None)
    value = str(direct or "")
    if not value:
        raise ValueError("VK не передал идентификатор callback-события.")
    return value


def build_vk_bot_scope(event: MessageEvent, *, configured_group_id: int = 0) -> str:
    """Возвращает неизменяемую область сообщества из события либо настройки."""

    group_id = getattr(event, "group_id", None)
    if type(group_id) is not int or group_id <= 0:
        group_id = configured_group_id
    if type(group_id) is not int or group_id <= 0:
        raise ValueError("Не удалось определить идентификатор сообщества VK.")
    return f"group_id:{group_id}"


async def _answer_safely(event: MessageEvent, *, error_text: str | None = None) -> bool:
    """Подтверждает callback либо показывает ошибку, локализуя сбой VK API."""

    try:
        if error_text is None:
            await event.send_empty_answer()
        else:
            await event.show_snackbar(error_text)
    except Exception as error:  # noqa: BLE001
        logger.bind(
            platform="vk",
            component="sagur_message_interactions",
            stage="callback_answer",
        ).error(
            "Не удалось подтвердить нажатие VK; error_type={error_type}.",
            error_type=type(error).__name__,
        )
        return False
    return True


async def _fetch_source_message(event: MessageEvent) -> Any:
    """Читает ровно одно исходное сообщение по идентификатору внутри диалога."""

    peer_id = getattr(event, "peer_id", None)
    conversation_message_id = getattr(event, "conversation_message_id", None)
    messages_api = getattr(getattr(event, "ctx_api", None), "messages", None)
    fetcher = getattr(messages_api, "get_by_conversation_message_id", None)
    if (
        type(peer_id) is not int
        or type(conversation_message_id) is not int
        or not callable(fetcher)
    ):
        raise SagurMessageKeyboardError("vk_message_lookup_unavailable")

    response = await fetcher(
        peer_id=peer_id,
        conversation_message_ids=[conversation_message_id],
    )
    items = _extract_field(response, "items")
    if items is None and isinstance(response, Mapping):
        items = _extract_field(response.get("response"), "items")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)) or len(items) != 1:
        raise SagurMessageKeyboardError("vk_message_lookup_ambiguous")
    return items[0]


async def _perform_rating_action(
    event: MessageEvent,
    payload: SagurButtonPayload,
) -> None:
    """Редактирует фактическое сообщение VK без потери текста и вложений."""

    source_message = await _fetch_source_message(event)
    text = _extract_field(source_message, "text")
    if not isinstance(text, str):
        raise SagurMessageKeyboardError("vk_message_text_unavailable")
    updated_keyboard = build_vk_keyboard_without_rating(
        _extract_field(source_message, "keyboard"),
        clicked_payload=payload,
    )
    attachment_value = build_vk_attachment_value(
        _extract_field(source_message, "attachments")
    )
    kwargs: dict[str, Any] = {
        "message": text,
        "keyboard": json.dumps(updated_keyboard, ensure_ascii=False, separators=(",", ":")),
        "keep_forward_messages": True,
        "keep_snippets": True,
    }
    if attachment_value is not None:
        kwargs["attachment"] = attachment_value
    await event.edit_message(**kwargs)


async def _perform_navigation_action(
    event: MessageEvent,
    payload: SagurButtonPayload,
    *,
    identity_adapter: VkIdentityAdapter,
) -> None:
    """Отправляет новый экран меню или купонов, не изменяя сообщение рассылки."""

    user_id = int(event.user_id)
    peer_id = int(event.peer_id)
    response = identity_adapter.handle_sagur_navigation(user_id, payload.action)
    keyboard = render_vk_keyboard(response.screen)
    kwargs: dict[str, Any] = {
        "peer_id": peer_id,
        "random_id": 0,
        "message": response.text,
    }
    if keyboard is not None:
        kwargs["keyboard"] = keyboard
    parse_mode = response.parse_mode or getattr(response.screen, "parse_mode", None)
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    await event.ctx_api.messages.send(**kwargs)


def _mark_user_action_safely(
    *,
    event_id: UUID,
    attempted_at: datetime,
    action: Callable[..., None],
    action_kwargs: dict[str, str] | None = None,
) -> None:
    """Сохраняет итог действия, не повторяя уже выполненный вызов VK."""

    try:
        action(event_id, attempted_at=attempted_at, **(action_kwargs or {}))
    except Exception as error:  # noqa: BLE001
        logger.bind(
            platform="vk",
            component="sagur_message_interactions",
            stage="user_action_state",
        ).exception(
            "Не удалось сохранить состояние пользовательского действия VK; "
            "error_type={error_type}.",
            error_type=type(error).__name__,
        )


async def handle_vk_sagur_interaction(
    event: MessageEvent,
    *,
    service: SagurMessageInteractionService,
    identity_adapter: VkIdentityAdapter,
    configured_group_id: int = 0,
    sagur_payload: SagurButtonPayload | None = None,
    sagur_payload_error: SagurButtonPayloadError | None = None,
) -> None:
    """Долговечно фиксирует событие до подтверждения и действия VK."""

    user_id = getattr(event, "user_id", None)
    event_logger = logger.bind(
        platform="vk",
        component="sagur_message_interactions",
        user_id=str(user_id) if user_id is not None else "-",
        stage="callback_received",
    )
    if sagur_payload_error is not None or sagur_payload is None:
        error_code = sagur_payload_error.code if sagur_payload_error is not None else "payload_missing"
        event_logger.warning(
            "Отклонены некорректные служебные данные SAGUR; error_code={error_code}.",
            error_code=error_code,
        )
        await _answer_safely(event, error_text="Кнопка содержит некорректные служебные данные.")
        return

    try:
        callback_id = _event_id(event)
        bot_scope = build_vk_bot_scope(event, configured_group_id=configured_group_id)
        conversation_message_id = getattr(event, "conversation_message_id", None)
        event_logger.info(
            "Получено нажатие SAGUR; interaction_id={interaction_id}; action={action}; "
            "conversation_message_id={message_id}; callback_id_fingerprint={fingerprint}.",
            interaction_id=sagur_payload.interaction_id,
            action=sagur_payload.action,
            message_id=conversation_message_id,
            fingerprint=platform_callback_fingerprint(callback_id),
        )
        insert_result = service.record_event(
            SagurMessageInteractionIngress(
                platform="vk",
                bot_scope=bot_scope,
                platform_callback_id=callback_id,
                interaction_id=sagur_payload.interaction_id,
                action=sagur_payload.action,
                provider_message_id=(
                    str(conversation_message_id)
                    if conversation_message_id is not None
                    else None
                ),
            )
        )
    except (SagurMessageInteractionStorageError, ValueError):
        event_logger.exception("Нажатие VK не сохранено; пользовательское действие не выполняется.")
        await _answer_safely(event, error_text="Не удалось сохранить нажатие. Повторите попытку.")
        return

    if not insert_result.created:
        if not insert_result.immutable_fields_match:
            event_logger.error("Повторный платформенный ключ содержит другие неизменяемые данные.")
        await _answer_safely(event)
        return

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
            "Пользовательское действие VK не выполнено; error_type={error_type}.",
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
        "Пользовательское действие VK выполнено."
    )


class VkSagurInteractionRule(ABCRule[MessageEvent]):
    """Распознаёт служебный JSON SAGUR и отдельно передаёт ошибку контракта."""

    async def check(
        self,
        event: MessageEvent,
    ) -> dict[str, SagurButtonPayload | SagurButtonPayloadError] | bool:
        try:
            payload = parse_sagur_button_payload(event.get_payload_json())
        except SagurButtonPayloadError as error:
            return {"sagur_payload_error": error}
        if payload is None:
            return False
        return {"sagur_payload": payload}


def register_vk_sagur_message_interactions(
    bot: Any,
    *,
    service: SagurMessageInteractionService,
    identity_adapter: VkIdentityAdapter,
    configured_group_id: int = 0,
) -> None:
    """Регистрирует блокирующий обработчик SAGUR раньше общего маршрута VK."""

    async def handler(
        event: MessageEvent,
        sagur_payload: SagurButtonPayload | None = None,
        sagur_payload_error: SagurButtonPayloadError | None = None,
    ) -> None:
        await handle_vk_sagur_interaction(
            event,
            service=service,
            identity_adapter=identity_adapter,
            configured_group_id=configured_group_id,
            sagur_payload=sagur_payload,
            sagur_payload_error=sagur_payload_error,
        )

    bot.on.raw_event(
        GroupEventType.MESSAGE_EVENT,
        MessageEvent,
        VkSagurInteractionRule(),
        blocking=True,
    )(handler)
