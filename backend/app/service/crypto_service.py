import logging
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)


class CryptoService:
    """
    本地凭据对称加密服务。
    使用 Fernet（AES-128-CBC + HMAC-SHA256）对邮箱授权码与 OAuth 令牌加密落盘。
    """

    def __init__(self, key_file: Path | None = None, explicit_key: str | None = None) -> None:
        self._key_file = key_file or settings.secret_key_file
        self._explicit_key = explicit_key or settings.secret_key
        self._fernet: Fernet | None = None

    def _get_fernet(self) -> Fernet:
        if self._fernet is not None:
            return self._fernet

        if self._explicit_key:
            key_bytes = self._explicit_key.encode("utf-8")
        elif self._key_file.exists():
            key_bytes = self._key_file.read_bytes().strip()
        else:
            key_bytes = Fernet.generate_key()
            self._key_file.parent.mkdir(parents=True, exist_ok=True)
            self._key_file.write_bytes(key_bytes)
            logger.info("Generated new local encryption key for MailHub credentials.")

        self._fernet = Fernet(key_bytes)
        return self._fernet

    def encrypt(self, plaintext: str | None) -> str | None:
        """加密明文字符串；空值直接返回 None。"""
        if not plaintext:
            return None
        return self._get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str | None) -> str | None:
        """解密密文字符串；解密失败记录告警并返回 None。"""
        if not ciphertext:
            return None
        try:
            return self._get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.warning("Failed to decrypt credential token due to invalid key or corrupted data.")
            return None


crypto_service = CryptoService()
