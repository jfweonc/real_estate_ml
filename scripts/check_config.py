import os, sys, json, re
from datetime import datetime, timedelta, date
from pathlib import Path
try:
    import zoneinfo  # py3.9+
except ImportError:
    print("Python 3.9+ required for zoneinfo", file=sys.stderr); sys.exit(2)
try:
    import yaml
except Exception as e:
    print("pyyaml required: pip install pyyaml", file=sys.stderr); sys.exit(2)

OK = "✅"; FAIL = "❌"
errors = []

def err(msg): errors.append(msg); print(FAIL, msg)

def get(d, path, default=None):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur: return default
        cur = cur[k]
    return cur

# 1) Load YAML
cfg_path = os.getenv("SETTINGS_PATH", "settings.yaml")
try:
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    print(OK, f"Loaded {cfg_path}")
except Exception as e:
    err(f"Cannot parse {cfg_path}: {e}")
    sys.exit(1)

# 2) Phase 0.5 block exists
p05 = cfg.get("phase05")
if not isinstance(p05, dict):
    err("Missing top-level 'phase05' block"); sys.exit(1)
else:
    print(OK, "Found phase05 block")

# 3) Timezone + date window
tzname = os.getenv("APP_TIMEZONE") or get(p05, "project.timezone")
try:
    tz = zoneinfo.ZoneInfo(tzname)
    print(OK, f"Timezone ok: {tzname}")
except Exception:
    err(f"Invalid timezone: {tzname}")

dw_from = get(p05, "coverage.date_window.from")
dw_to   = get(p05, "coverage.date_window.to")
def resolve(token):
    if token == "!today":  return datetime.now(tz).date()
    if token == "!yesterday": return (datetime.now(tz) - timedelta(days=1)).date()
    return date.fromisoformat(token)
try:
    dfrom = resolve(dw_from); dto = resolve(dw_to)
    if dto < dfrom: err(f"date_window invalid: to({dto}) < from({dfrom})")
    else: print(OK, f"date_window ok: {dfrom} → {dto}")
except Exception as e:
    err(f"date_window parse error: {e}")

allowed = set(get(p05, "coverage.date_window.allowed_date_fields", []))
df_def  = get(p05, "coverage.date_window.date_field_default")
if df_def not in allowed:
    err(f"date_field_default '{df_def}' not in allowed {sorted(allowed)}")
else:
    print(OK, f"date_field_default ok: {df_def}")

# 4) Reason codes
reasons = get(p05, "images.policy.reasons", [])
expected_reasons = ["no_images","partial","active_changed","late_active_change"]
if reasons != expected_reasons:
    err(f"images.policy.reasons must be exactly {expected_reasons}, got {reasons}")
else:
    print(OK, "Reason codes ok")

# 5) Required columns (must include PostalCode)
req_cols = get(p05, "csv_ingest.required_columns", [])
if "PostalCode" not in req_cols:
    err("csv_ingest.required_columns missing 'PostalCode'")
else:
    print(OK, "Required columns include PostalCode")

# 6) ZIP5 normalization flags
if not get(p05, "postal_code.normalize_to_zip5", False):
    err("postal_code.normalize_to_zip5 should be true")
else:
    print(OK, "ZIP5 normalization enabled")

# 7) Active statuses non-empty
active_statuses = get(p05, "images.policy.active_statuses", [])
if not active_statuses:
    err("images.policy.active_statuses is empty")
else:
    print(OK, f"Active statuses ok: {len(active_statuses)} entries")

# 8) Paths parity (only if phase05.project.paths exists)
base_raw = get(cfg, "paths.raw_dir")
p05_raw  = get(p05, "project.paths.raw", base_raw)
if base_raw and p05_raw and (p05_raw != base_raw):
    err(f"Path drift: phase05.project.paths.raw={p05_raw} != paths.raw_dir={base_raw}")
else:
    print(OK, "Path parity ok (or single source of truth)")

# 9) Directories exist & writable
candidates = [get(cfg, "paths.raw_dir"), get(cfg, "paths.interim_dir"), get(cfg, "paths.reports_dir")]
for p in filter(None, candidates):
    path = Path(p)
    if not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True)
            print(OK, f"Created missing dir: {p}")
        except Exception as e:
            err(f"Cannot create dir {p}: {e}")
    elif not os.access(p, os.W_OK):
        err(f"Dir not writable: {p}")
    else:
        print(OK, f"Dir ok: {p}")

# 10) DATABASE_URL present? (warn only)
db_url = os.getenv("DATABASE_URL")
if db_url:
    print(OK, "DATABASE_URL present in environment")
else:
    print("ℹ️  DATABASE_URL not set (ok if you’re not running DB-backed tests)")

# Exit
if errors:
    print("\n---- SUMMARY ----")
    for e in errors: print(FAIL, e)
    sys.exit(1)
else:
    print("\nAll config checks passed.")
