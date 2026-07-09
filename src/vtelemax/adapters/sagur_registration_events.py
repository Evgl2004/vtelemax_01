"""Сервис, HTTP-клиент и воркеры исходящих событий регистрации SAGUR."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit

import aiohttp
from loguru import logger
from sqlalchemy.orm import Session

from vtelemax.core import (
    GetVirtualCardUseCase,
    LoyaltyCustomer,
    LoyaltyCustomerUpsertData,
    LoyaltyGateway,
    LoyaltyGatewayError,
    LoyaltyMenuResult,
    SagurRegistrationContext,
    SagurRegistrationEventTask,
)
from vtelemax.infrastructure.postgres.sagur_registration_events_repository import (
    SQLAlchemySagurRegistrationEventsRepository,
)

_REGISTRATION_ENDPOINT_PATH = "/internal/integration/v1/vtelemax/registration-events"


class _RepositoryRegistrationObserver:
    """Пишет факты iikoCard в запись регистра SAGUR-регистрации."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        record_id,
        recovery_first_delay_seconds: int,
    ) -> None:
        self._session_factory = session_factory
        self._record_id = record_id
        self._recovery_first_delay_seconds = max(int(recovery_first_delay_seconds), 1)

    def mark_lookup_failed(self, error: LoyaltyGatewayError) -> None:
        next_attempt_at = datetime.now(timezone.utc) + timedelta(
            seconds=self._recovery_first_delay_seconds
        )
        self._run(
            lambda repository: repository.mark_lookup_failed(
                self._record_id,
                error_code=_loyalty_error_code(error),
                error_text=str(error),
                next_attempt_at=next_attempt_at,
            )
        )

    def mark_existing_customer(self, customer_id: str) -> None:
        self._run(
            lambda repository: repository.mark_existing_customer(
                self._record_id,
                customer_id=customer_id,
            )
        )

    def mark_create_started(self) -> None:
        self._run(lambda repository: repository.mark_create_started(self._record_id))

    def mark_created_customer(self, customer_id: str) -> None:
        self._run(
            lambda repository: repository.mark_created_customer(
                self._record_id,
                customer_id=customer_id,
            )
        )

    def mark_create_result_unknown(self, error: LoyaltyGatewayError) -> None:
        next_attempt_at = datetime.now(timezone.utc) + timedelta(
            seconds=self._recovery_first_delay_seconds
        )
        self._run(
            lambda repository: repository.mark_create_result_unknown(
                self._record_id,
                error_code=_loyalty_error_code(error),
                error_text=str(error),
                next_attempt_at=next_attempt_at,
            )
        )

    def mark_create_failed_terminal(self, error: LoyaltyGatewayError) -> None:
        self._run(
            lambda repository: repository.mark_create_failed_terminal(
                self._record_id,
                error_code=_loyalty_error_code(error),
                error_text=str(error),
            )
        )

    def _run(
        self,
        operation: Callable[[SQLAlchemySagurRegistrationEventsRepository], None],
    ) -> None:
        session = self._session_factory()
        try:
            operation(SQLAlchemySagurRegistrationEventsRepository(session))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


@dataclass(slots=True)
class SagurRegistrationFinalizationService:
    """Обертка финальной iikoCard-синхронизации, которая ведет SAGUR-регистр."""

    session_factory: Callable[[], Session]
    virtual_card_use_case: GetVirtualCardUseCase
    recovery_first_delay_seconds: int = 120

    def execute(
        self,
        *,
        context: SagurRegistrationContext,
        profile: LoyaltyCustomerUpsertData | None,
    ) -> LoyaltyMenuResult:
        """Выполняет текущий iikoCard use-case и создает pending-событие при успехе."""

        record_id = self._ensure_record(context)
        observer = _RepositoryRegistrationObserver(
            session_factory=self.session_factory,
            record_id=record_id,
            recovery_first_delay_seconds=self.recovery_first_delay_seconds,
        )
        result = self.virtual_card_use_case.execute(
            phone_e164=context.phone_e164,
            profile=profile,
            registration_observer=observer,
        )
        if result.status == "virtual_card" and result.customer_id:
            self._create_pending_event_if_required(record_id)
        return result

    def _ensure_record(self, context: SagurRegistrationContext):
        session = self.session_factory()
        try:
            repository = SQLAlchemySagurRegistrationEventsRepository(session)
            record_id = repository.ensure_iiko_lookup_started(context)
            session.commit()
            return record_id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _create_pending_event_if_required(self, record_id) -> None:
        session = self.session_factory()
        try:
            repository = SQLAlchemySagurRegistrationEventsRepository(session)
            repository.create_pending_event_if_required(record_id)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


@dataclass(frozen=True, slots=True)
class SagurRegistrationDeliveryOutcome:
    """Результат HTTP-отправки события регистрации в SAGUR."""

    status: Literal["accepted", "conflict", "retry", "failed_terminal"]
    duplicate: bool = False
    http_status: int | None = None
    error_code: str | None = None
    error_text: str | None = None


@dataclass(slots=True)
class SagurRegistrationHttpClient:
    """HTTP-клиент исходящего события регистрации vtelemax -> SAGUR."""

    endpoint: str
    hmac_secret: str
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.endpoint.strip():
            raise ValueError("SAGUR endpoint регистрации не должен быть пустым.")
        if not self.hmac_secret.strip():
            raise ValueError("HMAC-секрет исходящего события регистрации SAGUR не задан.")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds должен быть больше 0.")

    async def send(self, task: SagurRegistrationEventTask) -> SagurRegistrationDeliveryOutcome:
        """Отправляет сохраненные байты payload с подписью HMAC."""

        timestamp = str(int(time.time()))
        path = _canonical_path(self.endpoint)
        signature = build_vtelemax_registration_signature(
            secret=self.hmac_secret,
            method="POST",
            path=path,
            timestamp=timestamp,
            payload_body=task.payload_body,
        )
        headers = {
            "Content-Type": "application/json",
            "X-Vtelemax-Request-Id": task.request_id,
            "X-Vtelemax-Timestamp": timestamp,
            "X-Vtelemax-Signature": signature,
        }
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.endpoint, data=task.payload_body, headers=headers) as response:
                    data = await _read_json_response(response)
                    return _classify_sagur_response(response.status, data)
        except (TimeoutError, aiohttp.ClientError) as error:
            return SagurRegistrationDeliveryOutcome(
                status="retry",
                error_code="network_error",
                error_text=str(error),
            )


@dataclass(slots=True)
class SagurRegistrationEventsProcessor:
    """Обрабатывает отправку pending-событий регистрации в SAGUR."""

    session_factory: Callable[[], Session]
    http_client: SagurRegistrationHttpClient
    max_attempts: int = 8
    lock_timeout_seconds: int = 300

    async def process_once(self, *, limit: int = 20) -> tuple[int, int, int, int]:
        """Выполняет один проход отправки.

        Возвращает `(sent_count, conflict_count, retry_count, failed_count)`.
        """

        self._release_stale_processing()
        tasks = self._pull_tasks(limit=limit)
        sent_count = 0
        conflict_count = 0
        retry_count = 0
        failed_count = 0

        for task in tasks:
            outcome = await self.http_client.send(task)
            if outcome.status == "accepted":
                self._mark_sent(task, outcome)
                sent_count += 1
            elif outcome.status == "conflict":
                self._mark_conflict(task, outcome)
                conflict_count += 1
            elif outcome.status == "failed_terminal":
                self._schedule_retry_or_fail(task, outcome)
                failed_count += 1
            else:
                self._schedule_retry_or_fail(task, outcome)
                retry_count += 1

        return sent_count, conflict_count, retry_count, failed_count

    def _pull_tasks(self, *, limit: int) -> tuple[SagurRegistrationEventTask, ...]:
        session = self.session_factory()
        try:
            repository = SQLAlchemySagurRegistrationEventsRepository(session)
            tasks = repository.pull_pending_event_tasks(limit=limit)
            session.commit()
            return tasks
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _release_stale_processing(self) -> None:
        session = self.session_factory()
        try:
            repository = SQLAlchemySagurRegistrationEventsRepository(session)
            released = repository.release_stale_processing(
                lock_timeout_seconds=self.lock_timeout_seconds
            )
            session.commit()
            if released:
                logger.bind(component="sagur_registration_events", stage="release_stale").warning(
                    "Возвращены зависшие SAGUR registration-события. count={count}.",
                    count=released,
                )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _mark_sent(
        self,
        task: SagurRegistrationEventTask,
        outcome: SagurRegistrationDeliveryOutcome,
    ) -> None:
        self._run_repository_update(
            lambda repository: repository.mark_event_sent(
                task.record_id,
                duplicate=outcome.duplicate,
            )
        )

    def _mark_conflict(
        self,
        task: SagurRegistrationEventTask,
        outcome: SagurRegistrationDeliveryOutcome,
    ) -> None:
        self._run_repository_update(
            lambda repository: repository.mark_event_conflict(
                task.record_id,
                error_code=outcome.error_code or "event_id_payload_conflict",
                error_text=outcome.error_text or "SAGUR вернул конфликт event_id/payload.",
            )
        )

    def _schedule_retry_or_fail(
        self,
        task: SagurRegistrationEventTask,
        outcome: SagurRegistrationDeliveryOutcome,
    ) -> None:
        next_attempt_at = _delivery_next_attempt(task.attempts)
        self._run_repository_update(
            lambda repository: repository.schedule_event_retry(
                task.record_id,
                error_code=outcome.error_code or "sagur_delivery_error",
                error_text=outcome.error_text or "SAGUR registration event delivery failed.",
                next_attempt_at=next_attempt_at,
                max_attempts=self.max_attempts,
            )
        )

    def _run_repository_update(
        self,
        operation: Callable[[SQLAlchemySagurRegistrationEventsRepository], None],
    ) -> None:
        session = self.session_factory()
        try:
            operation(SQLAlchemySagurRegistrationEventsRepository(session))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


@dataclass(slots=True)
class SagurRegistrationRecoveryProcessor:
    """Контрольный поиск iikoCard для записей с неизвестным результатом создания."""

    session_factory: Callable[[], Session]
    loyalty_gateway: LoyaltyGateway
    max_attempts: int = 3

    async def process_once(self, *, limit: int = 10) -> tuple[int, int, int]:
        """Выполняет один проход восстановления.

        Возвращает `(found_count, retry_count, manual_count)`.
        """

        tasks = self._pull_tasks(limit=limit)
        found_count = 0
        retry_count = 0
        manual_count = 0
        for task in tasks:
            try:
                customer = await asyncio.to_thread(
                    self.loyalty_gateway.get_customer_info,
                    task.phone_e164,
                )
            except LoyaltyGatewayError as error:
                if self._schedule_recovery(task, error_code=_loyalty_error_code(error), error_text=str(error)):
                    retry_count += 1
                else:
                    manual_count += 1
                continue
            except Exception as error:  # noqa: BLE001
                if self._schedule_recovery(
                    task,
                    error_code="unexpected_recovery_error",
                    error_text=str(error),
                ):
                    retry_count += 1
                else:
                    manual_count += 1
                continue

            if customer is None:
                if self._schedule_recovery(
                    task,
                    error_code="customer_not_found",
                    error_text="Контрольный поиск iikoCard не нашел гостя.",
                ):
                    retry_count += 1
                else:
                    manual_count += 1
                continue

            self._mark_recovered(task, customer)
            found_count += 1

        return found_count, retry_count, manual_count

    def _pull_tasks(self, *, limit: int) -> tuple:
        session = self.session_factory()
        try:
            repository = SQLAlchemySagurRegistrationEventsRepository(session)
            tasks = repository.pull_due_recovery_tasks(limit=limit)
            session.commit()
            return tasks
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _mark_recovered(self, task, customer: LoyaltyCustomer) -> None:
        session = self.session_factory()
        try:
            repository = SQLAlchemySagurRegistrationEventsRepository(session)
            repository.mark_recovery_customer_found(
                task.record_id,
                customer_id=customer.customer_id,
            )
            repository.create_pending_event_if_required(task.record_id)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _schedule_recovery(self, task, *, error_code: str, error_text: str) -> bool:
        next_attempt_at = _recovery_next_attempt(task.recovery_attempts)
        session = self.session_factory()
        try:
            repository = SQLAlchemySagurRegistrationEventsRepository(session)
            repository.schedule_recovery_retry(
                task.record_id,
                error_code=error_code,
                error_text=error_text,
                next_attempt_at=next_attempt_at,
                max_attempts=self.max_attempts,
            )
            session.commit()
            return task.recovery_attempts < self.max_attempts
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


@dataclass(slots=True)
class PeriodicSagurRegistrationEventsWorker:
    """Периодический worker отправки и восстановления SAGUR-регистраций."""

    delivery_processor: SagurRegistrationEventsProcessor
    recovery_processor: SagurRegistrationRecoveryProcessor | None = None
    interval_seconds: float = 60.0
    batch_limit: int = 20
    recovery_interval_seconds: float = 300.0
    recovery_batch_limit: int = 10
    lock: asyncio.Lock | None = None
    _stop_event: asyncio.Event = field(init=False, repr=False)
    _next_recovery_at: datetime = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds должен быть больше 0.")
        if self.batch_limit <= 0:
            raise ValueError("batch_limit должен быть больше 0.")
        if self.recovery_interval_seconds <= 0:
            raise ValueError("recovery_interval_seconds должен быть больше 0.")
        if self.recovery_batch_limit <= 0:
            raise ValueError("recovery_batch_limit должен быть больше 0.")
        self._stop_event = asyncio.Event()
        self._next_recovery_at = datetime.now(timezone.utc)

    async def run_forever(self) -> None:
        """Запускает периодический цикл до сигнала остановки."""

        worker_logger = logger.bind(component="sagur_registration_events_worker", stage="run_forever")
        worker_logger.info(
            "SAGUR registration worker запущен. interval={interval}s, limit={limit}.",
            interval=self.interval_seconds,
            limit=self.batch_limit,
        )
        try:
            while not self._stop_event.is_set():
                await self.process_once()
                await self._wait_for_next_tick()
        except asyncio.CancelledError:
            worker_logger.info("SAGUR registration worker остановлен по отмене задачи.")
            raise
        finally:
            worker_logger.info("SAGUR registration worker завершил работу.")

    async def process_once(self) -> tuple[int, int, int, int]:
        """Выполняет один периодический проход."""

        if self.lock is None:
            return await self._process_once_internal()
        if self.lock.locked():
            logger.bind(component="sagur_registration_events_worker", stage="lock_wait").debug(
                "Пропуск прохода: предыдущая обработка SAGUR registration еще выполняется."
            )
            return 0, 0, 0, 0
        async with self.lock:
            return await self._process_once_internal()

    async def shutdown(self) -> None:
        """Запрашивает мягкую остановку worker."""

        if self._stop_event.is_set():
            return
        logger.bind(component="sagur_registration_events_worker", stage="shutdown").info(
            "Получен сигнал остановки SAGUR registration worker."
        )
        self._stop_event.set()

    async def _process_once_internal(self) -> tuple[int, int, int, int]:
        worker_logger = logger.bind(component="sagur_registration_events_worker", stage="process_once")
        try:
            result = await self.delivery_processor.process_once(limit=self.batch_limit)
            await self._maybe_run_recovery()
        except Exception:  # noqa: BLE001
            worker_logger.exception("Ошибка обработки SAGUR registration-регистра.")
            return 0, 0, 0, 0
        sent_count, conflict_count, retry_count, failed_count = result
        worker_logger.info(
            "Обработка SAGUR registration завершена. sent={sent}, conflict={conflict}, retry={retry}, failed={failed}.",
            sent=sent_count,
            conflict=conflict_count,
            retry=retry_count,
            failed=failed_count,
        )
        return result

    async def _maybe_run_recovery(self) -> None:
        if self.recovery_processor is None:
            return
        now = datetime.now(timezone.utc)
        if now < self._next_recovery_at:
            return
        found_count, retry_count, manual_count = await self.recovery_processor.process_once(
            limit=self.recovery_batch_limit
        )
        logger.bind(component="sagur_registration_events_worker", stage="recovery").info(
            "Восстановление SAGUR registration завершено. found={found}, retry={retry}, manual={manual}.",
            found=found_count,
            retry=retry_count,
            manual=manual_count,
        )
        self._next_recovery_at = now + timedelta(seconds=self.recovery_interval_seconds)

    async def _wait_for_next_tick(self) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)


def build_vtelemax_registration_canonical_string(
    *,
    method: str,
    path: str,
    timestamp: str,
    payload_body: bytes,
) -> str:
    """Собирает каноническую строку подписи vtelemax -> SAGUR."""

    body_hash = hashlib.sha256(payload_body).hexdigest()
    return "\n".join((method.upper(), path, timestamp, body_hash))


def build_vtelemax_registration_signature(
    *,
    secret: str,
    method: str,
    path: str,
    timestamp: str,
    payload_body: bytes,
) -> str:
    """Считает HMAC-SHA256 подпись исходящего события регистрации."""

    canonical = build_vtelemax_registration_canonical_string(
        method=method,
        path=path,
        timestamp=timestamp,
        payload_body=payload_body,
    )
    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def _read_json_response(response: aiohttp.ClientResponse) -> dict[str, object]:
    with contextlib.suppress(Exception):
        data = await response.json(content_type=None)
        if isinstance(data, dict):
            return data
    text = await response.text()
    return {"message": text}


def _classify_sagur_response(
    http_status: int,
    data: dict[str, object],
) -> SagurRegistrationDeliveryOutcome:
    error_code = _optional_str(data.get("code"))
    error_text = _optional_str(data.get("message"))
    if http_status == 202:
        return SagurRegistrationDeliveryOutcome(
            status="accepted",
            duplicate=bool(data.get("duplicate")),
            http_status=http_status,
        )
    if http_status == 409 and error_code == "event_id_payload_conflict":
        return SagurRegistrationDeliveryOutcome(
            status="conflict",
            http_status=http_status,
            error_code=error_code,
            error_text=error_text,
        )
    if http_status >= 500 or error_code == "callback_disabled":
        return SagurRegistrationDeliveryOutcome(
            status="retry",
            http_status=http_status,
            error_code=error_code or f"http_{http_status}",
            error_text=error_text,
        )
    return SagurRegistrationDeliveryOutcome(
        status="failed_terminal",
        http_status=http_status,
        error_code=error_code or f"http_{http_status}",
        error_text=error_text,
    )


def _canonical_path(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    path = parsed.path or _REGISTRATION_ENDPOINT_PATH
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def _delivery_next_attempt(attempts: int) -> datetime:
    safe_attempts = max(int(attempts), 1)
    if safe_attempts == 1:
        delay_seconds = 60
    elif safe_attempts == 2:
        delay_seconds = 5 * 60
    elif safe_attempts == 3:
        delay_seconds = 15 * 60
    else:
        delay_seconds = 30 * 60
    return datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)


def _recovery_next_attempt(attempts: int) -> datetime:
    safe_attempts = max(int(attempts), 1)
    if safe_attempts == 1:
        delay_seconds = 10 * 60
    elif safe_attempts == 2:
        delay_seconds = 30 * 60
    else:
        delay_seconds = 60 * 60
    return datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)


def _loyalty_error_code(error: LoyaltyGatewayError) -> str:
    return str(getattr(error, "reason_code", None) or "iiko_gateway_error")


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
