"""CP3 output limiter tests: byte limits, truncation, redaction, UTF-8 safety."""

from __future__ import annotations

import io

import pytest

from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.execution.output_limit import OutputLimit, OutputLimiter
from ant_orchestrator.security.redaction.redactor import Redactor


def _limiter(max_bytes: int = 1024) -> OutputLimiter:
    return OutputLimiter(OutputLimit(max_bytes), Redactor())


class TestOutputLimit:
    def test_minimum_valid(self) -> None:
        OutputLimit(max_bytes=100)

    def test_too_small_for_marker(self) -> None:
        with pytest.raises(InvariantViolation):
            OutputLimit(max_bytes=1)


class TestProcessBytes:
    def test_empty_output(self) -> None:
        r = _limiter().process_bytes(b"")
        assert r.text == ""
        assert r.truncated is False
        assert r.original_bytes == 0

    def test_below_limit(self) -> None:
        r = _limiter(1024).process_bytes(b"hello")
        assert r.text == "hello"
        assert r.truncated is False
        assert r.original_bytes == 5

    def test_exact_limit(self) -> None:
        data = b"x" * 100
        r = _limiter(100).process_bytes(data)
        assert r.truncated is False
        assert r.original_bytes == 100

    def test_over_limit_one_byte(self) -> None:
        data = b"x" * 101
        r = _limiter(100).process_bytes(data)
        assert r.truncated is True
        assert r.original_bytes == 101
        assert len(r.text.encode("utf-8")) <= 100

    def test_over_limit_large(self) -> None:
        data = b"y" * 10000
        r = _limiter(100).process_bytes(data)
        assert r.truncated is True
        assert r.original_bytes == 10000
        assert "\n... [OUTPUT TRUNCATED]" in r.text

    def test_marker_within_limit(self) -> None:
        data = b"z" * 500
        r = _limiter(100).process_bytes(data)
        assert len(r.text.encode("utf-8")) <= 100

    def test_original_bytes_reflects_total(self) -> None:
        data = b"a" * 5000
        r = _limiter(100).process_bytes(data)
        assert r.original_bytes == 5000

    def test_utf8_multibyte_at_boundary(self) -> None:
        data = b"a" * 98 + "é".encode()
        r = _limiter(100).process_bytes(data)
        assert r.original_bytes == 100
        assert r.truncated is False

    def test_invalid_utf8_deterministic(self) -> None:
        data = b"\xff\xfe" * 10
        r = _limiter(200).process_bytes(data)
        assert "�" in r.text
        assert r.original_bytes == 20

    def test_secret_below_limit_redacted(self) -> None:
        data = b"token: sk-abcdef1234567890abcdefgh"
        r = _limiter(1024).process_bytes(data)
        assert "sk-abc" not in r.text
        assert "[REDACTED]" in r.text

    def test_secret_near_boundary_redacted(self) -> None:
        secret = b"export API_KEY=sk-verysecretkey1234567890ab"
        padding = b"x" * 60
        data = padding + secret
        r = _limiter(100).process_bytes(data)
        assert "sk-verysecret" not in r.text

    def test_pem_near_boundary(self) -> None:
        pem = b"-----BEGIN RSA PRIVATE KEY-----\nMIIdata\n-----END RSA PRIVATE KEY-----"
        data = b"a" * 30 + pem
        r = _limiter(100).process_bytes(data)
        assert "BEGIN RSA PRIVATE KEY" not in r.text

    def test_final_encoded_within_limit(self) -> None:
        data = b"a" * 10000
        limit = 200
        r = _limiter(limit).process_bytes(data)
        assert len(r.text.encode("utf-8")) <= limit

    def test_deterministic_result(self) -> None:
        lim = _limiter(100)
        data = b"deterministic" * 20
        r1 = lim.process_bytes(data)
        r2 = lim.process_bytes(data)
        assert r1.text == r2.text
        assert r1.truncated == r2.truncated


class TestBoundaryRedaction:
    def test_pem_cross_boundary_header_redacted(self) -> None:
        """PEM header within retained region but footer beyond → header redacted."""
        prefix = b"x" * 100
        pem_header = b"-----BEGIN RSA PRIVATE KEY-----\n"
        pem_body = b"A" * 1600  # footer well outside retention=200+256=456
        pem_footer = b"-----END RSA PRIVATE KEY-----\n"
        data = prefix + pem_header + pem_body + pem_footer
        r = _limiter(200).process_bytes(data)
        assert "BEGIN RSA PRIVATE KEY" not in r.text

    def test_pem_complete_within_retention_redacted(self) -> None:
        """Complete PEM within retention window → primary redaction handles it."""
        pem = b"-----BEGIN RSA PRIVATE KEY-----\nMIIbody\n-----END RSA PRIVATE KEY-----"
        data = b"a" * 10 + pem
        r = _limiter(1024).process_bytes(data)
        assert "BEGIN RSA PRIVATE KEY" not in r.text

    def test_bearer_token_straddling_limit_redacted(self) -> None:
        """Bearer token starting before max_bytes boundary → within margin, redacted."""
        prefix = b"a" * 190
        token = b"Bearer tokenvalueabcdef12345678"  # starts at 190, within margin
        data = prefix + token
        r = _limiter(200).process_bytes(data)
        assert "tokenvalueabcdef" not in r.text

    def test_api_token_at_max_boundary_redacted(self) -> None:
        """API token at boundary → captured by safety margin, redacted."""
        prefix = b"a" * 195
        token = b"sk-abcdefghijklmnopqrstuv"  # starts at 195 < retention
        data = prefix + token
        r = _limiter(200).process_bytes(data)
        assert "sk-abcdefghijklmnopqrstuv" not in r.text

    def test_pem_cross_boundary_output_within_limit(self) -> None:
        """After PEM redaction at boundary, output still within max_bytes."""
        prefix = b"x" * 100
        pem_header = b"-----BEGIN RSA PRIVATE KEY-----\n"
        pem_body = b"A" * 1600
        pem_footer = b"-----END RSA PRIVATE KEY-----\n"
        data = prefix + pem_header + pem_body + pem_footer
        r = _limiter(200).process_bytes(data)
        assert len(r.text.encode("utf-8")) <= 200


class TestDrainAndProcess:
    def test_pipe_drain(self) -> None:
        pipe = io.BytesIO(b"pipe content")
        r = _limiter(1024).drain_and_process(pipe)
        assert r.text == "pipe content"
        assert r.truncated is False

    def test_pipe_drain_bounded(self) -> None:
        pipe = io.BytesIO(b"x" * 5000)
        r = _limiter(100).drain_and_process(pipe)
        assert r.truncated is True
        assert r.original_bytes == 5000
        assert len(r.text.encode("utf-8")) <= 100

    def test_pipe_drain_secret_redacted(self) -> None:
        pipe = io.BytesIO(b"password: ghp_abcdef1234567890abcdefgh")
        r = _limiter(1024).drain_and_process(pipe)
        assert "ghp_" not in r.text
        assert "[REDACTED]" in r.text

    def test_empty_pipe(self) -> None:
        pipe = io.BytesIO(b"")
        r = _limiter(100).drain_and_process(pipe)
        assert r.text == ""
        assert r.original_bytes == 0
