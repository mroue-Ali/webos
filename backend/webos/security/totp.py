"""TOTP (RFC 6238) with replay protection, and encryption of the stored secret."""

import base64
import hmac
import re

import pyotp
from cryptography.fernet import Fernet

STEP_SECONDS = 30
_CODE = re.compile(r"\d{6}")


def new_secret() -> str:
    return str(pyotp.random_base32())


def provisioning_uri(secret: str, username: str) -> str:
    return str(pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="webos"))


def verify(secret: str, code: str, *, last_step: int, now: float) -> int | None:
    """Return the matched time step, or None.

    Accepts the previous, current and next step to allow for clock drift, but never a step
    at or before `last_step`, so a code can be used only once.
    """
    code = code.replace(" ", "")
    if not _CODE.fullmatch(code):
        return None
    totp = pyotp.TOTP(secret)
    current = int(now // STEP_SECONDS)
    for step in (current - 1, current, current + 1):
        if step > last_step and hmac.compare_digest(str(totp.at(step * STEP_SECONDS)), code):
            return step
    return None


class SecretBox:
    """Encrypts the TOTP secret at rest, so a copy of the database alone can't mint codes."""

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def seal(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def open(self, token: str) -> str:
        return self._fernet.decrypt(token.encode()).decode()
