"""Budget-overrun alert (POST to a webhook, e.g. n8n).

Never hardcode the URL or token: they come from the environment variables
``CONCHO_ALERT_WEBHOOK_URL`` and ``CONCHO_ALERT_WEBHOOK_TOKEN`` (header name in
``CONCHO_ALERT_WEBHOOK_HEADER``, default ``X-Concho-Token``), as in AutoTVD PR #5.
Unset URL = alerts disabled. The variables are read at call time.
"""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime


def fire_budget_webhook(summary: list[dict], grand_total: float, target: float) -> None:
    """POST a budget-overrun alert to CONCHO_ALERT_WEBHOOK_URL (if configured)."""
    url = os.environ.get("CONCHO_ALERT_WEBHOOK_URL", "")
    token = os.environ.get("CONCHO_ALERT_WEBHOOK_TOKEN", "")
    header = os.environ.get("CONCHO_ALERT_WEBHOOK_HEADER", "X-Concho-Token")
    if not url:
        return
    delta = grand_total - target
    payload = json.dumps({
        "event":       "budget_overrun",
        "grand_total": round(grand_total, 2),
        "target":      round(target, 2),
        "delta":       round(delta, 2),
        "delta_pct":   round(delta / target * 100, 2) if target else 0,
        "timestamp":   datetime.now().isoformat(),
        "clusters":    [
            {"cluster": r["cluster"], "total": round(r["total"], 2)}
            for r in summary
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            **({header: token} if token else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"   n8n webhook fired — HTTP {resp.status}")
    except urllib.error.URLError as exc:
        print(f"   n8n webhook failed: {exc}")
