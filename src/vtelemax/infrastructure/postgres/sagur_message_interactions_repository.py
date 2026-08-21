"""PostgreSQL-репозиторий событий нажатия кнопок сообщений SAGUR."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, literal, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from vtelemax.core.sagur_message_interactions import (
    SAGUR_INTERACTION_ACTIONS,
    SAGUR_INTERACTION_ID_MAX,
    SagurMessageInteractionDeliveryStatus,
    SagurMessageInteractionDeliveryTask,
    SagurMessageInteractionEvent,
    SagurMessageInteractionIngress,
    SagurMessageInteractionInsertResult,
    SagurMessageInteractionQueueObservation,
    SagurMessageInteractionUserActionStatus,
)

from .schema import SagurMessageInteractionEventRow


_SUPPORTED_PLATFORMS = frozenset({"telegram", "vk", "max"})
_SUCCESSFUL_DELIVERY_RESULTS = frozenset({"accepted", "duplicate", "rating_already_recorded"})
_MAX_ERROR_TEXT_LENGTH = 2_000


class SQLAlchemySagurMessageInteractionsRepository:
    """Хранит неизменяемый факт нажатия и изменяемые состояния обработки."""

    def __init__(
        self,
        session: Session,
        *,
        event_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._session = session
        self._event_id_factory = event_id_factory

    def record_event(
        self,
        ingress: SagurMessageInteractionIngress,
        *,
        now_utc: datetime | None = None,
    ) -> SagurMessageInteractionInsertResult:
        """Атомарно вставляет событие без предварительного поиска по истории.

        Точное чтение по составному уникальному ключу выполняется только после
        конфликта вставки. Оно возвращает ранее созданный ``event_id`` и
        одновременно проверяет, не изменились ли неизменяемые поля события.
        """

        self._validate_ingress(ingress)
        now = _utc_now(now_utc)
        event_id = self._event_id_factory()
        values = {
            "event_id": event_id,
            "platform": ingress.platform,
            "bot_scope": ingress.bot_scope,
            "platform_callback_id": ingress.platform_callback_id,
            "interaction_id": ingress.interaction_id,
            "action": ingress.action,
            "occurred_at": now,
            "provider_message_id": ingress.provider_message_id,
            "delivery_status": SagurMessageInteractionDeliveryStatus.PENDING.value,
            "delivery_attempts": 0,
            "next_attempt_at": now,
            "user_action_status": SagurMessageInteractionUserActionStatus.PENDING.value,
            "created_at": now,
            "updated_at": now,
        }
        statement = self._build_atomic_insert(values)
        inserted_marker = self._session.execute(statement).scalar_one_or_none()
        if inserted_marker is not None:
            return SagurMessageInteractionInsertResult(
                event=_event_from_values(values),
                created=True,
                immutable_fields_match=True,
            )

        row = self._find_by_platform_key(ingress)
        if row is None:
            raise RuntimeError("Событие не найдено после конфликта уникального ключа.")
        immutable_fields_match = (
            row.interaction_id == ingress.interaction_id
            and row.action == ingress.action
            and row.provider_message_id == ingress.provider_message_id
        )
        return SagurMessageInteractionInsertResult(
            event=_event_from_row(row),
            created=False,
            immutable_fields_match=immutable_fields_match,
        )

    def select_due_events_for_update(
        self,
        *,
        limit: int,
        now_utc: datetime | None = None,
    ) -> tuple[SagurMessageInteractionDeliveryTask, ...]:
        """Блокирует короткий список готовых событий без изменения их статуса."""

        now = _utc_now(now_utc)
        safe_limit = max(1, min(int(limit), 100))
        statement = (
            select(SagurMessageInteractionEventRow)
            .where(
                SagurMessageInteractionEventRow.delivery_status.in_(
                    (
                        SagurMessageInteractionDeliveryStatus.PENDING.value,
                        SagurMessageInteractionDeliveryStatus.RETRY_SCHEDULED.value,
                    )
                ),
                SagurMessageInteractionEventRow.next_attempt_at <= now,
            )
            .order_by(
                SagurMessageInteractionEventRow.next_attempt_at.asc(),
                SagurMessageInteractionEventRow.occurred_at.asc(),
            )
            .limit(safe_limit)
            .with_for_update(skip_locked=True)
        )
        rows = self._session.execute(statement).scalars().all()
        return tuple(
            SagurMessageInteractionDeliveryTask(
                event_id=row.event_id,
                interaction_id=row.interaction_id,
                action=row.action,
                occurred_at=_aware_utc(row.occurred_at),
                provider_message_id=row.provider_message_id,
                delivery_attempts=row.delivery_attempts + 1,
            )
            for row in rows
        )

    def read_active_queue_observation(self) -> SagurMessageInteractionQueueObservation:
        """Считает только активные строки и время самого старого нажатия.

        Предикат совпадает с частичным индексом активной очереди. Доставленные и
        заблокированные исторические строки в агрегатную выборку не входят.
        """

        statement = select(
            func.count(SagurMessageInteractionEventRow.event_id),
            func.min(SagurMessageInteractionEventRow.occurred_at),
        ).where(
            SagurMessageInteractionEventRow.delivery_status.in_(
                (
                    SagurMessageInteractionDeliveryStatus.PENDING.value,
                    SagurMessageInteractionDeliveryStatus.RETRY_SCHEDULED.value,
                )
            )
        )
        active_count, oldest_occurred_at = self._session.execute(statement).one()
        return SagurMessageInteractionQueueObservation(
            active_count=int(active_count or 0),
            oldest_occurred_at=(
                _aware_utc(oldest_occurred_at) if oldest_occurred_at is not None else None
            ),
        )

    def mark_processing(
        self,
        event_ids: Sequence[UUID],
        *,
        lease_id: UUID,
        now_utc: datetime | None = None,
    ) -> int:
        """Закрепляет выбранный набор за одной уникальной попыткой доставки."""

        if not event_ids:
            return 0
        now = _utc_now(now_utc)
        statement = (
            update(SagurMessageInteractionEventRow)
            .where(
                SagurMessageInteractionEventRow.event_id.in_(tuple(event_ids)),
                SagurMessageInteractionEventRow.delivery_status.in_(
                    (
                        SagurMessageInteractionDeliveryStatus.PENDING.value,
                        SagurMessageInteractionDeliveryStatus.RETRY_SCHEDULED.value,
                    )
                ),
            )
            .values(
                delivery_status=SagurMessageInteractionDeliveryStatus.PROCESSING.value,
                delivery_attempts=SagurMessageInteractionEventRow.delivery_attempts + 1,
                locked_at=now,
                delivery_lease_id=lease_id,
                updated_at=now,
            )
        )
        result = self._session.execute(statement)
        return int(result.rowcount or 0)

    def mark_delivered(
        self,
        event_id: UUID,
        *,
        lease_id: UUID,
        result: str,
        now_utc: datetime | None = None,
    ) -> bool:
        """Подтверждает только один из трёх успешных результатов SAGUR."""

        if result not in _SUCCESSFUL_DELIVERY_RESULTS:
            raise ValueError("Неподдерживаемый успешный результат SAGUR.")
        now = _utc_now(now_utc)
        return self._update_claimed_one(
            event_id,
            lease_id=lease_id,
            delivery_status=SagurMessageInteractionDeliveryStatus.DELIVERED.value,
            delivery_result=result,
            delivered_at=now,
            locked_at=None,
            delivery_lease_id=None,
            delivery_error_code=None,
            delivery_error_text=None,
            updated_at=now,
        )

    def schedule_retry(
        self,
        event_id: UUID,
        *,
        lease_id: UUID,
        error_code: str,
        error_text: str,
        next_attempt_at: datetime,
        now_utc: datetime | None = None,
    ) -> bool:
        """Сохраняет временную ошибку и планирует следующую попытку без удаления."""

        now = _utc_now(now_utc)
        return self._update_claimed_one(
            event_id,
            lease_id=lease_id,
            delivery_status=SagurMessageInteractionDeliveryStatus.RETRY_SCHEDULED.value,
            next_attempt_at=_aware_utc(next_attempt_at),
            locked_at=None,
            delivery_lease_id=None,
            delivery_error_code=str(error_code)[:128],
            delivery_error_text=_trim_error_text(error_text),
            updated_at=now,
        )

    def mark_blocked(
        self,
        event_id: UUID,
        *,
        lease_id: UUID,
        error_code: str,
        error_text: str,
        now_utc: datetime | None = None,
    ) -> bool:
        """Переводит постоянный отказ в диагностируемое состояние без удаления."""

        now = _utc_now(now_utc)
        return self._update_claimed_one(
            event_id,
            lease_id=lease_id,
            delivery_status=SagurMessageInteractionDeliveryStatus.BLOCKED.value,
            locked_at=None,
            delivery_lease_id=None,
            delivery_error_code=str(error_code)[:128],
            delivery_error_text=_trim_error_text(error_text),
            updated_at=now,
        )

    def mark_user_action_succeeded(
        self,
        event_id: UUID,
        *,
        attempted_at: datetime,
        now_utc: datetime | None = None,
    ) -> bool:
        """Фиксирует успешное изменение интерфейса или открытие раздела."""

        now = _utc_now(now_utc)
        return self._update_one(
            event_id,
            user_action_status=SagurMessageInteractionUserActionStatus.SUCCEEDED.value,
            user_action_attempted_at=_aware_utc(attempted_at),
            user_action_finished_at=now,
            user_action_error_code=None,
            user_action_error_text=None,
            updated_at=now,
        )

    def mark_user_action_failed(
        self,
        event_id: UUID,
        *,
        attempted_at: datetime,
        error_code: str,
        error_text: str,
        now_utc: datetime | None = None,
    ) -> bool:
        """Фиксирует ошибку действия отдельно от независимой доставки в SAGUR."""

        now = _utc_now(now_utc)
        return self._update_one(
            event_id,
            user_action_status=SagurMessageInteractionUserActionStatus.FAILED.value,
            user_action_attempted_at=_aware_utc(attempted_at),
            user_action_finished_at=now,
            user_action_error_code=str(error_code)[:128],
            user_action_error_text=_trim_error_text(error_text),
            updated_at=now,
        )

    def release_stale_processing(
        self,
        *,
        lock_timeout_seconds: int,
        now_utc: datetime | None = None,
    ) -> int:
        """Возвращает зависшие попытки доставки в активную очередь."""

        now = _utc_now(now_utc)
        deadline = now - timedelta(seconds=max(1, int(lock_timeout_seconds)))
        statement = (
            update(SagurMessageInteractionEventRow)
            .where(
                SagurMessageInteractionEventRow.delivery_status
                == SagurMessageInteractionDeliveryStatus.PROCESSING.value,
                SagurMessageInteractionEventRow.locked_at <= deadline,
            )
            .values(
                delivery_status=SagurMessageInteractionDeliveryStatus.RETRY_SCHEDULED.value,
                next_attempt_at=now,
                locked_at=None,
                delivery_lease_id=None,
                delivery_error_code="processing_timeout",
                delivery_error_text="Истекло время владения попыткой доставки.",
                updated_at=now,
            )
        )
        result = self._session.execute(statement)
        return int(result.rowcount or 0)

    def _build_atomic_insert(self, values: dict[str, object]):
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name == "postgresql":
            insert_statement = postgresql_insert(SagurMessageInteractionEventRow)
        elif dialect_name == "sqlite":
            insert_statement = sqlite_insert(SagurMessageInteractionEventRow)
        else:
            raise RuntimeError(f"Неподдерживаемый диалект базы данных: {dialect_name}.")
        return (
            insert_statement.values(**values)
            .on_conflict_do_nothing(
                index_elements=("platform", "bot_scope", "platform_callback_id")
            )
            # Возвращаем нейтральный признак, а не UUID. SQLite объявляет тип
            # UUID с числовым сродством и может исказить значение в RETURNING;
            # сам UUID события уже создан выше и повторное чтение не требуется.
            .returning(literal(1))
        )

    def _find_by_platform_key(
        self,
        ingress: SagurMessageInteractionIngress,
    ) -> SagurMessageInteractionEventRow | None:
        statement = select(SagurMessageInteractionEventRow).where(
            SagurMessageInteractionEventRow.platform == ingress.platform,
            SagurMessageInteractionEventRow.bot_scope == ingress.bot_scope,
            SagurMessageInteractionEventRow.platform_callback_id == ingress.platform_callback_id,
        )
        return self._session.execute(statement).scalars().one_or_none()

    def _update_one(self, event_id: UUID, **values: object) -> bool:
        statement = (
            update(SagurMessageInteractionEventRow)
            .where(SagurMessageInteractionEventRow.event_id == event_id)
            .values(**values)
        )
        result = self._session.execute(statement)
        return bool(result.rowcount)

    def _update_claimed_one(
        self,
        event_id: UUID,
        *,
        lease_id: UUID,
        **values: object,
    ) -> bool:
        """Изменяет доставку только пока строкой владеет указанная аренда."""

        statement = (
            update(SagurMessageInteractionEventRow)
            .where(
                SagurMessageInteractionEventRow.event_id == event_id,
                SagurMessageInteractionEventRow.delivery_status
                == SagurMessageInteractionDeliveryStatus.PROCESSING.value,
                SagurMessageInteractionEventRow.delivery_lease_id == lease_id,
            )
            .values(**values)
        )
        result = self._session.execute(statement)
        return bool(result.rowcount)

    @staticmethod
    def _validate_ingress(ingress: SagurMessageInteractionIngress) -> None:
        if ingress.platform not in _SUPPORTED_PLATFORMS:
            raise ValueError("Платформа события не поддерживается.")
        if not ingress.bot_scope or len(ingress.bot_scope) > 128:
            raise ValueError("Область бота отсутствует или превышает 128 символов.")
        if not ingress.platform_callback_id or len(ingress.platform_callback_id) > 512:
            raise ValueError("Идентификатор обратного вызова отсутствует или слишком длинный.")
        if not (1 <= ingress.interaction_id <= SAGUR_INTERACTION_ID_MAX):
            raise ValueError("Идентификатор интерактивности находится вне диапазона BIGINT.")
        if ingress.action not in SAGUR_INTERACTION_ACTIONS:
            raise ValueError("Действие интерактивной кнопки не поддерживается.")
        if ingress.provider_message_id is not None and len(ingress.provider_message_id) > 255:
            raise ValueError("Идентификатор сообщения платформы превышает 255 символов.")


def _event_from_values(values: dict[str, object]) -> SagurMessageInteractionEvent:
    return SagurMessageInteractionEvent(
        event_id=values["event_id"],  # type: ignore[arg-type]
        platform=values["platform"],  # type: ignore[arg-type]
        bot_scope=values["bot_scope"],  # type: ignore[arg-type]
        platform_callback_id=values["platform_callback_id"],  # type: ignore[arg-type]
        interaction_id=values["interaction_id"],  # type: ignore[arg-type]
        action=values["action"],  # type: ignore[arg-type]
        occurred_at=values["occurred_at"],  # type: ignore[arg-type]
        provider_message_id=values["provider_message_id"],  # type: ignore[arg-type]
    )


def _event_from_row(row: SagurMessageInteractionEventRow) -> SagurMessageInteractionEvent:
    return SagurMessageInteractionEvent(
        event_id=row.event_id,
        platform=row.platform,
        bot_scope=row.bot_scope,
        platform_callback_id=row.platform_callback_id,
        interaction_id=row.interaction_id,
        action=row.action,
        occurred_at=_aware_utc(row.occurred_at),
        provider_message_id=row.provider_message_id,
    )


def _trim_error_text(value: str) -> str:
    return str(value)[:_MAX_ERROR_TEXT_LENGTH]


def _utc_now(value: datetime | None = None) -> datetime:
    return _aware_utc(value or datetime.now(timezone.utc))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
