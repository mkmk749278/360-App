#!/usr/bin/env python3
"""Healthcheck — verifies the 360-Crypto-scalping-V2 engine is running and healthy."""
import os
import sys
import time

# Maximum age (seconds) of the heartbeat file before the scanner is
# considered stale.  Must be longer than a worst-case scan cycle.
_HEARTBEAT_MAX_AGE_SECONDS = 120.0
_HEARTBEAT_PATH = os.path.join(os.path.dirname(__file__), "data", "scanner_heartbeat")


def _engine_process_running() -> bool:
    """Return True if a Python process running src.main is found in /proc."""
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/cmdline", "rb") as fh:
                    cmdline = fh.read().replace(b"\x00", b" ").decode("utf-8", errors="replace")
                if "python" in cmdline and "src.main" in cmdline:
                    return True
            except (FileNotFoundError, PermissionError):
                continue
    except FileNotFoundError:
        pass
    return False


def _config_importable() -> bool:
    """Return True if the engine config module can be imported (proves deps are installed)."""
    try:
        import config
        # Access a known attribute to confirm the module loaded correctly
        _ = config.BINANCE_REST_BASE
        return True
    except Exception:
        return False


def _logs_dir_exists() -> bool:
    """Return True if the logs directory exists."""
    return os.path.isdir(os.path.join(os.path.dirname(__file__), "logs"))


def _scanner_heartbeat_fresh() -> bool:
    """Return True if the scanner heartbeat file was touched recently.

    If the heartbeat file doesn't exist yet (e.g. during initial boot), the
    check passes to avoid false negatives before the first scan cycle.
    """
    if not os.path.isfile(_HEARTBEAT_PATH):
        return True  # Not yet created — engine is still booting
    try:
        age = time.time() - os.path.getmtime(_HEARTBEAT_PATH)
        return age < _HEARTBEAT_MAX_AGE_SECONDS
    except OSError:
        return True  # Cannot stat — treat as fresh to avoid false negatives


if not _engine_process_running():
    print("Engine process (src.main) not found.", file=sys.stderr)
    sys.exit(1)

if not _config_importable():
    print("Config module could not be imported — dependency issue.", file=sys.stderr)
    sys.exit(1)

if not _logs_dir_exists():
    print("logs/ directory does not exist.", file=sys.stderr)
    sys.exit(1)

if not _scanner_heartbeat_fresh():
    print(
        f"Scanner heartbeat is stale (>{_HEARTBEAT_MAX_AGE_SECONDS:.0f}s old).",
        file=sys.stderr,
    )
    sys.exit(1)

sys.exit(0)
