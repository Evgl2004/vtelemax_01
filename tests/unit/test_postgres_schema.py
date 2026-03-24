"""Проверки SQLAlchemy-схемы strict identity.

Тесты валидируют структуру метаданных без подключения к реальной БД.
Это защищает от случайного ослабления ограничений строгой идентификации.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, UniqueConstraint

from vtelemax.infrastructure.postgres.schema import Base, PersonRow, PhoneRow, PlatformAccountRow


def test_metadata_contains_strict_identity_tables() -> None:
    """Проверяет наличие ключевых таблиц strict identity в metadata."""

    table_names = set(Base.metadata.tables.keys())
    assert {"persons", "phones", "platform_accounts"}.issubset(table_names)


def test_phones_table_has_required_unique_constraints() -> None:
    """Проверяет уникальность телефона и person_id в таблице `phones`."""

    constraints = {
        constraint.name
        for constraint in PhoneRow.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_phones_phone_e164" in constraints
    assert "uq_phones_person_id" in constraints


def test_platform_accounts_constraints_are_strict() -> None:
    """Проверяет ограничения уникальности и платформенного набора значений."""

    unique_constraints = {
        constraint.name
        for constraint in PlatformAccountRow.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    check_constraints = {
        constraint.name
        for constraint in PlatformAccountRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "uq_platform_accounts_platform_external_id" in unique_constraints
    assert "ck_platform_accounts_platform_allowed" in check_constraints


def test_foreign_keys_point_to_persons_table() -> None:
    """Проверяет внешние ключи `phones` и `platform_accounts` на `persons`."""

    phone_fk_targets = {foreign_key.target_fullname for foreign_key in PhoneRow.__table__.foreign_keys}
    account_fk_targets = {
        foreign_key.target_fullname for foreign_key in PlatformAccountRow.__table__.foreign_keys
    }

    assert "persons.person_id" in phone_fk_targets
    assert "persons.person_id" in account_fk_targets


def test_person_table_primary_key_name() -> None:
    """Проверяет ожидаемое имя первичного ключа у таблицы `persons`."""

    pk_columns = list(PersonRow.__table__.primary_key.columns.keys())
    assert pk_columns == ["person_id"]
