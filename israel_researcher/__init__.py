# ── SSL cert fix — must run before yfinance / requests import ──────────────────
# On Windows, if the home directory contains non-ASCII characters (e.g. Hebrew),
# curl_cffi (used by yfinance) cannot open the certifi CA bundle and raises
# curl error 77. We copy it to an ASCII-only temp path and set all relevant vars.
import os as _os
import shutil as _shutil


def _fix_ssl_cert_path() -> None:
    try:
        import certifi as _certifi
        src = _certifi.where()
        try:
            src.encode("ascii")
            return  # Path is already ASCII-safe
        except UnicodeEncodeError:
            pass
        dst = _os.path.join(_os.environ.get("TEMP", "C:\\Temp"), "brokai_cacert.pem")
        _shutil.copy2(src, dst)
        for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
            _os.environ[var] = dst
        print(f"[SSL] Cert path fixed (Hebrew home dir) -> {dst}")
    except Exception as _e:
        print(f"[SSL] Warning: {_e}")


_fix_ssl_cert_path()
# ────────────────────────────────────────────────────────────────────────────────

from .researcher import run_research_cycle, main

__all__ = ["run_research_cycle", "main"]
