import logging

from app.logging_config import SecretMaskingFilter


def test_secret_masking_filter_redacts_configured_secret():
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="token=%s used", args=("super-secret-token",), exc_info=None,
    )
    filt = SecretMaskingFilter(secrets=["super-secret-token"])

    filt.filter(record)

    assert "super-secret-token" not in record.msg
    assert "***MASKED***" in record.msg


def test_secret_masking_filter_redacts_bearer_pattern():
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="Authorization: Bearer abc123.def456", args=(), exc_info=None,
    )
    filt = SecretMaskingFilter(secrets=[])

    filt.filter(record)

    assert "abc123.def456" not in record.msg
    assert "***MASKED***" in record.msg
