"""Unit tests for Fernet token encryption and decryption."""

import pytest
from cryptography.fernet import Fernet

import jobpilot.security.crypto as crypto_module
from jobpilot.config import Settings


def test_encrypt_and_decrypt_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that tokens are reversibly encrypted using Fernet."""
    test_key = Fernet.generate_key().decode("utf-8")
    test_settings = Settings(fernet_key=test_key)

    monkeypatch.setattr(crypto_module, "get_settings", lambda: test_settings)
    crypto_module.get_cipher_suite.cache_clear()

    raw_token = "ya29.a0AfH6SMB_secret_refresh_token_xyz_12345"
    encrypted = crypto_module.encrypt_token(raw_token)

    assert encrypted != raw_token
    assert isinstance(encrypted, str)

    decrypted = crypto_module.decrypt_token(encrypted)
    assert decrypted == raw_token


def test_decrypt_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that invalid ciphertext raises ValueError."""
    test_key = Fernet.generate_key().decode("utf-8")
    test_settings = Settings(fernet_key=test_key)

    monkeypatch.setattr(crypto_module, "get_settings", lambda: test_settings)
    crypto_module.get_cipher_suite.cache_clear()

    with pytest.raises(ValueError, match="Failed to decrypt token"):
        crypto_module.decrypt_token("invalid_encrypted_ciphertext")
