"""Служебные утилиты проекта vtelemax.

Пакет содержит безопасные инструменты для операционных задач разработки:

1. точечная очистка тестовых пользователей;
2. миграция legacy-пользователей Telegram из старого SQLite-бота;
3. вспомогательные процедуры диагностики.
"""

from .user_reset import (
    PersonResetAccount,
    PersonResetSnapshot,
    build_default_redis_patterns,
    collect_matching_redis_keys,
    delete_person_by_id,
    delete_redis_keys,
    get_person_snapshot_by_phone,
)
from .legacy_telegram_migration import (
    DEFAULT_SOURCE_SQLITE_PATH,
    LEGACY_PHONE_VERIFICATION_METHOD,
    LegacyMigrationIssue,
    LegacyMigrationReport,
    LegacyPreparationResult,
    LegacyTelegramSourceRecord,
    PreparedLegacyTelegramRecord,
    build_report_lines,
    migrate_prepared_legacy_records,
    prepare_legacy_source_records,
    read_legacy_source_records,
)
from .legacy_telegram_broadcast import (
    LegacyBroadcastSelectionResult,
    LegacyBroadcastSendResult,
    LegacyBroadcastTarget,
    build_default_legacy_broadcast_message,
    select_legacy_broadcast_targets,
    send_legacy_broadcast,
)
from .guest_info import (
    GuestInfo,
    GuestPlatformInfo,
    get_guest_info_by_phone,
    get_guest_info_rows_by_phone,
)

__all__ = [
    "PersonResetAccount",
    "PersonResetSnapshot",
    "build_default_redis_patterns",
    "collect_matching_redis_keys",
    "delete_person_by_id",
    "delete_redis_keys",
    "get_person_snapshot_by_phone",
    "DEFAULT_SOURCE_SQLITE_PATH",
    "LEGACY_PHONE_VERIFICATION_METHOD",
    "LegacyTelegramSourceRecord",
    "PreparedLegacyTelegramRecord",
    "LegacyMigrationIssue",
    "LegacyPreparationResult",
    "LegacyMigrationReport",
    "read_legacy_source_records",
    "prepare_legacy_source_records",
    "migrate_prepared_legacy_records",
    "build_report_lines",
    "LegacyBroadcastTarget",
    "LegacyBroadcastSelectionResult",
    "LegacyBroadcastSendResult",
    "build_default_legacy_broadcast_message",
    "select_legacy_broadcast_targets",
    "send_legacy_broadcast",
    "GuestInfo",
    "GuestPlatformInfo",
    "get_guest_info_by_phone",
    "get_guest_info_rows_by_phone",
]
