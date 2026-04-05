#!/usr/bin/env bash
set -euo pipefail

if [ -f sources_v2.yaml ]; then
  python workers/weekly_discover.py --window 1d --sources sources_v2.yaml --config config_v2.yaml || true
else
  python workers/weekly_discover.py --window 1d --config config_v2.yaml || true
fi

if [ ! -f state/latest_discovery.json ]; then
  python - <<'PY'
import json
import os
from datetime import datetime, timezone

os.makedirs("state", exist_ok=True)
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "window": "1d",
    "items": [],
    "documents": [],
    "sources": [],
}
with open("state/latest_discovery.json", "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False)
print("Wrote state/latest_discovery.json (empty fallback)")
PY
fi

python workers/process_document.py --from state/latest_discovery.json --config config_v2.yaml --limit 50
python workers/build_timeline.py --window 7d --config config_v2.yaml
python workers/build_daily_digest.py --hours 24
REPORT_ONLY=1 python main.py

if [ -f build_site_data.py ]; then
  python build_site_data.py || true
else
  python workers/build_site_data_v2.py
fi

if [ -f build_app_backend.py ]; then
  python build_app_backend.py
else
  python scripts/build_app_backend.py
fi

python scripts/validate_backend_outputs.py
python workers/publish_site_bridge.py
mkdir -p docs
touch docs/.nojekyll
