"""OTP delivery adapters. Console sender is for local development only (refused in production by config)."""

from __future__ import annotations

from typing import Protocol

from clinicdesk.core.logging import log, mask_phone


class OtpSender(Protocol):
    async def send(self, phone: str, code: str) -> None: ...


class ConsoleOtpSender:
    async def send(self, phone: str, code: str) -> None:
        # Dev-only: prints the code so a developer can sign in without a provider.
        log.warning("dev_otp", phone=mask_phone(phone), code=code)


class RecordingOtpSender:
    """Test double: keeps the last code per phone."""

    def __init__(self) -> None:
        self.codes: dict[str, str] = {}

    async def send(self, phone: str, code: str) -> None:
        self.codes[phone] = code
