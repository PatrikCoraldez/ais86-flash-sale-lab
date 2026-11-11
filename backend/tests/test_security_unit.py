import asyncio

import pytest

from app.security import (
    ApiError,
    RateLimiter,
    constant_time_equals,
    sanitize_validation_errors,
    validate_idempotency_key,
)


def test_constant_time_equals() -> None:
    assert constant_time_equals("a" * 40, "a" * 40)
    assert not constant_time_equals("a" * 40, "b" * 40)
    assert not constant_time_equals("short", "a" * 40)


def test_idempotency_key_accepts_valid_values() -> None:
    assert validate_idempotency_key("abcd1234") == "abcd1234"
    assert validate_idempotency_key("A-z_0" * 10) == "A-z_0" * 10


@pytest.mark.parametrize("value", [None, "", "short", "x" * 81, "has space", "slash/yes", "ñ" * 10])
def test_idempotency_key_rejects_invalid_values(value: str | None) -> None:
    with pytest.raises(ApiError) as error:
        validate_idempotency_key(value)
    assert error.value.status_code == 422
    assert error.value.code == "VALIDATION_ERROR"


def test_rate_limiter_enforces_limit() -> None:
    async def scenario() -> list[bool]:
        limiter = RateLimiter(window_seconds=60)
        return [await limiter.allow("client", 2) for _ in range(3)]

    assert asyncio.run(scenario()) == [True, True, False]


def test_sanitize_validation_errors_removes_raw_input() -> None:
    errors = [
        {
            "loc": ("body", "items", 0, "quantity"),
            "msg": "Input should be greater than or equal to 1",
            "type": "greater_than_equal",
            "input": "secret-value",
            "ctx": {"ge": 1},
        }
    ]
    sanitized = sanitize_validation_errors(errors)
    assert sanitized == [
        {
            "loc": ["body", "items", "0", "quantity"],
            "msg": "Input should be greater than or equal to 1",
            "type": "greater_than_equal",
        }
    ]
