"""Проверки SQLAlchemy-схемы strict identity.

Тесты валидируют структуру метаданных без подключения к реальной БД.
Это защищает от случайного ослабления ограничений строгой идентификации.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, UniqueConstraint

from vtelemax.infrastructure.postgres.schema import (
    Base,
    PersonCouponRow,
    PersonPlatformStateRow,
    PersonRow,
    PhoneRow,
    PlatformAccountRow,
    SupportMessageRow,
    SupportTicketRow,
)


def test_metadata_contains_strict_identity_tables() -> None:
    """Проверяет наличие ключевых таблиц strict identity в metadata."""

    table_names = set(Base.metadata.tables.keys())
    assert {
        "persons",
        "person_platform_states",
        "phones",
        "platform_accounts",
        "support_tickets",
        "support_messages",
    }.issubset(table_names)


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
    assert "ck_platform_accounts_lifecycle_status_allowed" in check_constraints


def test_person_platform_states_constraints_are_strict() -> None:
    """Проверяет платформенные ограничения в таблице `person_platform_states`."""

    check_constraints = {
        constraint.name
        for constraint in PersonPlatformStateRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_person_platform_states_platform_allowed" in check_constraints


def test_person_coupons_allow_used_after_campaign_status() -> None:
    check_constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in PersonCouponRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_person_coupons_status_allowed" in check_constraints
    assert "used_after_campaign" in check_constraints["ck_person_coupons_status_allowed"]


def test_foreign_keys_point_to_persons_table() -> None:
    """Проверяет внешние ключи `phones` и `platform_accounts` на `persons`."""

    phone_fk_targets = {foreign_key.target_fullname for foreign_key in PhoneRow.__table__.foreign_keys}
    account_fk_targets = {
        foreign_key.target_fullname for foreign_key in PlatformAccountRow.__table__.foreign_keys
    }
    platform_state_fk_targets = {
        foreign_key.target_fullname for foreign_key in PersonPlatformStateRow.__table__.foreign_keys
    }

    assert "persons.person_id" in phone_fk_targets
    assert "persons.person_id" in account_fk_targets
    assert "persons.person_id" in platform_state_fk_targets


def test_person_table_primary_key_name() -> None:
    """Проверяет ожидаемое имя первичного ключа у таблицы `persons`."""

    pk_columns = list(PersonRow.__table__.primary_key.columns.keys())
    assert pk_columns == ["person_id"]


def test_support_tickets_constraints_are_strict() -> None:
    """Проверяет базовые ограничения тикетов поддержки."""

    check_constraints = {
        constraint.name
        for constraint in SupportTicketRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_support_tickets_status_allowed" in check_constraints
    assert "ck_support_tickets_source_platform_allowed" in check_constraints
    assert "ck_support_tickets_last_guest_platform_allowed" in check_constraints


def test_support_messages_constraints_are_strict() -> None:
    """Проверяет ограничения сообщений поддержки и маршрутизации."""

    check_constraints = {
        constraint.name
        for constraint in SupportMessageRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_support_messages_author_allowed" in check_constraints
    assert "ck_support_messages_source_platform_allowed" in check_constraints
    assert "ck_support_messages_target_platform_allowed" in check_constraints
    assert "ck_support_messages_delivery_status_allowed" in check_constraints
