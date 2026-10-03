from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def derive_key(secret: str, purpose: str, length: int = 32) -> bytes:
    """Derive an independent key per purpose from WEBOS_SECRET_KEY, so no two uses share one."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(), length=length, salt=None, info=f"webos:{purpose}".encode()
    )
    return hkdf.derive(secret.encode())
