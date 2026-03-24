"""Unit Of Work для strict identity на базе SQLAlchemy."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vtelemax.core.errors import IdentityConflictError
from vtelemax.core.ports import IdentityUnitOfWork

from .repository import SQLAlchemyIdentityRepository
from .support_repository import SQLAlchemySupportRepository


class SQLAlchemyIdentityUnitOfWork(IdentityUnitOfWork):
    """Транзакционная обертка для сценариев strict identity.

    По умолчанию commit выполняется явно через `commit()`.
    Если во время работы возникает исключение, `__exit__` выполняет rollback.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.identity_repository: SQLAlchemyIdentityRepository
        self.support_repository: SQLAlchemySupportRepository

    def __enter__(self) -> "SQLAlchemyIdentityUnitOfWork":
        """Открывает SQLAlchemy Session и репозиторий для текущей транзакции."""

        self._session = self._session_factory()
        self.identity_repository = SQLAlchemyIdentityRepository(self._session)
        self.support_repository = SQLAlchemySupportRepository(self._session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Закрывает транзакцию и освобождает ресурсы."""

        if self._session is None:
            return

        if exc_type is not None:
            self.rollback()
        else:
            # Защита от незафиксированных изменений при забытом commit.
            self._session.rollback()

        self._session.close()
        self._session = None

    def commit(self) -> None:
        """Подтверждает транзакцию."""

        if self._session is None:
            raise RuntimeError("Нельзя выполнить commit вне контекста UnitOfWork.")
        try:
            self._session.commit()
        except IntegrityError as error:
            self._session.rollback()
            if self._is_strict_identity_conflict(error):
                # Трансляция только strict identity-конфликтов в доменную ошибку.
                raise IdentityConflictError(
                    "Конфликт strict identity на уровне БД: нарушены ограничения уникальности."
                ) from error
            # Для остальных целостностных ошибок (например, support FK) сохраняем исходную причину.
            raise

    def rollback(self) -> None:
        """Откатывает транзакцию."""

        if self._session is None:
            raise RuntimeError("Нельзя выполнить rollback вне контекста UnitOfWork.")
        self._session.rollback()

    @staticmethod
    def _is_strict_identity_conflict(error: IntegrityError) -> bool:
        """Определяет, относится ли ошибка целостности к strict identity-ограничениям."""

        error_text = str(error).lower()
        hints = (
            "uq_phones_phone_e164",
            "uq_phones_person_id",
            "uq_platform_accounts_platform_external_id",
            "phones.phone_e164",
            "phones.person_id",
            "platform_accounts.platform, platform_accounts.external_id",
            "platform_accounts.platform, external_id",
        )
        return any(hint in error_text for hint in hints)
