#!/usr/bin/env python3
"""Debug helper: test confirmed-resolution API and append to debug log."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / "debug-980007.log"


def log(msg: str, data: dict, hypothesis_id: str = "A") -> None:
    row = {
        "sessionId": "980007",
        "hypothesisId": hypothesis_id,
        "location": "debug_confirm_api.py",
        "message": msg,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    print(msg, data)


def main() -> None:
    LOG.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=5) as r:
            log("health_ok", {"status": r.status})
    except Exception as e:
        log("health_fail", {"err": str(e)})
        return

    body = json.dumps(
        {
            "selected_text": "# Runbook: order processing Error code - D1",
            "comment": "all vendors linked",
            "source": "historical",
        }
    ).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/findings/0/confirmed-resolution?out_dir=out",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode())
            log(
                "post_ok",
                {
                    "status": r.status,
                    "elapsed_s": round(time.time() - t0, 2),
                    "error_code": payload.get("error_code"),
                },
                hypothesis_id="A",
            )
    except urllib.error.HTTPError as e:
        log("post_http_error", {"code": e.code, "body": e.read().decode()[:500], "elapsed_s": round(time.time() - t0, 2)})
    except Exception as e:
        log("post_fail", {"err": str(e), "elapsed_s": round(time.time() - t0, 2)})


if __name__ == "__main__":
    main()
