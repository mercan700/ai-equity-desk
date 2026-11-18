"""Output and error handling shared by every desk script."""
import json
import sys

from . import DeskError


def friendly_error(e):
    if isinstance(e, DeskError):
        return str(e)
    name = type(e).__name__
    if "RateLimit" in name:
        return "Yahoo Finance is rate-limiting this computer. Wait a few minutes and try again."
    if name in ("ConnectionError", "Timeout", "ReadTimeout", "ConnectTimeout"):
        return "No connection to the data source. Check the internet connection."
    return f"{name}: {e}. If this repeats, run desk-setup to check the installation."


def emit(obj, pretty=False):
    """One line of compact JSON on stdout, UTF-8 regardless of the console code page."""
    text = json.dumps(obj, ensure_ascii=False, default=str,
                      indent=2 if pretty else None,
                      separators=None if pretty else (",", ":"))
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.flush()


def run(fn, pretty=False):
    """Call fn(), print its result or an {"error": ...} object, return the exit code."""
    try:
        out = fn()
    except Exception as e:  # noqa: BLE001 - every failure becomes a readable message
        emit({"error": friendly_error(e)})
        return 1
    emit(out, pretty)
    return 0
