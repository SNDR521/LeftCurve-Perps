from app.core.security import encrypt_credentials, decrypt_credentials


def test_credentials_roundtrip():
    data = {"api_key": "abc123", "api_secret": "s3cr3t"}
    token = encrypt_credentials(data)
    assert isinstance(token, str)
    assert "s3cr3t" not in token          # encrypted, not plaintext
    assert decrypt_credentials(token) == data


def test_token_is_nondeterministic_but_decryptable():
    data = {"api_key": "k", "api_secret": "v"}
    t1, t2 = encrypt_credentials(data), encrypt_credentials(data)
    assert t1 != t2                        # Fernet embeds a random IV/timestamp
    assert decrypt_credentials(t1) == decrypt_credentials(t2) == data
