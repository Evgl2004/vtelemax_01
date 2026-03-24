"""Фабрики подключения к PostgreSQL через SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def build_engine(database_url: str, echo: bool = False) -> Engine:
    """Создает SQLAlchemy Engine для PostgreSQL.

    Args:
        database_url: Строка подключения к БД.
        echo: Включение SQL-логов SQLAlchemy.
    """

    return create_engine(database_url, echo=echo, future=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Создает фабрику сессий для UnitOfWork и репозиториев."""

    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

