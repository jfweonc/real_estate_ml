#!/usr/bin/env python3
"""
Module 1 - Import CSVs into staging, validate structure, project minimal clean slice,
and refresh `etl.listing` (current snapshot). All config comes from master settings.yaml:
  - paths.*  (raw_dir, reports_dir)
  - etl.csv.* (encoding, delimiter, quotechar, strict, sniffer_delimiters, normalize_smart_quotes)
  - etl.required_headers / etl.header_aliases
"""

from __future__ import annotations

# --- make /app/src importable even if PYTHONPATH isn't set (safe no-op if it is) ---
from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]  # /app
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import argparse
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from relml.config import load_settings  # your loader should return the merged master(+overlay) model
from etl.db import (
    connect,
    conflict_insert,
    file_ingest_record,
    file_ingest_seen,
    quarantine_insert,
    refresh_listing_snapshot,
)
from etl.media_utils import sha256_file
from etl.normalize import (
    DEFAULT_INVALID_ZIP5,
    canon_date,
    canon_dt_iso8601,
    canon_int,
    canon_money,
    normalize_zip5,
    to_domain,
)



# ----------------------
# Settings (master-only fields)
# ----------------------
SETTINGS = load_settings()

def _get(cfg, *path, default=None):
    """Safe nested getattr/lookup (works with pydantic models or dicts)."""
    cur = cfg
    for key in path:
        if cur is None:
            return default
        if hasattr(cur, key):
            cur = getattr(cur, key)
        elif isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return default
    return cur if cur is not None else default

RAW_ROOT      = Path(_get(SETTINGS, "paths", "raw_dir", default="data/raw"))
REPORTS_DIR   = Path(_get(SETTINGS, "paths", "reports_dir", default="data/reports"))
DATA_SUFFIX   = str(_get(SETTINGS, "etl", "data_subfolder_suffix", default="Data")).lower()

csv_cfg = _get(SETTINGS, "etl", "csv", default={}) or {}
ENCODING  = csv_cfg.get("encoding", "utf-8")
CSV_KW    = {
    "delimiter": csv_cfg.get("delimiter", ","),
    "quotechar": csv_cfg.get("quotechar", '"'),
    "strict":    bool(csv_cfg.get("strict", True)),
}
SNIFFER_DELIMS          = list(csv_cfg.get("sniffer_delimiters", [",", ";", "\t"]))
NORMALIZE_SMART_QUOTES  = bool(csv_cfg.get("normalize_smart_quotes", False))
INVALID_ZIP5            = set(_get(SETTINGS, "etl", "zip_normalization", "invalid_zip5", default=DEFAULT_INVALID_ZIP5))

REQUIRED_HEADERS = _get(SETTINGS, "etl", "required_headers", default=[]) or []
HEADER_ALIASES   = _get(SETTINGS, "etl", "header_aliases",   default={}) or {}

REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------
# Normalization helpers
# ----------------------
SMART_TO_ASCII = str.maketrans({
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
})
def sanitize_text(s: str) -> str:
    return s.translate(SMART_TO_ASCII) if NORMALIZE_SMART_QUOTES and isinstance(s, str) else s


def normalized_row_tuple(rec: Dict[str, str]) -> Tuple[str, ...]:
    listing_key = (rec.get("MLS #") or "").strip()
    domain      = to_domain(rec.get("PropertyType"))
    status      = (rec.get("Status") or "").strip()

    list_date   = canon_date(rec.get("ListingContractDate"))  # canonical
    close_date  = canon_date(rec.get("CloseDate"))
    mm_iso      = canon_dt_iso8601(rec.get("MatrixModifiedDT"))

    list_price  = canon_money(rec.get("ListPrice"))
    close_price = canon_money(rec.get("ClosePrice"))
    photo_count = canon_int(rec.get("PhotoCount"))
    zip5        = normalize_zip5(rec.get("PostalCode"), INVALID_ZIP5)

    return (
        listing_key,
        domain,
        status.lower(),
        list_date or "",
        close_date or "",
        mm_iso or "",
        list_price or "",
        close_price or "",
        photo_count or "",
        zip5 or "",
    )

def hash_row(rec: Dict[str, str]) -> str:
    return hashlib.sha256("|".join(normalized_row_tuple(rec)).encode("utf-8")).hexdigest()




# ----------------------
# Row persistence helpers
# ----------------------
def upsert_raw_listing_row(cur, rec: Dict[str, str], raw_source: str, file_hash: str):
    """Insert into raw_listing_row; log conflicts when the normalized hash changes."""
    listing_key = (rec.get("MLS #") or "").strip()
    domain = to_domain(rec.get("PropertyType"))
    status = (rec.get("Status") or "").strip()
    list_date = canon_date(rec.get("ListingContractDate"))
    close_date = canon_date(rec.get("CloseDate"))
    mm_iso = canon_dt_iso8601(rec.get("MatrixModifiedDT"))
    list_price = canon_money(rec.get("ListPrice"))
    close_price = canon_money(rec.get("ClosePrice"))
    photo_count = canon_int(rec.get("PhotoCount"))
    zip5 = normalize_zip5(rec.get("PostalCode"), INVALID_ZIP5)

    if not listing_key or not domain or not mm_iso:
        quarantine_insert(
            cur,
            raw_source,
            None,
            "missing_required_col",
            {"missing": ["MLS # or PropertyType or MatrixModifiedDT"], "listing_key": listing_key},
        )
        return False, None

    n_hash = hash_row(rec)
    record_json = json.dumps(rec, ensure_ascii=False)

    cur.execute(
        """
        INSERT INTO etl.raw_listing_row
          (listing_key, domain, matrix_modified_dt, status, list_date, close_date,
           list_price, close_price, photo_count, postal_code_zip5,
           normalized_row_hash, raw_source, file_hash, record_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (listing_key, domain, matrix_modified_dt) DO NOTHING
        """,
        (
            listing_key,
            domain,
            mm_iso,
            status,
            list_date,
            close_date,
            list_price,
            close_price,
            int(photo_count) if photo_count else None,
            zip5,
            n_hash,
            raw_source,
            file_hash,
            record_json,
        ),
    )

    if cur.rowcount == 1:
        return True, (listing_key, domain)

    cur.execute(
        """
        SELECT normalized_row_hash
        FROM etl.raw_listing_row
        WHERE listing_key=%s AND domain=%s AND matrix_modified_dt=%s
        """,
        (listing_key, domain, mm_iso),
    )
    row = cur.fetchone()
    if row and row["normalized_row_hash"] != n_hash:
        conflict_insert(cur, listing_key, domain, mm_iso, row["normalized_row_hash"], n_hash, raw_source)
    return False, None
# ----------------------
# CSV discovery (master paths)
# ----------------------
def discover_csv_files(raw_root: Path) -> List[Path]:
    files: List[Path] = []
    if raw_root.is_dir():
        files.extend(sorted(list(raw_root.glob("*.csv")) + list(raw_root.glob("*.CSV"))))
    for child in raw_root.iterdir() if raw_root.exists() and raw_root.is_dir() else []:
        if child.is_dir() and child.name.lower().endswith(DATA_SUFFIX):
            files.extend(sorted(child.rglob("*.csv")))
            files.extend(sorted(child.rglob("*.CSV")))
    return sorted({p.resolve() for p in files})

def iter_csv_rows(path: Path):
    """Open CSV robustly: try Sniffer with configured delimiters; fallback to CSV_KW; apply header aliases."""
    with path.open("r", encoding=ENCODING, newline="") as f:
        sample = f.read(64 * 1024)
        f.seek(0)
        try:
            sniffed = csv.Sniffer().sniff(sample, delimiters=SNIFFER_DELIMS)
            sniffed.strict = CSV_KW.get("strict", True)
            reader = csv.reader(f, sniffed)
            header = next(reader)
        except Exception:
            f.seek(0)
            reader = csv.reader(f, **CSV_KW)
            header = next(reader)

        header = [HEADER_ALIASES.get(h, h) for h in header]
        return header, reader

def validate_required_header(header: List[str]) -> Tuple[bool, List[str]]:
    missing = [h for h in REQUIRED_HEADERS if h not in header]
    return (len(missing) == 0), missing


# ----------------------
# Per-file processing
# ----------------------
def run_one_file(conn, path: Path, force: bool):
    raw_source = str(path)
    file_hash = sha256_file(path)

    with conn.cursor() as cur:
        if not force and file_ingest_seen(cur, file_hash):
            print(f"SKIP already ingested: {path.name}")
            return

        try:
            header, reader = iter_csv_rows(path)
        except Exception as e:
            quarantine_insert(cur, raw_source, None, "bad_quote", {"error": str(e)})
            conn.commit()
            print(f"QUARANTINE bad_quote: {path.name}")
            return

        ok, missing = validate_required_header(header)
        if not ok:
            quarantine_insert(cur, raw_source, 1, "missing_required_col", {"missing": missing})
            conn.commit()
            print(f"QUARANTINE missing_required_col: {path.name} -> {missing}")
            return

        header_idx = {h: i for i, h in enumerate(header)}
        touched: List[Tuple[str, str]] = []
        line_no = 1
        inserted_rows = 0

        for row in reader:
            line_no += 1
            if len(row) != len(header):
                quarantine_insert(cur, raw_source, line_no, "column_mismatch",
                                  {"expected": len(header), "got": len(row)})
                continue

            rec = {h: row[header_idx[h]] for h in header}
            if NORMALIZE_SMART_QUOTES:
                rec = {k: sanitize_text(v) for k, v in rec.items()}

            inserted, key = upsert_raw_listing_row(cur, rec, raw_source, file_hash)
            if inserted and key:
                touched.append(key)
                inserted_rows += 1

        if touched:
            refresh_listing_snapshot(cur, touched)

        file_ingest_record(cur, file_hash, raw_source)
        conn.commit()
        print(f"INGEST OK: {path.name} (inserted {inserted_rows} rows)")


# ----------------------
# CLI
# ----------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=str(RAW_ROOT), help="Root folder (default: settings.paths.raw_dir)")
    ap.add_argument("--force", action="store_true", help="Reprocess even if file_hash already seen")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: path not found: {root}", file=sys.stderr)
        raise SystemExit(1)

    files = discover_csv_files(root)
    if not files:
        print(f"No CSV files found under {root} (direct *.csv and */*{DATA_SUFFIX}/**/*.csv).", file=sys.stderr)
        raise SystemExit(1)

    print(f"Discovered {len(files)} CSV file(s). Showing up to 10 paths:")
    for p in files[:10]:
        print(f"  - {p}")

    with connect() as conn:
        for f in files:
            run_one_file(conn, f, force=args.force)

if __name__ == "__main__":
    main()
