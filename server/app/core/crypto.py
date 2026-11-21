"""Encryption of secrets at rest (e.g. API keys of external interfaces).

Secrets are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using keys that live
outside the database (environment variable / secret file on the server). ``MultiFernet``
allows key rotation: new values are encrypted with the first key, all configured keys
can decrypt. Plaintext secrets are never returned by the API – only a masked hint.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class SecretBoxError(Exception):
    pass


class SecretBox:
    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise SecretBoxError("Kein Verschlüsselungsschlüssel konfiguriert")
        try:
            self._fernet = MultiFernet([Fernet(k.strip().encode()) for k in keys])
        except (ValueError, TypeError) as exc:
            raise SecretBoxError("Ungültiger Verschlüsselungsschlüssel (Fernet-Format erwartet)") from exc

    @classmethod
    def from_config(cls, encryption_keys: str) -> SecretBox:
        return cls([k for k in encryption_keys.split(",") if k.strip()])

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise SecretBoxError("Geheimnis konnte nicht entschlüsselt werden (falscher Schlüssel?)") from exc

    def rotate(self, token: str) -> str:
        """Re-encrypt a token with the current primary key."""
        return self._fernet.rotate(token.encode("ascii")).decode("ascii")

    @staticmethod
    def mask(plaintext: str) -> str:
        if len(plaintext) <= 4:
            return "••••"
        return "••••" + plaintext[-4:]

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode("ascii")


@lru_cache
def get_secret_box() -> SecretBox:
    from app.core.config import get_settings

    return SecretBox.from_config(get_settings().encryption_keys)
