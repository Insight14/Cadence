"""Token encryption and decryption helpers using Fernet symmetric encryption."""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from jobpilot.config import get_settings


@lru_cache(maxsize=1)
def get_cipher_suite() -> Fernet:
    """Return a cached Fernet cipher initialized from config."""
    settings = get_settings()
    key = settings.fernet_key.encode("utf-8")
    return Fernet(key)


def encrypt_token(plain_token: str) -> str:
    """Encrypt a plain text token (e.g. Google refresh token) to base64 string."""
    cipher = get_cipher_suite()
    encrypted_bytes = cipher.encrypt(plain_token.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a Fernet encrypted base64 string back to plain text."""
    cipher = get_cipher_suite()
    try:
        decrypted_bytes = cipher.decrypt(encrypted_token.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt token: invalid token or corrupt key") from exc
