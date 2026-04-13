"""Unit tests for profile sync processor."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from vtelemax.adapters.profile_sync import ProfileSyncProcessor
from vtelemax.core import (
    FinalizeProfileSyncTaskCommand,
    LoyaltyCard,
    LoyaltyCustomer,
    LoyaltyGatewayError,
    LoyaltyRegisterCustomerResult,
    Person,
    PlatformAccount,
    PlatformRegistrationState,
    ProfileSyncStatus,
    ProfileSyncTask,
)


class _PullPendingUseCaseStub:
    def __init__(self, tasks: tuple[ProfileSyncTask, ...]) -> None:
        self.tasks = tasks
        self.last_limit: int | None = None

    def execute(self, *, limit: int) -> tuple[ProfileSyncTask, ...]:
        self.last_limit = limit
        return self.tasks


class _FinalizeUseCaseStub:
    def __init__(self) -> None:
        self.commands: list[FinalizeProfileSyncTaskCommand] = []

    def execute(self, command: FinalizeProfileSyncTaskCommand) -> None:
        self.commands.append(command)


class _PersonLookupUseCaseStub:
    def __init__(self, person: Person | None) -> None:
        self.person = person

    def execute(self, command):  # noqa: ANN001
        return self.person


@dataclass(slots=True)
class _LoyaltyGatewayStub:
    customer: LoyaltyCustomer | None = None
    get_customer_info_calls: int = 0
    register_customer_calls: int = 0
    last_profile: object | None = None
    fail_with: Exception | None = None

    def get_customer_info(self, phone_e164: str) -> LoyaltyCustomer | None:  # noqa: ARG002
        self.get_customer_info_calls += 1
        return self.customer

    def register_customer(
        self,
        phone_e164: str,  # noqa: ARG002
        *,
        profile=None,
        customer_id: str | None = None,  # noqa: ARG002
    ) -> LoyaltyRegisterCustomerResult:
        self.register_customer_calls += 1
        self.last_profile = profile
        if self.fail_with is not None:
            raise self.fail_with
        return LoyaltyRegisterCustomerResult(customer_id="iiko-1", message="ok")

    def issue_card_for_customer(self, phone_e164: str, customer_id: str):  # noqa: ANN201, ARG002
        raise NotImplementedError


def _build_task(*, attempts: int = 1) -> ProfileSyncTask:
    now_utc = datetime.now(timezone.utc)
    return ProfileSyncTask(
        sync_id=uuid4(),
        person_id=uuid4(),
        source_platform="telegram",
        status=ProfileSyncStatus.PROCESSING,
        attempts=attempts,
        next_attempt_at=now_utc,
        payload_json={"trigger": "profile_edit"},
        created_at=now_utc,
        updated_at=now_utc,
    )


def _build_person(person_id) -> Person:  # noqa: ANN001
    person = Person(
        person_id=person_id,
        phone_e164="+79129990000",
        accounts={PlatformAccount(platform="telegram", external_id="1001")},
        first_name_input="Ivan",
        last_name_input="Petrov",
        email="ivan@example.com",
    )
    person.set_platform_state(
        PlatformRegistrationState(
            platform="telegram",
            rules_accepted=True,
            notifications_allowed=False,
            is_registered=True,
        )
    )
    return person


def test_profile_sync_processor_marks_task_done_on_success() -> None:
    task = _build_task(attempts=1)
    person = _build_person(task.person_id)
    pull_use_case = _PullPendingUseCaseStub(tasks=(task,))
    finalize_use_case = _FinalizeUseCaseStub()
    person_lookup_use_case = _PersonLookupUseCaseStub(person=person)
    loyalty_gateway = _LoyaltyGatewayStub(
        customer=LoyaltyCustomer(
            customer_id="iiko-customer",
            balance=100.0,
            cards=(LoyaltyCard(number="2200000000000000"),),
        )
    )
    processor = ProfileSyncProcessor(
        pull_pending_use_case=pull_use_case,  # type: ignore[arg-type]
        finalize_task_use_case=finalize_use_case,  # type: ignore[arg-type]
        person_lookup_use_case=person_lookup_use_case,  # type: ignore[arg-type]
        loyalty_gateway=loyalty_gateway,  # type: ignore[arg-type]
        max_attempts=5,
    )

    done_count, failed_count, rescheduled_count = asyncio.run(processor.process_once(limit=20))

    assert done_count == 1
    assert failed_count == 0
    assert rescheduled_count == 0
    assert pull_use_case.last_limit == 20
    assert loyalty_gateway.get_customer_info_calls == 1
    assert loyalty_gateway.register_customer_calls == 1
    assert loyalty_gateway.last_profile is not None
    assert loyalty_gateway.last_profile.first_name == "Ivan"
    assert loyalty_gateway.last_profile.rules_accepted is True
    assert len(finalize_use_case.commands) == 1
    assert finalize_use_case.commands[0].status == ProfileSyncStatus.DONE
    assert finalize_use_case.commands[0].sync_id == task.sync_id


def test_profile_sync_processor_reschedules_on_retryable_error() -> None:
    task = _build_task(attempts=1)
    person = _build_person(task.person_id)
    finalize_use_case = _FinalizeUseCaseStub()
    processor = ProfileSyncProcessor(
        pull_pending_use_case=_PullPendingUseCaseStub(tasks=(task,)),  # type: ignore[arg-type]
        finalize_task_use_case=finalize_use_case,  # type: ignore[arg-type]
        person_lookup_use_case=_PersonLookupUseCaseStub(person=person),  # type: ignore[arg-type]
        loyalty_gateway=_LoyaltyGatewayStub(  # type: ignore[arg-type]
            fail_with=LoyaltyGatewayError("temporary iiko failure")
        ),
        max_attempts=5,
    )

    done_count, failed_count, rescheduled_count = asyncio.run(processor.process_once(limit=10))

    assert done_count == 0
    assert failed_count == 0
    assert rescheduled_count == 1
    assert len(finalize_use_case.commands) == 1
    command = finalize_use_case.commands[0]
    assert command.status == ProfileSyncStatus.PENDING
    assert command.next_attempt_at is not None
    assert "temporary iiko failure" in (command.error_text or "")


def test_profile_sync_processor_fails_when_person_missing() -> None:
    task = _build_task(attempts=1)
    finalize_use_case = _FinalizeUseCaseStub()
    processor = ProfileSyncProcessor(
        pull_pending_use_case=_PullPendingUseCaseStub(tasks=(task,)),  # type: ignore[arg-type]
        finalize_task_use_case=finalize_use_case,  # type: ignore[arg-type]
        person_lookup_use_case=_PersonLookupUseCaseStub(person=None),  # type: ignore[arg-type]
        loyalty_gateway=_LoyaltyGatewayStub(),  # type: ignore[arg-type]
        max_attempts=5,
    )

    done_count, failed_count, rescheduled_count = asyncio.run(processor.process_once(limit=10))

    assert done_count == 0
    assert failed_count == 1
    assert rescheduled_count == 0
    assert len(finalize_use_case.commands) == 1
    command = finalize_use_case.commands[0]
    assert command.status == ProfileSyncStatus.FAILED
    assert command.error_text == "Person not found"
