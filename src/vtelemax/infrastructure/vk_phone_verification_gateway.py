"""HTTP gateway for VK Mini App phone verification status polling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal
from urllib import parse, request
from urllib.error import HTTPError, URLError


class VkPhoneVerificationGatewayError(RuntimeError):
    """Raised when VK phone verification status cannot be fetched or parsed."""


VkPhoneVerificationState = Literal["verified", "pending", "failed", "not_found"]


@dataclass(frozen=True, slots=True)
class VkPhoneVerificationStatus:
    """Normalized status returned by the external VK phone verification service."""

    state: VkPhoneVerificationState
    phone_e164: str | None = None
    message: str | None = None

    @property
    def is_verified(self) -> bool:
        """Returns `True` when status is verified and phone is present."""

        return self.state == "verified" and bool(self.phone_e164)


class HttpVkPhoneVerificationGateway:
    """HTTP client for polling external VK Mini App phone verification status."""

    def __init__(
        self,
        *,
        status_url: str,
        api_token: str = "",
        timeout_seconds: float = 5.0,
    ) -> None:
        self._status_url = status_url.strip()
        self._api_token = api_token.strip()
        self._timeout_seconds = timeout_seconds

    def check_status(self, *, vk_user_id: int) -> VkPhoneVerificationStatus:
        """Fetches verification status for one VK user id."""

        if not self._status_url:
            raise VkPhoneVerificationGatewayError("Status URL is not configured.")

        try:
            response_data = self._perform_request(vk_user_id=vk_user_id)
        except (HTTPError, URLError, TimeoutError) as error:
            raise VkPhoneVerificationGatewayError(
                f"Failed to fetch VK phone verification status: {error}"
            ) from error
        except json.JSONDecodeError as error:
            raise VkPhoneVerificationGatewayError(
                f"Invalid JSON from VK phone verification service: {error}"
            ) from error

        raw_status = str(response_data.get("status", "pending")).strip().lower()
        if raw_status not in {"verified", "pending", "failed", "not_found"}:
            raw_status = "pending"

        phone_value = (
            str(response_data.get("phone_e164", "")).strip()
            or str(response_data.get("phone", "")).strip()
            or None
        )
        message = (
            str(response_data.get("message", "")).strip()
            or str(response_data.get("error", "")).strip()
            or None
        )
        return VkPhoneVerificationStatus(
            state=raw_status,  # type: ignore[arg-type]
            phone_e164=phone_value,
            message=message,
        )

    def _perform_request(self, *, vk_user_id: int) -> dict[str, object]:
        """Performs GET request and returns decoded JSON object."""

        parsed = parse.urlsplit(self._status_url)
        query = dict(parse.parse_qsl(parsed.query, keep_blank_values=True))
        query["vk_user_id"] = str(vk_user_id)
        url = parse.urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parse.urlencode(query),
                parsed.fragment,
            )
        )

        headers = {"Accept": "application/json"}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"

        http_request = request.Request(url=url, headers=headers, method="GET")
        with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
            payload = response.read().decode("utf-8")
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            raise VkPhoneVerificationGatewayError("Service returned non-object JSON payload.")
        return decoded
