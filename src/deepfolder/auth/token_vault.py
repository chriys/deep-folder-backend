import base64
import hashlib

from cryptography.fernet import Fernet


class TokenVault:
    """Fernet-encrypts refresh tokens at app layer before DB storage.

    Key rotation: When rotating to a new secret_key, instantiate a new vault with the new key
    and decrypt all ciphertexts with the old vault, then re-encrypt with the new vault.
    Old ciphertexts are tied to their key; there is no multi-key support in Fernet itself.
    """

    def __init__(self, secret_key: str) -> None:
        key_bytes = hashlib.sha256(secret_key.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(key_bytes))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()
