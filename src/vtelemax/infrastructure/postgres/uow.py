"""Unit Of Work для strict identity на базе SQLAlchemy."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vtelemax.core.errors import IdentityConflictError
from vtelemax.core.ports import IdentityUnitOfWork

from .repository import SQLAlchemyIdentityRepository


class SQLAlchemyIdentityUnitOfWork(IdentityUnitOfWork):
    """Транзакционная обертка для сценариев strict identity.

    По умолчанию commit выполняется явно через `commit()`.
    Если во время работы возникает исключение, `__exit__` выполняет rollback.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.identity_repository: SQLAlchemyIdentityRepository

    def __enter__(self) -> "SQLAlchemyIdentityUnitOfWork":
        """Открывает SQLAlchemy Session и репозиторий для текущей транзакции."""

        self._session = self._session_factory()
        self.identity_repository = SQLAlchemyIdentityRepository(self._session)
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
            # Трансляция низкоуровневой DB-ошибки в доменную ошибку.
            self._session.rollback()
            raise IdentityConflictError(
                "Конфликт strict identity на уровне БД: нарушены ограничения уникальности."
            ) from error

    def rollback(self) -> None:
        """Откатывает транзакцию."""

        if self._session is None:
            raise RuntimeError("Нельзя выполнить rollback вне контекста UnitOfWork.")
        self._session.rollback()
