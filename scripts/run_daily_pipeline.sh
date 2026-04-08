#!/usr/bin/env bash
set -euo pipefail

DISCOVERY_WINDOW="${DISCOVERY_WINDOW:-1d}"
DOC_LIMIT="${DOC_LIMIT:-50}"
RUN_REPORT_ONLY="${RUN_REPORT_ONLY:-1}"

if [ -f sources_v2.yaml ]; then
  python workers/weekly_discover.py --window "${DISCOVERY_WINDOW}" --sources sources_v2.yaml --config config_v2.yaml || true
else
  python workers/weekly_discover.py --window "${DISCOVERY_WINDOW}" --config config_v2.yaml || true
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

python workers/process_document.py --from state/latest_discovery.json --config config_v2.yaml --limit "${DOC_LIMIT}"
python workers/build_timeline.py --window 7d --config config_v2.yaml
python workers/build_daily_digest.py --hours 24

if [ "${RUN_REPORT_ONLY}" = "1" ]; then
  REPORT_ONLY=1 python main.py
else
  echo "Skipping rich daily report for lighter midday refresh"
fi

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
