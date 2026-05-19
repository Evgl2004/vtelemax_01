"""Инфраструктурный клиент iiko Cloud API для разделов лояльности.

Клиент реализует порт `LoyaltyGateway` и предоставляет синхронный интерфейс,
который можно безопасно вызывать из текущих синхронных adapter/use-case слоёв.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from loguru import logger

from vtelemax.core.loyalty_ports import (
    LoyaltyCard,
    LoyaltyCustomer,
    LoyaltyCustomerUpsertData,
    LoyaltyGateway,
    LoyaltyGatewayError,
    LoyaltyIssueCardResult,
    LoyaltyRegisterCustomerResult,
)


@dataclass(slots=True)
class _AccessTokenState:
    """Кэш состояния access-токена iiko."""

    token: str
    expires_at_utc: datetime


class IikoLoyaltyGateway(LoyaltyGateway):
    """Шлюз интеграции с iiko Cloud API."""

    def __init__(
        self,
        *,
        api_key: str,
        organization_id: str,
        base_url: str = "https://api-ru.iiko.services/api/1",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._logger = logger.bind(component="iiko_gateway")
        self._api_key = str(api_key).strip()
        self._organization_id = str(organization_id).strip()
        self._base_url = str(base_url).strip().rstrip("/")
        self._timeout_seconds = float(timeout_seconds)
        self._access_token_state: _AccessTokenState | None = None

        if not self._api_key:
            raise ValueError("Параметр IIKO_API_KEY не может быть пустым.")
        if not self._organization_id:
            raise ValueError("Параметр IIKO_ORG_ID не может быть пустым.")
        if not self._base_url:
            raise ValueError("Параметр IIKO_BASE_URL не может быть пустым.")

    def get_customer_info(self, phone_e164: str) -> LoyaltyCustomer | None:
        """Возвращает данные клиента iiko по номеру телефона."""

        token = self._get_access_token()
        payload = {
            "phone": self._normalize_phone(phone_e164),
            "type": "phone",
            "organizationId": self._organization_id,
        }
        status_code, body, raw_text = self._post_json(
            path="/loyalty/iiko/customer/info",
            payload=payload,
            token=token,
        )
        if status_code == 200:
            try:
                return self._extract_customer(body)
            except LoyaltyGatewayError as error:
                raise LoyaltyGatewayError(
                    str(error),
                    reason_code="customer_info_payload_invalid",
                    endpoint="/loyalty/iiko/customer/info",
                    status_code=status_code,
                    is_transient=False,
                ) from error
        if status_code in {400, 404}:
            # Для бизнес-логики это штатный сценарий: клиент ещё не создан.
            self._logger.info(
                "Клиент iiko не найден по номеру телефона. phone={phone}.",
                phone=payload["phone"],
            )
            return None
        raise LoyaltyGatewayError(
            f"Ошибка получения данных клиента iiko (HTTP {status_code}): {raw_text or 'empty response'}",
            reason_code="customer_info_http_error",
            endpoint="/loyalty/iiko/customer/info",
            status_code=status_code,
            is_transient=self._is_transient_http_status(status_code),
        )

    def register_customer(
        self,
        phone_e164: str,
        *,
        profile: LoyaltyCustomerUpsertData | None = None,
        customer_id: str | None = None,
    ) -> LoyaltyRegisterCustomerResult:
        """Создает или обновляет клиента в iiko и возвращает его `customer_id`."""

        token = self._get_access_token()
        safe_customer_id = str(customer_id or "").strip() or None
        safe_profile = profile or LoyaltyCustomerUpsertData()
        consent_status = self._resolve_consent_status(safe_profile.rules_accepted)
        notifications_allowed = (
            bool(safe_profile.notifications_allowed)
            if safe_profile.notifications_allowed is not None
            else True
        )
        payload = {
            "phone": self._normalize_phone(phone_e164),
            "name": str(safe_profile.first_name or "").strip(),
            "shouldReceivePromoActionsInfo": notifications_allowed,
            "shouldReceiveLoyaltyInfo": notifications_allowed,
            "consentStatus": consent_status,
            "organizationId": self._organization_id,
        }
        last_name = str(safe_profile.last_name or "").strip()
        if last_name:
            payload["surName"] = last_name
        birthday = self._format_birth_date_for_iiko(safe_profile.birth_date)
        if birthday:
            payload["birthday"] = birthday
        sex = self._format_gender_for_iiko(safe_profile.gender)
        if sex is not None:
            payload["sex"] = sex
        email = str(safe_profile.email or "").strip()
        if email:
            payload["email"] = email
        if safe_customer_id is not None:
            payload["id"] = safe_customer_id
        self._logger.info(
            "Отправка create_or_update в iiko. phone={phone}, has_name={has_name}, "
            "rules_accepted={rules_accepted}, rules_accepted_at={rules_accepted_at}, "
            "notifications_allowed={notifications_allowed}, notifications_allowed_at={notifications_allowed_at}, "
            "is_update={is_update}.",
            phone=payload["phone"],
            has_name=bool(payload["name"]),
            rules_accepted=safe_profile.rules_accepted,
            rules_accepted_at=safe_profile.rules_accepted_at.isoformat()
            if safe_profile.rules_accepted_at is not None
            else None,
            notifications_allowed=safe_profile.notifications_allowed,
            notifications_allowed_at=safe_profile.notifications_allowed_at.isoformat()
            if safe_profile.notifications_allowed_at is not None
            else None,
            is_update=safe_customer_id is not None,
        )
        status_code, body, raw_text = self._post_json(
            path="/loyalty/iiko/customer/create_or_update",
            payload=payload,
            token=token,
        )
        if status_code != 200:
            raise LoyaltyGatewayError(
                f"Ошибка регистрации клиента iiko (HTTP {status_code}): {raw_text or 'empty response'}",
                reason_code="customer_upsert_http_error",
                endpoint="/loyalty/iiko/customer/create_or_update",
                status_code=status_code,
                is_transient=self._is_transient_http_status(status_code),
            )

        customer_id = str(body.get("id") or "").strip()
        if not customer_id:
            raise LoyaltyGatewayError(
                "iiko вернул пустой customer_id после регистрации клиента.",
                reason_code="customer_upsert_empty_customer_id",
                endpoint="/loyalty/iiko/customer/create_or_update",
                status_code=status_code,
                is_transient=False,
            )

        return LoyaltyRegisterCustomerResult(
            customer_id=customer_id,
            message=(
                "Клиент успешно обновлен в бонусной системе."
                if safe_customer_id is not None
                else "Клиент успешно зарегистрирован в бонусной системе."
            ),
        )

    def issue_card_for_customer(self, phone_e164: str, customer_id: str) -> LoyaltyIssueCardResult:
        """Выпускает карту клиенту и подключает к программе лояльности."""

        safe_customer_id = str(customer_id).strip()
        if not safe_customer_id:
            raise LoyaltyGatewayError(
                "Не указан customer_id для выпуска карты.",
                reason_code="card_issue_missing_customer_id",
                endpoint="/loyalty/iiko/customer/card/add",
                is_transient=False,
            )

        token = self._get_access_token()
        card_number = self._build_card_number(phone_e164)
        add_card_payload = {
            "customerId": safe_customer_id,
            "cardNumber": card_number,
            "cardTrack": card_number,
            "organizationId": self._organization_id,
        }
        status_code, _, raw_text = self._post_json(
            path="/loyalty/iiko/customer/card/add",
            payload=add_card_payload,
            token=token,
        )
        if status_code != 200:
            raise LoyaltyGatewayError(
                f"Ошибка выпуска карты iiko (HTTP {status_code}): {raw_text or 'empty response'}",
                reason_code="card_issue_http_error",
                endpoint="/loyalty/iiko/customer/card/add",
                status_code=status_code,
                is_transient=self._is_transient_http_status(status_code),
            )

        # Подключение к программе лояльности не блокирует успешный выпуск карты.
        program_message = self._try_attach_customer_to_program(
            token=token,
            customer_id=safe_customer_id,
        )
        return LoyaltyIssueCardResult(
            card_number=card_number,
            message=program_message,
        )

    def _try_attach_customer_to_program(self, *, token: str, customer_id: str) -> str:
        """Пытается подключить клиента к программе лояльности, без фатального падения сценария."""

        programs_payload = {
            "withoutMarketingCampaigns": True,
            "organizationId": self._organization_id,
        }
        status_code, programs_body, raw_text = self._post_json(
            path="/loyalty/iiko/program",
            payload=programs_payload,
            token=token,
        )
        if status_code != 200:
            self._logger.warning(
                "Не удалось получить программы лояльности для карты. status={status}, body={body}.",
                status=status_code,
                body=raw_text,
            )
            return "Карта выпущена, но программу лояльности подключить не удалось."

        programs = programs_body.get("programs") or programs_body.get("Programs") or []
        if not isinstance(programs, list) or not programs:
            return "Карта выпущена, но в iiko не найдено программ лояльности."

        selected_program_id = self._select_program_id(programs)
        if not selected_program_id:
            return "Карта выпущена, но не удалось определить ID программы лояльности."

        attach_payload = {
            "customerId": customer_id,
            "organizationId": self._organization_id,
            "programId": selected_program_id,
        }
        status_code, _, raw_text = self._post_json(
            path="/loyalty/iiko/customer/program/add",
            payload=attach_payload,
            token=token,
        )
        if status_code != 200:
            self._logger.warning(
                "Карта выпущена, но программа лояльности не подключена. status={status}, body={body}.",
                status=status_code,
                body=raw_text,
            )
            return "Карта выпущена, но подключение к программе лояльности не выполнено."

        return "Карта успешно выпущена и подключена к программе лояльности."

    def _get_access_token(self) -> str:
        """Возвращает действующий access-токен iiko (с кэшем на 14 минут)."""

        if self._access_token_state is not None and datetime.now(tz=timezone.utc) < self._access_token_state.expires_at_utc:
            return self._access_token_state.token

        status_code, body, raw_text = self._post_json(
            path="/access_token",
            payload={"apiLogin": self._api_key},
            token=None,
        )
        if status_code != 200:
            raise LoyaltyGatewayError(
                f"Ошибка получения access token iiko (HTTP {status_code}): {raw_text or 'empty response'}",
                reason_code="access_token_http_error",
                endpoint="/access_token",
                status_code=status_code,
                is_transient=self._is_transient_http_status(status_code),
            )

        token = str(body.get("token") or "").strip()
        if not token:
            raise LoyaltyGatewayError(
                "iiko вернул пустой access token.",
                reason_code="access_token_empty",
                endpoint="/access_token",
                status_code=status_code,
                is_transient=False,
            )

        self._access_token_state = _AccessTokenState(
            token=token,
            expires_at_utc=datetime.now(tz=timezone.utc) + timedelta(minutes=14),
        )
        return token

    def _post_json(
        self,
        *,
        path: str,
        payload: dict[str, Any],
        token: str | None,
    ) -> tuple[int, dict[str, Any], str]:
        """Выполняет POST-запрос и возвращает `(status_code, json_body, raw_text)`."""

        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        request = Request(
            url=f"{self._base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                status_code = int(response.status)
                raw_bytes = response.read()
                raw_text = raw_bytes.decode("utf-8", errors="replace")
        except HTTPError as error:
            raw_bytes = error.read()
            raw_text = raw_bytes.decode("utf-8", errors="replace")
            return int(error.code), self._try_parse_json(raw_text), raw_text
        except (URLError, TimeoutError, socket.timeout) as error:
            raise LoyaltyGatewayError(
                f"Сетевая ошибка обращения к iiko: {error}",
                reason_code="network_error",
                endpoint=path,
                is_transient=True,
            ) from error

        return status_code, self._try_parse_json(raw_text), raw_text

    @staticmethod
    def _is_transient_http_status(status_code: int) -> bool:
        """Определяет статусы iiko, которые стоит считать временными сбоями."""

        return status_code in {408, 429} or 500 <= status_code <= 599

    @staticmethod
    def _try_parse_json(raw_text: str) -> dict[str, Any]:
        """Пытается распарсить JSON-ответ; при неуспехе возвращает пустой словарь."""

        try:
            parsed = json.loads(raw_text or "{}")
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}

    @staticmethod
    def _normalize_phone(raw_phone: str) -> str:
        """Нормализует телефон к формату `+7XXXXXXXXXX`."""

        digits = "".join(ch for ch in str(raw_phone) if ch.isdigit())
        if digits.startswith("7"):
            return f"+{digits}"
        if digits.startswith("8"):
            return f"+7{digits[1:]}"
        if len(digits) == 10:
            return f"+7{digits}"
        if not digits:
            raise LoyaltyGatewayError("Невалидный телефон: отсутствуют цифры.")
        return f"+{digits}"

    @staticmethod
    def _build_card_number(phone_e164: str) -> str:
        """Генерирует детерминированный номер карты на основе телефона и даты."""

        digits = "".join(ch for ch in str(phone_e164) if ch.isdigit())
        if not digits:
            raise LoyaltyGatewayError("Невалидный телефон: не удалось сгенерировать номер карты.")
        date_part = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        return f"{digits}_{date_part}"

    @staticmethod
    def _format_birth_date_for_iiko(raw_birth_date: date | None) -> str | None:
        """Преобразует `date` в формат iiko `YYYY-MM-DD 00:00:00.000`."""

        if raw_birth_date is None:
            return None
        return raw_birth_date.strftime("%Y-%m-%d 00:00:00.000")

    @staticmethod
    def _format_gender_for_iiko(raw_gender: str | None) -> int | None:
        """Преобразует доменное значение пола в код iiko (1/2)."""

        normalized = str(raw_gender or "").strip().lower()
        if normalized == "male":
            return 1
        if normalized == "female":
            return 2
        return None

    @staticmethod
    def _resolve_consent_status(rules_accepted: bool | None) -> int:
        """Возвращает код согласия для iiko (1 - согласен, 0 - не согласен/неизвестно)."""

        return 1 if rules_accepted else 0

    @staticmethod
    def _parse_valid_to(raw_value: str | None) -> str | None:
        """Преобразует дату окончания действия карты в человекочитаемый формат."""

        if not raw_value:
            return None
        raw = str(raw_value).strip()
        if not raw:
            return None

        # Частый формат iiko: "YYYY-MM-DD HH:MM:SS.sss"
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f")
            return parsed.strftime("%d.%m.%Y")
        except ValueError:
            pass

        # Fallback на ISO 8601.
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.strftime("%d.%m.%Y")
        except ValueError:
            return raw

    @staticmethod
    def _select_program_id(programs: list[dict[str, Any]]) -> str | None:
        """Выбирает program_id: по имени «программа лояльности» или первый доступный."""

        target = next(
            (
                item
                for item in programs
                if str(item.get("name") or "").strip().lower() == "программа лояльности"
            ),
            None,
        )
        if target is None:
            target = programs[0]
        program_id = str(target.get("id") or "").strip()
        return program_id or None

    @staticmethod
    def _extract_first_name(data: dict[str, Any]) -> str | None:
        """Извлекает имя клиента из разных вариантов ключей ответа iiko."""

        for key in ("name", "firstName", "first_name"):
            raw_value = data.get(key)
            normalized = str(raw_value or "").strip()
            if normalized:
                return normalized
        return None

    @staticmethod
    def _extract_last_name(data: dict[str, Any]) -> str | None:
        """Извлекает фамилию клиента из разных вариантов ключей ответа iiko."""

        for key in ("surname", "surName", "lastName", "last_name"):
            raw_value = data.get(key)
            normalized = str(raw_value or "").strip()
            if normalized:
                return normalized
        return None

    @staticmethod
    def _extract_email(data: dict[str, Any]) -> str | None:
        """Извлекает email клиента из разных вариантов ключей ответа iiko."""

        for key in ("email", "eMail", "mail"):
            raw_value = data.get(key)
            normalized = str(raw_value or "").strip()
            if normalized:
                return normalized
        return None

    @staticmethod
    def _parse_gender(raw_value: Any) -> str | None:
        """Преобразует значение пола из iiko в доменный формат (`male` / `female`)."""

        if raw_value is None:
            return None

        if isinstance(raw_value, bool):
            return None

        if isinstance(raw_value, int | float):
            numeric = int(raw_value)
            if numeric == 1:
                return "male"
            if numeric == 2:
                return "female"
            return None

        normalized = str(raw_value).strip().lower()
        if not normalized:
            return None

        male_aliases = {"1", "male", "m", "man", "м", "муж", "мужской"}
        female_aliases = {"2", "female", "f", "woman", "ж", "жен", "женский"}
        if normalized in male_aliases:
            return "male"
        if normalized in female_aliases:
            return "female"
        return None

    @staticmethod
    def _parse_birth_date(raw_value: Any) -> date | None:
        """Преобразует дату рождения из iiko в объект `date`."""

        if raw_value is None:
            return None

        raw = str(raw_value).strip()
        if not raw:
            return None

        # Наиболее частые форматы даты в iiko.
        for date_format in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(raw, date_format).date()
            except ValueError:
                continue

        # Fallback на ISO 8601.
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None

    def _extract_customer(self, data: dict[str, Any]) -> LoyaltyCustomer:
        """Преобразует raw-ответ iiko в доменную модель клиента лояльности."""

        customer_id = str(data.get("id") or "").strip()
        if not customer_id:
            raise LoyaltyGatewayError("В ответе iiko отсутствует customer_id.")

        wallets = data.get("walletBalances") or []
        selected_wallet: dict[str, Any] | None = None
        if isinstance(wallets, list) and wallets:
            selected_wallet = next(
                (
                    item
                    for item in wallets
                    if str(item.get("name") or item.get("programName") or "").strip().lower()
                    == "программа лояльности"
                ),
                None,
            )
            if selected_wallet is None:
                selected_wallet = next(
                    (item for item in wallets if str(item.get("type") or "") == "1"),
                    None,
                )
            if selected_wallet is None:
                selected_wallet = wallets[0]

        if selected_wallet is None:
            balance = 0.0
            program_name = ""
        else:
            raw_balance = selected_wallet.get("balance", 0)
            try:
                balance = float(raw_balance)
            except (TypeError, ValueError):
                balance = 0.0
            program_name = str(
                selected_wallet.get("name")
                or selected_wallet.get("programName")
                or selected_wallet.get("walletName")
                or ""
            ).strip()

        raw_cards = data.get("cards") or []
        cards: list[LoyaltyCard] = []
        if isinstance(raw_cards, list):
            for raw_card in raw_cards:
                if not isinstance(raw_card, dict):
                    continue
                number = str(raw_card.get("number") or "").strip()
                if not number:
                    continue
                cards.append(
                    LoyaltyCard(
                        number=number,
                        valid_to=self._parse_valid_to(raw_card.get("validToDate")),
                    )
                )

        return LoyaltyCustomer(
            customer_id=customer_id,
            balance=balance,
            cards=tuple(cards),
            program_name=program_name,
            first_name=self._extract_first_name(data),
            last_name=self._extract_last_name(data),
            gender=self._parse_gender(data.get("sex") or data.get("gender")),
            birth_date=self._parse_birth_date(data.get("birthday") or data.get("birthDate")),
            email=self._extract_email(data),
        )
