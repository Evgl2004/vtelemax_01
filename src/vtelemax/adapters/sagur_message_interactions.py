"""Транзакционная граница приёма нажатий интерактивных сообщений SAGUR."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.core.sagur_message_interactions import (
    SagurMessageInteractionIngress,
    SagurMessageInteractionInsertResult,
)
from vtelemax.infrastructure.postgres.sagur_message_interactions_repository import (
    SQLAlchemySagurMessageInteractionsRepository,
)


class SagurMessageInteractionStorageError(RuntimeError):
    """PostgreSQL не подтвердил долговечную фиксацию нажатия."""


class SagurMessageInteractionService:
    """Сохраняет факт до ответа платформе и отдельно фиксирует действие."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record_event(
        self,
        ingress: SagurMessageInteractionIngress,
    ) -> SagurMessageInteractionInsertResult:
        """Создаёт либо возвращает событие и фиксирует транзакцию до ответа бота."""

        try:
            with self._session_factory() as session:
                repository = SQLAlchemySagurMessageInteractionsRepository(session)
                result = repository.record_event(ingress)
                session.commit()
                return result
        except Exception as error:  # noqa: BLE001
            logger.bind(
                platform=ingress.platform,
                component="sagur_message_interactions",
                stage="durable_insert",
            ).exception(
                "Не удалось долговечно сохранить нажатие SAGUR; error_type={error_type}.",
                error_type=type(error).__name__,
            )
            raise SagurMessageInteractionStorageError(
                "Не удалось долговечно сохранить нажатие SAGUR."
            ) from error

    def mark_user_action_succeeded(
        self,
        event_id: UUID,
        *,
        attempted_at: datetime,
    ) -> None:
        """Фиксирует успешное пользовательское действие отдельной транзакцией."""

        with self._session_factory() as session:
            repository = SQLAlchemySagurMessageInteractionsRepository(session)
            if not repository.mark_user_action_succeeded(
                event_id,
                attempted_at=attempted_at,
            ):
                raise SagurMessageInteractionStorageError("Событие пользовательского действия не найдено.")
            session.commit()

    def mark_user_action_failed(
        self,
        event_id: UUID,
        *,
        attempted_at: datetime,
        error_code: str,
        error_text: str,
    ) -> None:
        """Фиксирует ошибку пользовательского действия отдельной транзакцией."""

        with self._session_factory() as session:
            repository = SQLAlchemySagurMessageInteractionsRepository(session)
            if not repository.mark_user_action_failed(
                event_id,
                attempted_at=attempted_at,
                error_code=error_code,
                error_text=error_text,
            ):
                raise SagurMessageInteractionStorageError("Событие пользовательского действия не найдено.")
            session.commit()


def platform_callback_fingerprint(callback_id: str) -> str:
    """Возвращает короткий безопасный отпечаток без записи исходного идентификатора."""

    return hashlib.sha256(callback_id.encode("utf-8")).hexdigest()[:16]


def utc_now() -> datetime:
    """Возвращает текущее серверное время UTC для границ пользовательского действия."""

    return datetime.now(timezone.utc)
