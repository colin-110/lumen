import uuid

import pytest
from jose import JWTError

from app.core import security


def test_password_hash_roundtrip():
    hashed = security.get_password_hash("correct horse battery staple")
    assert security.verify_password("correct horse battery staple", hashed)
    assert not security.verify_password("wrong password", hashed)


def test_password_hash_is_salted():
    a = security.get_password_hash("same password")
    b = security.get_password_hash("same password")
    assert a != b  # different salts -> different hashes for the same input


def test_verify_password_rejects_garbage_hash_without_raising():
    assert security.verify_password("anything", "not-a-real-bcrypt-hash") is False


def test_bcrypt_72_byte_truncation_is_handled_safely():
    # bcrypt silently ignores bytes past 72; passwords differing only after
    # that point must still verify against the same hash without raising.
    long_password = "x" * 100
    hashed = security.get_password_hash(long_password)
    assert security.verify_password("x" * 100, hashed)
    assert security.verify_password("x" * 72 + "y" * 28, hashed)


def test_access_and_refresh_tokens_roundtrip():
    user_id = uuid.uuid4()
    access = security.create_access_token(user_id)
    refresh = security.create_refresh_token(user_id)

    access_payload = security.decode_token(access)
    refresh_payload = security.decode_token(refresh)

    assert access_payload["sub"] == str(user_id)
    assert access_payload["type"] == security.TokenType.ACCESS.value
    assert refresh_payload["type"] == security.TokenType.REFRESH.value
    # Distinct jti per token, even for the same subject issued back-to-back.
    assert access_payload["jti"] != refresh_payload["jti"]


def test_decode_token_rejects_tampered_signature():
    token = security.create_access_token(uuid.uuid4())
    tampered = token[:-4] + ("0000" if token[-4:] != "0000" else "1111")
    with pytest.raises(JWTError):
        security.decode_token(tampered)


def test_decode_token_rejects_garbage():
    with pytest.raises(JWTError):
        security.decode_token("not.a.jwt")
