"""Инструменты рассылки для migrated legacy-пользователей Telegram.

Модуль решает прикладную задачу перехода со старого Telegram-бота:

1. Выбрать уникальные Telegram chat_id из legacy SQLite-источника.
2. Поддержать точечный фильтр по телефону.
3. Подготовить текст рассылки про новый интерфейс и альтернативные каналы (VK/MAX).

Фактическая отправка выполняется отдельным CLI-скриптом в `scripts/`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Sequence, AsyncIterable
from contextlib import asynccontextmanager

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import ReplyKeyboardRemove
from loguru import logger

from vtelemax.core import normalize_phone
from vtelemax.tools.legacy_telegram_migration import LegacyTelegramSourceRecord


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
    sent_cleanup: int  # количество успешных очисток кэша reply-кнопок
    sent_messages: int  # количество успешно отправленных приветственных сообщений
    failed_cleanup: int  # количество неудачных очисток
    failed_messages: int  # количество неудачных отправок сообщений
    retry_after_errors: int  # количество ошибок лимита (TelegramRetryAfter)
    forbidden_errors: int  # количество ошибок "бот заблокирован"
    chat_not_found_errors: int  # количество ошибок "chat not found"
    other_errors: int  # прочие ошибки


def build_default_legacy_broadcast_message() -> str:
    """Возвращает дефолтный текст рассылки о переходе на новый бот."""

    return (
        "👋 Привет! Мы обновили бота и перевели его на новое меню.\n\n"
        "Пожалуйста, нажмите команду /start, чтобы продолжить работу в новой версии.\n\n"
        "Доступны и альтернативные каналы:\n"
        "• VK: https://vk.me/club236296391\n"
        "• MAX: https://max.ru/id7203243481_bot\n\n"
        "Что есть в новом меню:\n"
        "• 💰 Мой баланс\n"
        "• 🪪 Карта\n"
        "• 🚚 Доставка\n"
        "• ❓ Мне только спросить\n"
        "• ✍️ Оставить отзыв\n"
        "• 👤 Профиль\n\n"
        "Если внизу чата остались старые кнопки, просто нажмите /start еще раз."
    )


async def send_legacy_broadcast(
    bot: Bot,
    targets: Sequence[LegacyBroadcastTarget],
    *,
    delay_seconds: float = 0.5,
    cleanup_before_message: bool = True,
) -> LegacyBroadcastSendResult:
    """Асинхронно отправляет очистку reply-кнопок и приветственное сообщение каждому target.

    Args:
        bot: экземпляр aiogram.Bot, инициализированный с токеном.
        targets: список получателей рассылки.
        delay_seconds: задержка между отправками (по умолчанию 0.5 сек).
        cleanup_before_message: если True, перед сообщением отправляет ReplyKeyboardRemove.

    Returns:
        LegacyBroadcastSendResult со статистикой отправки.
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

    # Логирование маскированного токена для диагностики
    token = getattr(bot, "token", None)
    if token:
        masked_token = f"{token[:5]}...{token[-5:]}" if len(token) > 10 else "***"
        logger.debug(f"Токен бота для рассылки: {masked_token}")
    else:
        logger.warning("Токен бота недоступен для логирования")

    broadcast_message = build_default_legacy_broadcast_message()

    for idx, target in enumerate(targets, start=1):
        chat_id = target.telegram_user_id
        logger.info(
            f"[{idx}/{total}] Отправка пользователю {chat_id} (телефон: {target.phone_e164 or 'нет'})"
        )

        # 1. Очистка кэша reply-кнопок
        if cleanup_before_message:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=".",  # минимальный текст, чтобы сообщение не было пустым
                    reply_markup=ReplyKeyboardRemove(),
                )
                sent_cleanup += 1
                logger.debug(f"   Очистка reply-кнопок отправлена для {chat_id}")
            except TelegramRetryAfter as e:
                retry_after_errors += 1
                logger.warning(f"   Лимит Telegram при очистке: {e}. Пропускаем пользователя.")
                # Ждем указанное время + дополнительная задержка
                wait_time = e.retry_after + delay_seconds
                await asyncio.sleep(wait_time)
                continue
            except TelegramForbiddenError:
                forbidden_errors += 1
                logger.warning(f"   Бот заблокирован пользователем {chat_id}. Пропускаем.")
                continue
            except TelegramBadRequest as e:
                failed_cleanup += 1
                error_message = str(e).lower()
                if "chat not found" in error_message:
                    chat_not_found_errors += 1
                    logger.warning(f"   Чат не найден для {chat_id} (очистка). Причина: {e}")
                else:
                    logger.warning(f"   Ошибка очистки для {chat_id}: {e}")
                # Продолжаем, возможно, сообщение всё равно отправится
            except Exception as e:
                other_errors += 1
                logger.warning(f"   Неожиданная ошибка очистки для {chat_id}: {e}")

        # 2. Отправка приветственного сообщения
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=broadcast_message,
                parse_mode=None,
                disable_web_page_preview=False,
            )
            sent_messages += 1
            logger.debug(f"   Приветственное сообщение отправлено для {chat_id}")
        except TelegramRetryAfter as e:
            retry_after_errors += 1
            logger.warning(f"   Лимит Telegram при отправке сообщения: {e}. Ждем.")
            wait_time = e.retry_after + delay_seconds
            await asyncio.sleep(wait_time)
            # Повторяем отправку сообщения после ожидания
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=broadcast_message,
                    parse_mode=None,
                    disable_web_page_preview=False,
                )
                sent_messages += 1
            except Exception:
                failed_messages += 1
        except TelegramForbiddenError:
            forbidden_errors += 1
            logger.warning(f"   Бот заблокирован пользователем {chat_id} при отправке сообщения.")
            continue
        except TelegramBadRequest as e:
            failed_messages += 1
            error_message = str(e).lower()
            if "chat not found" in error_message:
                chat_not_found_errors += 1
                logger.warning(f"   Чат не найден для {chat_id} (сообщение). Причина: {e}")
            else:
                logger.warning(f"   Ошибка отправки сообщения для {chat_id}: {e}")
        except Exception as e:
            other_errors += 1
            logger.warning(f"   Неожиданная ошибка отправки сообщения для {chat_id}: {e}")

        # Задержка между пользователями
        if idx < total:
            await asyncio.sleep(delay_seconds)

    logger.info(
        f"Рассылка завершена. Итог: "
        f"очистка {sent_cleanup}/{total}, "
        f"сообщения {sent_messages}/{total}, "
        f"ошибки лимита {retry_after_errors}, "
        f"заблокировано {forbidden_errors}, "
        f"чат не найден {chat_not_found_errors}, "
        f"прочие ошибки {other_errors}."
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
    3. При заданном фильтре `phone_filter_e164` в выборку попадают только записи
       с совпадающим нормализованным телефоном.
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
                    # При точечном фильтре по номеру такие строки точно не подходят.
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

