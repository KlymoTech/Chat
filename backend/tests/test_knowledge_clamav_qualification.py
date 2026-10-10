"""Isolated protocol and fail-closed tests for live ClamAV qualification CLI."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from northstar_api.services.object_store import InvalidUpload, ObjectStoreUnavailable
from northstar_api.workers import knowledge_clamav_qualification as qualification


class FakeSocket:
    def __init__(self, reply: bytes) -> None:
        self.reply = reply
        self.sent: list[bytes] = []

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def settimeout(self, _: float) -> None:
        pass

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, _: int) -> bytes:
        reply, self.reply = self.reply, b""
        return reply


@pytest.mark.parametrize(
    ("command", "reply", "expected"),
    [
        (b"PING", b"PONG\x00", "PONG"),
        (
            b"VERSION",
            b"ClamAV 1.5.4/12345/Sat Oct 10 2026\x00",
            "ClamAV 1.5.4/12345/Sat Oct 10 2026",
        ),
    ],
)
def test_probe_uses_loopback_and_checks_protocol(
    monkeypatch: pytest.MonkeyPatch, command: bytes, reply: bytes, expected: str
) -> None:
    fake = FakeSocket(reply)
    connect = Mock(return_value=fake)
    monkeypatch.setattr(qualification.socket, "create_connection", connect)
    assert qualification._probe_command(command, port=3310, timeout=8) == expected
    connect.assert_called_once_with(("127.0.0.1", 3310), timeout=8)
    assert fake.sent == [b"z" + command + b"\x00"]


@pytest.mark.parametrize("reply", [b"PONG", b"BAD\x00", b"", b"\xff\x00"])
def test_ping_never_accepts_invalid_or_incomplete_reply(
    monkeypatch: pytest.MonkeyPatch, reply: bytes
) -> None:
    monkeypatch.setattr(
        qualification.socket, "create_connection", Mock(return_value=FakeSocket(reply))
    )
    with pytest.raises(ObjectStoreUnavailable):
        qualification._probe_command(b"PING", port=3310, timeout=5)


def test_partial_probe_is_not_reported_as_full_detection_qualification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        qualification, "_probe_command",
        Mock(side_effect=["PONG", "ClamAV 1.5.4/12345"]),
    )
    scanner = Mock(return_value=None)
    monkeypatch.setattr(qualification, "scan_with_clamav_instream", scanner)
    result = qualification.qualify_clamav(port=3310, timeout=5)
    assert result["status"] == "partial"
    assert result["test_detection_confirmed"] is False
    scanner.assert_called_once_with(
        qualification._CLEAN_TEST_BYTES, port=3310, timeout_seconds=5
    )


def test_diagnostic_proves_clean_and_harmless_test_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        qualification, "_probe_command",
        Mock(side_effect=["PONG", "ClamAV 1.5.4/12345"]),
    )
    scanner = Mock(side_effect=[None, InvalidUpload("EICAR FOUND")])
    monkeypatch.setattr(qualification, "scan_with_clamav_instream", scanner)
    assert len(qualification._EICAR_TEST_BYTES) == 68
    result = qualification.qualify_clamav(port=3310, timeout=5, test_detection=True)
    assert result["status"] == "checked"
    assert result["test_detection_confirmed"] is True
    assert scanner.call_count == 2


def test_detection_false_negative_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        qualification, "_probe_command",
        Mock(side_effect=["PONG", "ClamAV 1.5.4/12345"]),
    )
    monkeypatch.setattr(
        qualification, "scan_with_clamav_instream", Mock(return_value=None)
    )
    with pytest.raises(ObjectStoreUnavailable, match="did not reject"):
        qualification.qualify_clamav(port=3310, timeout=5, test_detection=True)


@pytest.mark.parametrize(("port", "timeout"), [(0, 10), (3310, 0), (65536, 10)])
def test_invalid_probe_settings_fail_before_network(
    monkeypatch: pytest.MonkeyPatch, port: int, timeout: int
) -> None:
    call = Mock()
    monkeypatch.setattr(qualification, "_probe_command", call)
    with pytest.raises(ValueError):
        qualification.qualify_clamav(port=port, timeout=timeout)
    call.assert_not_called()
