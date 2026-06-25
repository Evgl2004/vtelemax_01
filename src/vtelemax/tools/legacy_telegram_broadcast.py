"""Инструменты рассылки для migrated legacy-пользователей Telegram.

Модуль решает прикладную задачу перехода со старого Telegram-бота:

1. Выбрать уникальные Telegram chat_id из legacy SQLite-источника.
2. Поддержать точечный фильтр по телефону.
3. Сформировать приветственное сообщение о новом интерфейсе.
4. Отправить рассылку с классификацией ошибок Telegram API.

Фактический CLI-раннер находится в `scripts/legacy_telegram_broadcast.py`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Sequence

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import ReplyKeyboardRemove
from loguru import logger

from vtelemax.core import normalize_phone
from vtelemax.tools.legacy_telegram_migration import LegacyTelegramSourceRecord


_INVISIBLE_CLEANUP_TEXT = "\u2063"


@dataclass(frozen=True, slots=True)
class LegacyBroadcastTarget:
    """Цель рассылки для конкретного Telegram-пользователя."""

    telegram_user_id: int
    raw_phone: str
    phone_e164: str | None


@dataclass(frozen=True, slots=True)
class LegacyBroadcastSelectionResult:
    """Итог отбора получателей рассылки."""

    targets: tuple[LegacyBroadcastTarget, ...]
    invalid_telegram_id_rows: int
    invalid_phone_rows: int
    skipped_by_phone_filter: int
    duplicate_telegram_id_rows: int


@dataclass(frozen=True, slots=True)
class LegacyBroadcastSendResult:
    """Итог отправки рассылки."""

    total_targets: int
    sent_cleanup: int
    sent_messages: int
    failed_cleanup: int
    failed_messages: int
    retry_after_errors: int
    forbidden_errors: int
    chat_not_found_errors: int
    other_errors: int


def build_default_legacy_broadcast_message() -> str:
    """Возвращает дефолтный текст рассылки о переходе на новый бот."""

    return (
        "👋 Привет! Мы обновили бота и перевели его на новое меню.\n\n"
        "Пожалуйста, нажмите команду /start, чтобы продолжить работу в новой версии.\n\n"
        "Доступны и альтернативные каналы:\n"
        "• VK: https://vk.me/club236296391\n"
        "• MAX: https://max.ru/id7203243481_bot\n\n"
        "Что есть в новом меню:\n"
        "• 💰 Мой баланс — просмотр бонусных баллов\n"
        "• 🪪 Карта — виртуальная карта лояльности\n"
        "• 🚚 Доставка — заказ доставки из ресторанов\n"
        "• ❓ Мне только спросить — обращение в отдел заботы\n"
        "• 🎟️ Купоны — ваши персональные купоны\n"
        "• ✍️ Оставить отзыв — обратная связь\n"
        "• 🍽️ Бизнес-ланч — меню бизнес-ланча\n"
        "• 🪑 Бронь стола — онлайн-бронирование\n"
        "• 👤 Профиль — управление личными данными\n\n"
        "Если внизу чата остались старые кнопки, просто нажмите /start еще раз."
    )


def _is_chat_not_found_error(error: TelegramBadRequest) -> bool:
    """Определяет, что Telegram вернул ошибку `chat not found`."""

    return "chat not found" in str(error).lower()


async def send_legacy_broadcast(
    bot: Bot,
    targets: Sequence[LegacyBroadcastTarget],
    *,
    delay_seconds: float = 0.5,
    cleanup_before_message: bool = True,
) -> LegacyBroadcastSendResult:
    """Асинхронно отправляет рассылку с предварительной очисткой reply-кнопок.

    Args:
        bot: экземпляр aiogram.Bot.
        targets: список получателей.
        delay_seconds: задержка между пользователями.
        cleanup_before_message: отправлять ли отдельную очистку кэша клавиатуры
            перед приветственным сообщением.
    """

    total = len(targets)
    sent_cleanup = 0
    sent_messages = 0
    failed_cleanup = 0
    failed_messages = 0
    retry_after_errors = 0
    forbidden_errors = 0
    chat_not_found_errors = 0
    other_errors = 0

    token = getattr(bot, "token", None)
    if token:
        masked = f"{token[:5]}...{token[-5:]}" if len(token) > 10 else "***"
        logger.debug("legacy-broadcast: используем токен {}", masked)

    message_text = build_default_legacy_broadcast_message()
    normalized_delay = max(0.0, float(delay_seconds))

    for index, target in enumerate(targets, start=1):
        chat_id = target.telegram_user_id
        logger.info(
            "[legacy-broadcast] {}/{} chat_id={} phone={}",
            index,
            total,
            chat_id,
            target.phone_e164 or "unknown",
        )

        if cleanup_before_message:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=_INVISIBLE_CLEANUP_TEXT,
                    reply_markup=ReplyKeyboardRemove(),
                )
                sent_cleanup += 1
            except TelegramRetryAfter as error:
                retry_after_errors += 1
                wait_for = max(float(error.retry_after), 0.0) + normalized_delay
                logger.warning(
                    "[legacy-broadcast] retry_after на cleanup для chat_id={}. Ждем {:.2f} сек и пропускаем.",
                    chat_id,
                    wait_for,
                )
                await asyncio.sleep(wait_for)
                continue
            except TelegramForbiddenError:
                forbidden_errors += 1
                logger.warning(
                    "[legacy-broadcast] cleanup: бот заблокирован пользователем chat_id={}.",
                    chat_id,
                )
                continue
            except TelegramBadRequest as error:
                failed_cleanup += 1
                if _is_chat_not_found_error(error):
                    chat_not_found_errors += 1
                    logger.warning(
                        "[legacy-broadcast] cleanup: chat not found chat_id={}.",
                        chat_id,
                    )
                else:
                    logger.warning(
                        "[legacy-broadcast] cleanup: bad request chat_id={}, error={}",
                        chat_id,
                        error,
                    )
            except Exception as error:  # noqa: BLE001
                failed_cleanup += 1
                other_errors += 1
                logger.warning(
                    "[legacy-broadcast] cleanup: unexpected error chat_id={}, error={}",
                    chat_id,
                    error,
                )

        try:
            await bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode=None,
                disable_web_page_preview=False,
                reply_markup=ReplyKeyboardRemove() if not cleanup_before_message else None,
            )
            sent_messages += 1
            if not cleanup_before_message:
                sent_cleanup += 1
        except TelegramRetryAfter as error:
            retry_after_errors += 1
            wait_for = max(float(error.retry_after), 0.0) + normalized_delay
            logger.warning(
                "[legacy-broadcast] retry_after на message для chat_id={}. Ждем {:.2f} сек и пробуем 1 ретрай.",
                chat_id,
                wait_for,
            )
            await asyncio.sleep(wait_for)
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=message_text,
                    parse_mode=None,
                    disable_web_page_preview=False,
                    reply_markup=ReplyKeyboardRemove() if not cleanup_before_message else None,
                )
                sent_messages += 1
                if not cleanup_before_message:
                    sent_cleanup += 1
            except TelegramBadRequest as retry_error:
                failed_messages += 1
                if _is_chat_not_found_error(retry_error):
                    chat_not_found_errors += 1
                else:
                    other_errors += 1
            except TelegramForbiddenError:
                failed_messages += 1
                forbidden_errors += 1
            except Exception:  # noqa: BLE001
                failed_messages += 1
                other_errors += 1
        except TelegramForbiddenError:
            failed_messages += 1
            forbidden_errors += 1
            logger.warning(
                "[legacy-broadcast] message: бот заблокирован пользователем chat_id={}.",
                chat_id,
            )
        except TelegramBadRequest as error:
            failed_messages += 1
            if _is_chat_not_found_error(error):
                chat_not_found_errors += 1
                logger.warning(
                    "[legacy-broadcast] message: chat not found chat_id={}.",
                    chat_id,
                )
            else:
                logger.warning(
                    "[legacy-broadcast] message: bad request chat_id={}, error={}",
                    chat_id,
                    error,
                )
        except Exception as error:  # noqa: BLE001
            failed_messages += 1
            other_errors += 1
            logger.warning(
                "[legacy-broadcast] message: unexpected error chat_id={}, error={}",
                chat_id,
                error,
            )

        if index < total and normalized_delay > 0:
            await asyncio.sleep(normalized_delay)

    logger.info(
        "[legacy-broadcast] итог: total={}, sent_cleanup={}, sent_messages={}, "
        "failed_cleanup={}, failed_messages={}, retry_after={}, forbidden={}, chat_not_found={}, other={}",
        total,
        sent_cleanup,
        sent_messages,
        failed_cleanup,
        failed_messages,
        retry_after_errors,
        forbidden_errors,
        chat_not_found_errors,
        other_errors,
    )
    return LegacyBroadcastSendResult(
        total_targets=total,
        sent_cleanup=sent_cleanup,
        sent_messages=sent_messages,
        failed_cleanup=failed_cleanup,
        failed_messages=failed_messages,
        retry_after_errors=retry_after_errors,
        forbidden_errors=forbidden_errors,
        chat_not_found_errors=chat_not_found_errors,
        other_errors=other_errors,
    )


def select_legacy_broadcast_targets(
    source_records: Sequence[LegacyTelegramSourceRecord],
    *,
    phone_filter_e164: str | None = None,
) -> LegacyBroadcastSelectionResult:
    """Формирует уникальный список Telegram-получателей из legacy source.

    Правила:

    1. Дубли по `telegram_user_id` схлопываются в одну цель.
    2. Некорректные `telegram_user_id` пропускаются.
    3. При фильтре `phone_filter_e164` остаются только совпадающие номера.
    """

    seen_ids: set[int] = set()
    targets: list[LegacyBroadcastTarget] = []
    invalid_id_rows = 0
    invalid_phone_rows = 0
    skipped_by_phone_filter = 0
    duplicate_id_rows = 0

    for record in source_records:
        raw_user_id = str(record.telegram_user_id).strip()
        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            invalid_id_rows += 1
            continue

        phone_e164: str | None = None
        if record.raw_phone:
            try:
                phone_e164 = normalize_phone(record.raw_phone)
            except ValueError:
                invalid_phone_rows += 1
                if phone_filter_e164 is not None:
                    continue

        if phone_filter_e164 is not None and phone_e164 != phone_filter_e164:
            skipped_by_phone_filter += 1
            continue

        if user_id in seen_ids:
            duplicate_id_rows += 1
            continue

        seen_ids.add(user_id)
        targets.append(
            LegacyBroadcastTarget(
                telegram_user_id=user_id,
                raw_phone=record.raw_phone,
                phone_e164=phone_e164,
            )
        )

    return LegacyBroadcastSelectionResult(
        targets=tuple(targets),
        invalid_telegram_id_rows=invalid_id_rows,
        invalid_phone_rows=invalid_phone_rows,
        skipped_by_phone_filter=skipped_by_phone_filter,
        duplicate_telegram_id_rows=duplicate_id_rows,
    )
