"""Пакетная доставка сохранённых нажатий интерактивных кнопок в SAGUR."""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit
from uuid import UUID, uuid4

import aiohttp
from loguru import logger
from sqlalchemy.orm import Session

from vtelemax.core.sagur_message_interactions import (
    SagurMessageInteractionDeliveryTask,
    SagurMessageInteractionQueueObservation,
)
from vtelemax.infrastructure.postgres.sagur_message_interactions_repository import (
    SQLAlchemySagurMessageInteractionsRepository,
)

from .vtelemax_outbound_hmac import (
    build_vtelemax_outbound_signature,
    canonical_request_path,
)


SAGUR_MESSAGE_INTERACTION_ENDPOINT_PATH = (
    "/internal/integration/v1/vtelemax/message-interactions/events"
)
SAGUR_MESSAGE_INTERACTION_SCHEMA_VERSION = 1
SAGUR_MESSAGE_INTERACTION_MAX_BATCH_ITEMS = 100
SAGUR_MESSAGE_INTERACTION_MAX_BODY_BYTES = 65_536

_SUCCESSFUL_RESULTS = frozenset({"accepted", "duplicate", "rating_already_recorded"})
_PERMANENT_ITEM_RESULTS = frozenset(
    {
        "invalid_item",
        "interaction_not_found",
        "action_unsupported",
        "action_not_allowed_for_button_set",
        "event_id_conflict",
    }
)
_VALID_BATCH_STATUSES = frozenset({"accepted", "partial", "rejected"})
_MAX_SAFE_ERROR_TEXT_LENGTH = 2_000


@dataclass(frozen=True, slots=True)
class SagurMessageInteractionBatchRequest:
    """Неизменяемые байты одной HTTP-попытки и вошедшие в неё события."""

    request_id: str
    sent_at: datetime
    tasks: tuple[SagurMessageInteractionDeliveryTask, ...]
    body: bytes


@dataclass(frozen=True, slots=True)
class SagurMessageInteractionHttpOutcome:
    """Транспортный результат одной попытки без изменения локальной очереди."""

    http_status: int | None
    data: Mapping[str, Any] | None = None
    error_code: str | None = None
    error_text: str | None = None
    retry_after_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class SagurMessageInteractionProcessingResult:
    """Сводный результат одного выбранного пакета."""

    selected: int = 0
    delivered: int = 0
    retry_scheduled: int = 0
    blocked: int = 0
    http_requests: int = 0

    def __add__(
        self,
        other: SagurMessageInteractionProcessingResult,
    ) -> SagurMessageInteractionProcessingResult:
        return SagurMessageInteractionProcessingResult(
            selected=self.selected + other.selected,
            delivered=self.delivered + other.delivered,
            retry_scheduled=self.retry_scheduled + other.retry_scheduled,
            blocked=self.blocked + other.blocked,
            http_requests=self.http_requests + other.http_requests,
        )


@dataclass(frozen=True, slots=True)
class _EventDecision:
    task: SagurMessageInteractionDeliveryTask
    state: Literal["delivered", "retry", "blocked"]
    code: str
    text: str = ""
    retry_after_seconds: float | None = None


def format_rfc3339_utc(value: datetime) -> str:
    """Форматирует осознанную дату в UTC с суффиксом ``Z``."""

    if value.tzinfo is None:
        raise ValueError("Дата-время должно содержать часовой пояс.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_sagur_message_interaction_batch_request(
    tasks: Sequence[SagurMessageInteractionDeliveryTask],
    *,
    request_id: UUID | str,
    sent_at: datetime,
) -> SagurMessageInteractionBatchRequest:
    """Сериализует пакет ровно один раз в компактный UTF-8 JSON."""

    normalized_tasks = tuple(tasks)
    if not 1 <= len(normalized_tasks) <= SAGUR_MESSAGE_INTERACTION_MAX_BATCH_ITEMS:
        raise ValueError("Пакет должен содержать от 1 до 100 событий.")

    request_id_text = str(UUID(str(request_id)))
    items: list[dict[str, object]] = []
    for task in normalized_tasks:
        item: dict[str, object] = {
            "event_id": str(task.event_id),
            "interaction_id": task.interaction_id,
            "action": task.action,
            "occurred_at": format_rfc3339_utc(task.occurred_at),
        }
        if task.provider_message_id is not None:
            item["provider_message_id"] = task.provider_message_id
        items.append(item)

    payload = {
        "request_id": request_id_text,
        "schema_version": SAGUR_MESSAGE_INTERACTION_SCHEMA_VERSION,
        "sent_at": format_rfc3339_utc(sent_at),
        "items": items,
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return SagurMessageInteractionBatchRequest(
        request_id=request_id_text,
        sent_at=sent_at,
        tasks=normalized_tasks,
        body=body,
    )


@dataclass(slots=True)
class SagurMessageInteractionHttpClient:
    """HTTP-клиент подписанных пакетных запросов vtelemax → SAGUR."""

    base_url: str
    endpoint_path: str
    hmac_secret: str
    timeout_seconds: float = 20.0
    require_https: bool = True
    now_factory: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    request_id_factory: Callable[[], UUID] = uuid4
    _session: aiohttp.ClientSession | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        normalized_base_url = self.base_url.strip().rstrip("/")
        normalized_path = self.endpoint_path.strip()
        if not normalized_base_url:
            raise ValueError("Базовый адрес SAGUR не должен быть пустым.")
        if not normalized_path.startswith("/"):
            raise ValueError("Путь приёма SAGUR должен начинаться с '/'.")
        if not self.hmac_secret.strip():
            raise ValueError("HMAC-секрет пакетной доставки SAGUR не задан.")
        if self.timeout_seconds <= 0:
            raise ValueError("Тайм-аут HTTP должен быть больше нуля.")
        parsed = urlsplit(normalized_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Базовый адрес SAGUR должен быть абсолютным HTTP(S)-адресом.")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError(
                "Базовый адрес SAGUR не должен содержать путь, параметры или фрагмент."
            )
        if self.require_https and parsed.scheme != "https":
            raise ValueError("Для пакетной доставки SAGUR требуется HTTPS.")
        self.base_url = normalized_base_url
        self.endpoint_path = normalized_path

    @property
    def endpoint(self) -> str:
        """Возвращает полный адрес утверждённой точки приёма."""

        return urljoin(f"{self.base_url}/", self.endpoint_path.lstrip("/"))

    def prepare(
        self,
        tasks: Sequence[SagurMessageInteractionDeliveryTask],
    ) -> SagurMessageInteractionBatchRequest:
        """Создаёт новый ``request_id`` и неизменяемые байты одной попытки."""

        return build_sagur_message_interaction_batch_request(
            tasks,
            request_id=self.request_id_factory(),
            sent_at=self.now_factory(),
        )

    async def close(self) -> None:
        """Закрывает принадлежащий клиенту HTTP-сеанс и его пул соединений."""

        session = self._session
        self._session = None
        if session is not None and not session.closed:
            await session.close()

    def _get_or_create_session(self) -> aiohttp.ClientSession:
        """Лениво создаёт один HTTP-сеанс на время жизни работника."""

        session = self._session
        if session is None or session.closed:
            session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds)
            )
            self._session = session
        return session

    async def send(
        self,
        request: SagurMessageInteractionBatchRequest,
    ) -> SagurMessageInteractionHttpOutcome:
        """Отправляет уже подготовленные байты и возвращает безопасный результат."""

        timestamp = str(int(self.now_factory().timestamp()))
        signature = build_vtelemax_outbound_signature(
            secret=self.hmac_secret,
            method="POST",
            path=canonical_request_path(
                self.endpoint,
                default_path=SAGUR_MESSAGE_INTERACTION_ENDPOINT_PATH,
            ),
            timestamp=timestamp,
            payload_body=request.body,
        )
        headers = {
            "Content-Type": "application/json",
            "X-Vtelemax-Request-Id": request.request_id,
            "X-Vtelemax-Timestamp": timestamp,
            "X-Vtelemax-Signature": signature,
        }
        try:
            session = self._get_or_create_session()
            async with session.post(
                self.endpoint,
                data=request.body,
                headers=headers,
            ) as response:
                raw_body = await response.read()
                data = _decode_response_object(raw_body)
                return SagurMessageInteractionHttpOutcome(
                    http_status=response.status,
                    data=data,
                    error_code=_optional_text(data.get("code")) if data else None,
                    error_text=_optional_text(data.get("message")) if data else None,
                    retry_after_seconds=_parse_retry_after(
                        response.headers.get("Retry-After"),
                        now=self.now_factory(),
                    ),
                )
        except (TimeoutError, aiohttp.ClientError) as error:
            return SagurMessageInteractionHttpOutcome(
                http_status=None,
                error_code="network_error",
                error_text=_safe_error_text(str(error)),
            )


@dataclass(slots=True)
class SagurMessageInteractionDeliveryProcessor:
    """Выбирает короткий пакет, отправляет его и фиксирует частичный результат."""

    session_factory: Callable[[], Session]
    http_client: SagurMessageInteractionHttpClient
    batch_size: int = SAGUR_MESSAGE_INTERACTION_MAX_BATCH_ITEMS
    max_body_bytes: int = SAGUR_MESSAGE_INTERACTION_MAX_BODY_BYTES
    retry_base_seconds: float = 30.0
    retry_max_seconds: float = 3_600.0
    retry_jitter_ratio: float = 0.2
    lock_timeout_seconds: int = 300
    minimum_request_interval_seconds: float = 1.0
    now_factory: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    monotonic_factory: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    random_uniform: Callable[[float, float], float] = random.uniform
    _last_request_started_at: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not 1 <= self.batch_size <= SAGUR_MESSAGE_INTERACTION_MAX_BATCH_ITEMS:
            raise ValueError("Размер пакета должен находиться в диапазоне от 1 до 100.")
        if self.max_body_bytes <= 0:
            raise ValueError("Предел тела запроса должен быть больше нуля.")
        if self.retry_base_seconds <= 0 or self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError("Границы задержки повтора заданы некорректно.")
        if not 0 <= self.retry_jitter_ratio <= 1:
            raise ValueError("Доля случайного разброса должна находиться от 0 до 1.")
        if self.lock_timeout_seconds <= 0:
            raise ValueError("Тайм-аут блокировки должен быть больше нуля.")
        if self.minimum_request_interval_seconds < 0:
            raise ValueError("Минимальный интервал запросов не может быть отрицательным.")

    def read_queue_observation(self) -> SagurMessageInteractionQueueObservation:
        """Читает низконагрузочный снимок активной очереди в отдельной сессии."""

        session = self.session_factory()
        try:
            repository = SQLAlchemySagurMessageInteractionsRepository(session)
            return repository.read_active_queue_observation()
        finally:
            session.close()

    async def process_once(self) -> SagurMessageInteractionProcessingResult:
        """Обрабатывает один готовый пакет; внешний HTTP выполняется без транзакции БД."""

        request = self._claim_request()
        if request is None:
            return SagurMessageInteractionProcessingResult()
        if len(request.body) > self.max_body_bytes:
            decision = _EventDecision(
                task=request.tasks[0],
                state="blocked",
                code="payload_too_large",
                text="Один элемент превышает локальный предел тела пакетного запроса.",
            )
            self._apply_decisions((decision,), lease_id=UUID(request.request_id))
            return SagurMessageInteractionProcessingResult(selected=1, blocked=1)

        decisions, http_requests = await self._send_with_splitting(request)
        self._apply_decisions(decisions, lease_id=UUID(request.request_id))
        return SagurMessageInteractionProcessingResult(
            selected=len(request.tasks),
            delivered=sum(item.state == "delivered" for item in decisions),
            retry_scheduled=sum(item.state == "retry" for item in decisions),
            blocked=sum(item.state == "blocked" for item in decisions),
            http_requests=http_requests,
        )

    def _claim_request(self) -> SagurMessageInteractionBatchRequest | None:
        session = self.session_factory()
        try:
            repository = SQLAlchemySagurMessageInteractionsRepository(session)
            released = repository.release_stale_processing(
                lock_timeout_seconds=self.lock_timeout_seconds,
                now_utc=self.now_factory(),
            )
            tasks = repository.select_due_events_for_update(
                limit=self.batch_size,
                now_utc=self.now_factory(),
            )
            if not tasks:
                session.commit()
                if released:
                    _log_released_stale(released)
                return None

            request = self._largest_fitting_request(tasks)
            event_ids = tuple(task.event_id for task in request.tasks)
            marked = repository.mark_processing(
                event_ids,
                lease_id=UUID(request.request_id),
                now_utc=self.now_factory(),
            )
            if marked != len(event_ids):
                raise RuntimeError("Не все выбранные события переведены в состояние processing.")
            session.commit()
            if released:
                _log_released_stale(released)
            return request
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _largest_fitting_request(
        self,
        tasks: Sequence[SagurMessageInteractionDeliveryTask],
    ) -> SagurMessageInteractionBatchRequest:
        request_id = self.http_client.request_id_factory()
        sent_at = self.http_client.now_factory()
        selected_count = 1
        selected_request = build_sagur_message_interaction_batch_request(
            tasks[:1],
            request_id=request_id,
            sent_at=sent_at,
        )
        for count in range(2, len(tasks) + 1):
            candidate = build_sagur_message_interaction_batch_request(
                tasks[:count],
                request_id=request_id,
                sent_at=sent_at,
            )
            if len(candidate.body) > self.max_body_bytes:
                break
            selected_count = count
            selected_request = candidate
        if selected_count == 1:
            return selected_request
        return selected_request

    async def _send_with_splitting(
        self,
        request: SagurMessageInteractionBatchRequest,
    ) -> tuple[tuple[_EventDecision, ...], int]:
        await self._wait_for_request_slot()
        started_at = self.monotonic_factory()
        outcome = await self.http_client.send(request)
        duration_ms = max((self.monotonic_factory() - started_at) * 1_000, 0.0)
        _log_http_attempt(request=request, outcome=outcome, duration_ms=duration_ms)

        if outcome.http_status == 413:
            if len(request.tasks) == 1:
                return (
                    (
                        _EventDecision(
                            task=request.tasks[0],
                            state="blocked",
                            code=outcome.error_code or "body_too_large",
                            text=outcome.error_text
                            or "SAGUR отклонил одиночный слишком большой элемент.",
                        ),
                    ),
                    1,
                )
            middle = len(request.tasks) // 2
            left_request = self.http_client.prepare(request.tasks[:middle])
            right_request = self.http_client.prepare(request.tasks[middle:])
            left_decisions, left_requests = await self._send_with_splitting(left_request)
            right_decisions, right_requests = await self._send_with_splitting(right_request)
            return left_decisions + right_decisions, 1 + left_requests + right_requests

        return self._decisions_for_outcome(request, outcome), 1

    async def _wait_for_request_slot(self) -> None:
        now_value = self.monotonic_factory()
        if self._last_request_started_at is not None:
            wait_seconds = self.minimum_request_interval_seconds - (
                now_value - self._last_request_started_at
            )
            if wait_seconds > 0:
                await self.sleep(wait_seconds)
        self._last_request_started_at = self.monotonic_factory()

    def _decisions_for_outcome(
        self,
        request: SagurMessageInteractionBatchRequest,
        outcome: SagurMessageInteractionHttpOutcome,
    ) -> tuple[_EventDecision, ...]:
        status = outcome.http_status
        if (
            status is None
            or status == 408
            or status == 429
            or (status is not None and status >= 500)
        ):
            return tuple(
                _EventDecision(
                    task=task,
                    state="retry",
                    code=outcome.error_code or (f"http_{status}" if status else "network_error"),
                    text=outcome.error_text or "Временная ошибка доставки пакета в SAGUR.",
                    retry_after_seconds=outcome.retry_after_seconds,
                )
                for task in request.tasks
            )
        if status != 200:
            return tuple(
                _EventDecision(
                    task=task,
                    state="blocked",
                    code=outcome.error_code or f"http_{status}",
                    text=outcome.error_text or "SAGUR отклонил оболочку пакетного запроса.",
                )
                for task in request.tasks
            )
        return _parse_successful_batch_response(request=request, data=outcome.data)

    def _apply_decisions(
        self,
        decisions: Sequence[_EventDecision],
        *,
        lease_id: UUID,
    ) -> None:
        session = self.session_factory()
        try:
            repository = SQLAlchemySagurMessageInteractionsRepository(session)
            now = self.now_factory()
            ignored_stale = 0
            for decision in decisions:
                if decision.state == "delivered":
                    applied = repository.mark_delivered(
                        decision.task.event_id,
                        lease_id=lease_id,
                        result=decision.code,
                        now_utc=now,
                    )
                elif decision.state == "blocked":
                    applied = repository.mark_blocked(
                        decision.task.event_id,
                        lease_id=lease_id,
                        error_code=decision.code,
                        error_text=decision.text,
                        now_utc=now,
                    )
                else:
                    delay_seconds = self._retry_delay_seconds(decision)
                    applied = repository.schedule_retry(
                        decision.task.event_id,
                        lease_id=lease_id,
                        error_code=decision.code,
                        error_text=decision.text,
                        next_attempt_at=now + timedelta(seconds=delay_seconds),
                        now_utc=now,
                    )
                if not applied:
                    ignored_stale += 1
            session.commit()
            if ignored_stale:
                logger.bind(
                    component="sagur_message_interaction_delivery",
                    stage="stale_result_ignored",
                ).warning(
                    "Запоздавший результат старой аренды не применён. "
                    "lease_id={lease_id}, count={count}.",
                    lease_id=str(lease_id),
                    count=ignored_stale,
                )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _retry_delay_seconds(self, decision: _EventDecision) -> float:
        exponent = min(max(decision.task.delivery_attempts - 1, 0), 30)
        base_delay = min(self.retry_base_seconds * (2**exponent), self.retry_max_seconds)
        jitter = self.random_uniform(0.0, base_delay * self.retry_jitter_ratio)
        calculated = min(base_delay + jitter, self.retry_max_seconds)
        if decision.retry_after_seconds is None:
            return calculated
        return max(calculated, decision.retry_after_seconds)


@dataclass(slots=True)
class PeriodicSagurMessageInteractionWorker:
    """Единственный последовательный работник активной очереди нажатий."""

    processor: SagurMessageInteractionDeliveryProcessor
    interval_seconds: float = 300.0
    lock: asyncio.Lock | None = None
    now_factory: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    _stop_event: asyncio.Event = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("Интервал работника должен быть больше нуля.")
        self._stop_event = asyncio.Event()

    async def run_forever(self) -> None:
        """Обрабатывает всю готовую очередь и ожидает следующего окна."""

        worker_logger = logger.bind(
            component="sagur_message_interaction_worker",
            stage="run_forever",
        )
        worker_logger.info(
            "Работник пакетной доставки нажатий SAGUR запущен. interval={interval}s.",
            interval=self.interval_seconds,
        )
        try:
            while not self._stop_event.is_set():
                await self.process_due_events()
                await self._wait_for_next_tick()
        except asyncio.CancelledError:
            worker_logger.info("Работник пакетной доставки нажатий SAGUR остановлен по отмене.")
            raise
        finally:
            worker_logger.info("Работник пакетной доставки нажатий SAGUR завершил работу.")

    async def process_due_events(self) -> SagurMessageInteractionProcessingResult:
        """Последовательно выгружает все события, готовые к текущему проходу."""

        if self.lock is not None:
            if self.lock.locked():
                return SagurMessageInteractionProcessingResult()
            async with self.lock:
                return await self._process_due_events_unlocked()
        return await self._process_due_events_unlocked()

    async def shutdown(self) -> None:
        """Запрашивает мягкую остановку после текущего HTTP-запроса."""

        self._stop_event.set()

    async def _process_due_events_unlocked(self) -> SagurMessageInteractionProcessingResult:
        total = SagurMessageInteractionProcessingResult()
        try:
            while not self._stop_event.is_set():
                result = await self.processor.process_once()
                total += result
                if result.selected == 0:
                    break
        except Exception:  # noqa: BLE001
            logger.bind(
                component="sagur_message_interaction_worker",
                stage="process_due_events",
            ).exception("Ошибка обработки очереди нажатий SAGUR.")
        observation = self._read_queue_observation_safely()
        oldest_age_seconds = _oldest_event_age_seconds(
            observation,
            now=self.now_factory(),
        )
        logger.bind(
            component="sagur_message_interaction_worker",
            stage="process_due_events",
        ).info(
            "Проход доставки нажатий SAGUR завершён. selected={selected}, "
            "delivered={delivered}, retry={retry}, blocked={blocked}, requests={requests}, "
            "active={active}, oldest_age_seconds={oldest_age_seconds}.",
            selected=total.selected,
            delivered=total.delivered,
            retry=total.retry_scheduled,
            blocked=total.blocked,
            requests=total.http_requests,
            active=observation.active_count if observation is not None else None,
            oldest_age_seconds=oldest_age_seconds,
        )
        return total

    def _read_queue_observation_safely(
        self,
    ) -> SagurMessageInteractionQueueObservation | None:
        """Не позволяет диагностическому чтению остановить доставку событий."""

        try:
            return self.processor.read_queue_observation()
        except Exception:  # noqa: BLE001
            logger.bind(
                component="sagur_message_interaction_worker",
                stage="queue_observation",
            ).exception("Не удалось прочитать состояние активной очереди нажатий SAGUR.")
            return None

    async def _wait_for_next_tick(self) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)


def _oldest_event_age_seconds(
    observation: SagurMessageInteractionQueueObservation | None,
    *,
    now: datetime,
) -> int | None:
    """Возвращает неотрицательный возраст старейшего активного события."""

    if observation is None or observation.oldest_occurred_at is None:
        return None
    if now.tzinfo is None or observation.oldest_occurred_at.tzinfo is None:
        raise ValueError("Дата-время наблюдения за очередью должно содержать часовой пояс.")
    age_seconds = (
        now.astimezone(timezone.utc)
        - observation.oldest_occurred_at.astimezone(timezone.utc)
    ).total_seconds()
    return max(int(age_seconds), 0)


def _parse_successful_batch_response(
    *,
    request: SagurMessageInteractionBatchRequest,
    data: Mapping[str, Any] | None,
) -> tuple[_EventDecision, ...]:
    if not _valid_response_envelope(request=request, data=data):
        return _retry_all(
            request.tasks, code="response_invalid", text="Некорректная оболочка ответа SAGUR."
        )

    assert data is not None
    raw_results = data["results"]
    assert isinstance(raw_results, list)
    decisions: dict[int, _EventDecision] = {}
    invalid_indexes: set[int] = set()
    for raw_result in raw_results:
        if not isinstance(raw_result, Mapping):
            continue
        index = raw_result.get("index")
        if type(index) is not int or not 0 <= index < len(request.tasks):
            continue
        if index in decisions or index in invalid_indexes:
            decisions.pop(index, None)
            invalid_indexes.add(index)
            continue
        task = request.tasks[index]
        if raw_result.get("event_id") != str(task.event_id):
            invalid_indexes.add(index)
            continue
        item_status = raw_result.get("status")
        result = raw_result.get("result")
        message = _optional_text(raw_result.get("message")) or ""
        if item_status == "accepted" and isinstance(result, str) and result in _SUCCESSFUL_RESULTS:
            decisions[index] = _EventDecision(task=task, state="delivered", code=result)
        elif (
            item_status == "rejected"
            and isinstance(result, str)
            and result in _PERMANENT_ITEM_RESULTS
        ):
            decisions[index] = _EventDecision(
                task=task,
                state="blocked",
                code=result,
                text=message or "SAGUR отклонил элемент пакетного запроса.",
            )
        else:
            invalid_indexes.add(index)

    for index, task in enumerate(request.tasks):
        if index not in decisions:
            decisions[index] = _EventDecision(
                task=task,
                state="retry",
                code="item_result_missing",
                text="Ответ SAGUR не содержит однозначного подтверждения элемента.",
            )
    return tuple(decisions[index] for index in range(len(request.tasks)))


def _valid_response_envelope(
    *,
    request: SagurMessageInteractionBatchRequest,
    data: Mapping[str, Any] | None,
) -> bool:
    if not data:
        return False
    status = data.get("status")
    return bool(
        data.get("ok") is True
        and type(data.get("schema_version")) is int
        and data.get("schema_version") == SAGUR_MESSAGE_INTERACTION_SCHEMA_VERSION
        and data.get("request_id") == request.request_id
        and isinstance(status, str)
        and status in _VALID_BATCH_STATUSES
        and isinstance(data.get("received_at"), str)
        and isinstance(data.get("results"), list)
    )


def _retry_all(
    tasks: Sequence[SagurMessageInteractionDeliveryTask],
    *,
    code: str,
    text: str,
) -> tuple[_EventDecision, ...]:
    return tuple(_EventDecision(task=task, state="retry", code=code, text=text) for task in tasks)


def _decode_response_object(raw_body: bytes) -> Mapping[str, Any] | None:
    try:
        decoded = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, Mapping) else None


def _parse_retry_after(value: str | None, *, now: datetime) -> float | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        seconds = float(normalized)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(normalized)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        seconds = (retry_at - now.astimezone(timezone.utc)).total_seconds()
    return max(seconds, 0.0)


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _safe_error_text(value: str) -> str:
    return str(value)[:_MAX_SAFE_ERROR_TEXT_LENGTH]


def _log_released_stale(count: int) -> None:
    logger.bind(
        component="sagur_message_interaction_delivery",
        stage="release_stale",
    ).warning("Возвращены зависшие попытки доставки нажатий SAGUR. count={count}.", count=count)


def _log_http_attempt(
    *,
    request: SagurMessageInteractionBatchRequest,
    outcome: SagurMessageInteractionHttpOutcome,
    duration_ms: float,
) -> None:
    logger.bind(
        component="sagur_message_interaction_delivery",
        stage="http_attempt",
    ).info(
        "HTTP-попытка доставки нажатий SAGUR завершена. request_id={request_id}, "
        "items={items}, body_bytes={body_bytes}, http_status={http_status}, "
        "duration_ms={duration_ms:.0f}.",
        request_id=request.request_id,
        items=len(request.tasks),
        body_bytes=len(request.body),
        http_status=outcome.http_status,
        duration_ms=duration_ms,
    )
