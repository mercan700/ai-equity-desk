#!/usr/bin/env python3
"""Checks that ai-equity-desk can run on this computer and saves settings.

  check_setup.py                       run all checks
  check_setup.py --install             pip-install missing packages first
  check_setup.py --sec-user-agent "Jane Doe jane@example.com"
  check_setup.py --market BIST         set the default market
  check_setup.py --offline             skip network checks
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_SCRIPTS = os.path.join(HERE, "..", "..", "desk-data", "scripts")
sys.path.insert(0, os.path.abspath(DATA_SCRIPTS))

PACKAGES = {"yfinance": "yfinance", "pandas": "pandas", "requests": "requests"}


def check(name, fn):
    try:
        detail = fn()
        return {"check": name, "ok": True, "detail": detail}
    except Exception as e:  # report every failure, never crash
        return {"check": name, "ok": False, "detail": f"{type(e).__name__}: {e}"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--install", action="store_true")
    p.add_argument("--sec-user-agent")
    p.add_argument("--market", choices=["US", "BIST"])
    p.add_argument("--offline", action="store_true")
    a = p.parse_args()

    def python_version():
        if sys.version_info < (3, 9):
            raise RuntimeError(f"Python 3.9+ required, found {sys.version.split()[0]}")
        return sys.version.split()[0]

    results = [check("python>=3.9", python_version)]

    missing = [pip for mod, pip in PACKAGES.items() if importlib.util.find_spec(mod) is None]
    if missing and a.install:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", *missing], check=False)
        missing = [pip for mod, pip in PACKAGES.items() if importlib.util.find_spec(mod) is None]
    results.append({"check": "packages", "ok": not missing,
                    "detail": "all installed" if not missing else f"missing: {' '.join(missing)}"})
    if missing:
        print(json.dumps({"ready": False, "results": results,
                          "fix": f"{sys.executable} -m pip install {' '.join(missing)}"}))
        return 1

    from deskcore import config, macro, prices, sec  # noqa: E402

    updates = {}
    if a.sec_user_agent:
        updates["sec_user_agent"] = a.sec_user_agent.strip()
    if a.market:
        updates["default_market"] = a.market
    cfg = config.save(updates) if updates else config.load()

    def writable():
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        probe = config.CACHE_DIR / ".probe"
        probe.write_text("ok")
        probe.unlink()
        return str(config.HOME)

    results.append(check("data folder", writable))
    results.append({"check": "default market", "ok": True, "detail": cfg["default_market"]})
    ua_ok = "@" in cfg.get("sec_user_agent", "")
    results.append({"check": "SEC user-agent", "ok": ua_ok,
                    "detail": "set" if ua_ok else "not set (needed only for SEC filings)"})

    if not a.offline:
        results.append(check("yfinance prices", lambda: f"AAPL close {prices.quote('AAPL')['close']}"))
        results.append(check("FRED macro", lambda: f"DGS10 {macro.snapshot(['DGS10'])['DGS10'].get('value')}"))
        if ua_ok:
            results.append(check("SEC EDGAR", lambda: sec.cik_for("AAPL")[1]))

    required = {"python>=3.9", "packages", "data folder", "yfinance prices"}
    ready = all(r["ok"] for r in results if r["check"] in required)
    print(json.dumps({"ready": ready, "results": results}, ensure_ascii=False))
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
