from app.core.security import hash_password, verify_password, new_token, hash_token


def test_password_round_trip():
    h = hash_password("s3cret")
    assert h != "s3cret"
    assert verify_password("s3cret", h) is True
    assert verify_password("wrong", h) is False


def test_new_token_returns_raw_and_matching_hash():
    raw, h = new_token()
    assert isinstance(raw, str) and len(raw) > 20
    assert h == hash_token(raw)
    assert h != raw  # stored hash is not the raw token


def test_hash_token_is_deterministic():
    assert hash_token("abc") == hash_token("abc")
