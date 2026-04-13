"""Процессор очереди синхронизации профиля с iiko."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from loguru import logger

from vtelemax.core import (
    FinalizeProfileSyncTaskCommand,
    FinalizeProfileSyncTaskTransactionalUseCase,
    GetPersonByIdCommand,
    GetPersonByIdTransactionalUseCase,
    LoyaltyCustomerUpsertData,
    LoyaltyGateway,
    LoyaltyGatewayError,
    ProfileSyncStatus,
    PullPendingProfileSyncTasksTransactionalUseCase,
)


@dataclass(slots=True)
class ProfileSyncProcessor:
    """Обрабатывает pending-задачи очереди профиля и отправляет изменения в iiko."""

    pull_pending_use_case: PullPendingProfileSyncTasksTransactionalUseCase
    finalize_task_use_case: FinalizeProfileSyncTaskTransactionalUseCase
    person_lookup_use_case: GetPersonByIdTransactionalUseCase
    loyalty_gateway: LoyaltyGateway
    max_attempts: int = 5

    async def process_once(self, *, limit: int = 50) -> tuple[int, int, int]:
        """Выполняет один проход очереди.

        Возвращает `(done_count, failed_count, rescheduled_count)`.
        """

        safe_limit = max(int(limit), 1)
        tasks = self.pull_pending_use_case.execute(limit=safe_limit)
        if not tasks:
            return 0, 0, 0

        done_count = 0
        failed_count = 0
        rescheduled_count = 0

        for task in tasks:
            person = self.person_lookup_use_case.execute(GetPersonByIdCommand(person_id=task.person_id))
            if person is None:
                self.finalize_task_use_case.execute(
                    FinalizeProfileSyncTaskCommand(
                        sync_id=task.sync_id,
                        status=ProfileSyncStatus.FAILED,
                        error_text="Person not found",
                    )
                )
                failed_count += 1
                continue

            profile = LoyaltyCustomerUpsertData(
                first_name=person.first_name_input,
                last_name=person.last_name_input,
                gender=person.gender,
                birth_date=person.birth_date,
                email=person.email,
                rules_accepted=person.get_rules_accepted_for_platform(task.source_platform),
                notifications_allowed=person.get_notifications_allowed_for_platform(task.source_platform),
                rules_accepted_at=person.get_rules_accepted_at_for_platform(task.source_platform),
                notifications_allowed_at=person.get_notifications_allowed_at_for_platform(task.source_platform),
            )

            try:
                await asyncio.to_thread(self._sync_profile, phone_e164=person.phone_e164, profile=profile)
            except LoyaltyGatewayError as error:
                next_attempt_at = self._calculate_next_attempt(task.attempts)
                if task.attempts >= self.max_attempts:
                    self.finalize_task_use_case.execute(
                        FinalizeProfileSyncTaskCommand(
                            sync_id=task.sync_id,
                            status=ProfileSyncStatus.FAILED,
                            error_text=str(error),
                        )
                    )
                    failed_count += 1
                else:
                    self.finalize_task_use_case.execute(
                        FinalizeProfileSyncTaskCommand(
                            sync_id=task.sync_id,
                            status=ProfileSyncStatus.PENDING,
                            error_text=str(error),
                            next_attempt_at=next_attempt_at,
                        )
                    )
                    rescheduled_count += 1
            except Exception as error:  # noqa: BLE001
                next_attempt_at = self._calculate_next_attempt(task.attempts)
                if task.attempts >= self.max_attempts:
                    self.finalize_task_use_case.execute(
                        FinalizeProfileSyncTaskCommand(
                            sync_id=task.sync_id,
                            status=ProfileSyncStatus.FAILED,
                            error_text=f"Unexpected error: {error}",
                        )
                    )
                    failed_count += 1
                else:
                    self.finalize_task_use_case.execute(
                        FinalizeProfileSyncTaskCommand(
                            sync_id=task.sync_id,
                            status=ProfileSyncStatus.PENDING,
                            error_text=f"Unexpected error: {error}",
                            next_attempt_at=next_attempt_at,
                        )
                    )
                    rescheduled_count += 1
            else:
                self.finalize_task_use_case.execute(
                    FinalizeProfileSyncTaskCommand(
                        sync_id=task.sync_id,
                        status=ProfileSyncStatus.DONE,
                    )
                )
                done_count += 1

        return done_count, failed_count, rescheduled_count

    def _sync_profile(self, *, phone_e164: str, profile: LoyaltyCustomerUpsertData) -> None:
        """Синхронизирует профиль пользователя с iiko."""

        customer = self.loyalty_gateway.get_customer_info(phone_e164)
        customer_id = customer.customer_id if customer is not None else None
        self.loyalty_gateway.register_customer(
            phone_e164,
            profile=profile,
            customer_id=customer_id,
        )

    @staticmethod
    def _calculate_next_attempt(attempts: int) -> datetime:
        """Возвращает время следующей попытки на основе текущего номера попытки."""

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


def log_profile_sync_cycle(
    *,
    done_count: int,
    failed_count: int,
    rescheduled_count: int,
) -> None:
    """Логирует итог одного цикла обработки profile-sync очереди."""

    logger.bind(component="profile_sync_processor", stage="process_once").info(
        "Обработка profile_sync_queue завершена. done={done}, failed={failed}, rescheduled={rescheduled}.",
        done=done_count,
        failed=failed_count,
        rescheduled=rescheduled_count,
    )

