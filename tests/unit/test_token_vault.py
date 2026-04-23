import pytest

from deepfolder.auth.token_vault import TokenVault


@pytest.fixture
def vault() -> TokenVault:
    return TokenVault(secret_key="supersecretkey1234567890123456789012345678")


def test_encrypt_decrypt_roundtrip(vault: TokenVault) -> None:
    plaintext = "ya29.refresh_token_value"
    ciphertext = vault.encrypt(plaintext)
    assert vault.decrypt(ciphertext) == plaintext


def test_ciphertext_differs_from_plaintext(vault: TokenVault) -> None:
    plaintext = "ya29.refresh_token_value"
    ciphertext = vault.encrypt(plaintext)
    assert ciphertext != plaintext


def test_different_encryptions_produce_different_ciphertexts(vault: TokenVault) -> None:
    plaintext = "ya29.refresh_token_value"
    c1 = vault.encrypt(plaintext)
    c2 = vault.encrypt(plaintext)
    assert c1 != c2  # Fernet uses random IVs


def test_decrypt_invalid_token_raises(vault: TokenVault) -> None:
    with pytest.raises(Exception):
        vault.decrypt("not-valid-fernet-token")
