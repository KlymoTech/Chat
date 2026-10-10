"""Operator-invoked live ClamAV INSTREAM qualification (no production writes).

This command is deliberately not a startup readiness bypass or a release gate.
"""

from __future__ import annotations

import argparse
import json
import socket
from typing import Any

from northstar_api.config import get_settings
from northstar_api.services.object_store import (
    InvalidUpload,
    ObjectStoreUnavailable,
    scan_with_clamav_instream,
)

# Split the harmless EICAR industry-standard test string so antivirus scanners
# inspecting repository source do not confuse it with a malicious upload.
_EICAR_TEST_BYTES = (
    b"X5O!P%@AP[4" + b"\\PZX54(P^)7CC)7}" + b"$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)
_CLEAN_TEST_BYTES = b"Northstar local ClamAV readiness probe; safe test payload."


def _probe_command(command: bytes, *, port: int, timeout: float) -> str:
    """Issue a bounded, NUL-framed command to the loopback ClamAV daemon."""
    if command not in {b"PING", b"VERSION"}:
        raise ValueError("Unsupported scanner probe command")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
            conn.settimeout(timeout)
            conn.sendall(b"z" + command + b"\x00")
            response = bytearray()
            terminated = False
            while len(response) < 512:
                chunk = conn.recv(min(128, 512 - len(response)))
                if not chunk:
                    break
                response.extend(chunk)
                if b"\x00" in response or b"\n" in response:
                    terminated = True
                    break
    except (OSError, TimeoutError) as exc:
        raise ObjectStoreUnavailable("ClamAV probe connection unavailable") from exc
    if not terminated:
        raise ObjectStoreUnavailable("ClamAV probe did not return a full response")
    try:
        raw = bytes(response).split(b"\x00", 1)[0].split(b"\n", 1)[0]
        value = raw.decode("ascii")
    except UnicodeError as exc:
        raise ObjectStoreUnavailable("ClamAV probe returned invalid bytes") from exc
    if command == b"PING" and value != "PONG":
        raise ObjectStoreUnavailable("ClamAV PING did not succeed")
    if command == b"VERSION" and not value.startswith("ClamAV "):
        raise ObjectStoreUnavailable("ClamAV version response is invalid")
    return value


def qualify_clamav(
    *, port: int, timeout: float, test_detection: bool = False
) -> dict[str, Any]:
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("ClamAV port is invalid")
    if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 600:
        raise ValueError("ClamAV timeout is invalid")
    _probe_command(b"PING", port=port, timeout=timeout)
    version = _probe_command(b"VERSION", port=port, timeout=timeout)
    scan_with_clamav_instream(_CLEAN_TEST_BYTES, port=port, timeout_seconds=timeout)
    if test_detection:
        try:
            scan_with_clamav_instream(
                _EICAR_TEST_BYTES, port=port, timeout_seconds=timeout
            )
        except InvalidUpload:
            pass
        else:
            raise ObjectStoreUnavailable(
                "ClamAV did not reject the standard antivirus test payload"
            )
    return {
        "status": "checked" if test_detection else "partial",
        "version": version,
        "clean_accepted": True,
        "test_detection_confirmed": test_detection,
        "host": "127.0.0.1",
        "port": port,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify the existing local ClamAV upload scanner"
    )
    parser.add_argument(
        "--test-eicar",
        action="store_true",
        help="Also send the harmless industry-standard detection test string",
    )
    args = parser.parse_args()
    settings = get_settings()
    try:
        result = qualify_clamav(
            port=settings.knowledge_clamav_port,
            timeout=float(settings.knowledge_clamav_timeout_seconds),
            test_detection=args.test_eicar,
        )
    except (ValueError, InvalidUpload, ObjectStoreUnavailable) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from exc
    print(json.dumps(result, sort_keys=True))
    if not args.test_eicar:
        # A connectivity-only check is never sufficient qualification.
        raise SystemExit(2)


if __name__ == "__main__":
    main()
