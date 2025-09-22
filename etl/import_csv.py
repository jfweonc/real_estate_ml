#!/usr/bin/env python3
# etl/import_csv.py
"""
Module 1 — Import CSVs to staging, validate structure, project minimal clean slice, and refresh `listing`.
Idempotent by (MLS #, domain, MatrixModifiedDT) + normalized_row_hash.

File discovery (UPDATED):
- Given a root like `data/raw`, discover CSVs in:
  1) any immediate files under `data/raw` matching *.csv / *.CSV
  2) any subfolder whose name ends with "Data" (case-insensitive), e.g. ".../SomethingData"
     - include all *.csv / *.CSV files anywhere under those "Data" folders (recursive)

Usage:
  python etl/import_csv.py data/raw
  python etl/import_csv.py path/to/another/root  # optional

Inside Docker:
  docker compose exec -e DATABASE_URL=postgresql://app:app@db:5432/real_estate_ml app \
    python etl/import_csv.py data/raw
"""

from __future__ import annotations
from relml.config import load_settings
import argparse, csv, hashlib, io, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Iterable

import psycopg  # psycopg>=3.2
from psycopg.rows import dict_row


# ----------------------
# Settings / constants
# ----------------------
# load from settings once
SETTINGS = load_settings()
REQUIRED_HEADERS = SETTINGS.etl.required_headers
HEADER_ALIASES   = SETTINGS.etl.header_aliases or {}

# Sensible fallbacks in case a key is missing
CSV_SETTINGS = SETTINGS.etl.csv

# Encoding, reports dir, and csv knobs from settings with defaults
ENCODING = CSV_SETTINGS.encoding or "utf-8"
REPORTS_DIR = Path((getattr(SETTINGS, "etl", None) or {}).__dict__.get("reports_dir", "data/reports"))

CSV_KW = {
    "delimiter": CSV_SETTINGS.delimiter or ",",
    "quotechar": CSV_SETTINGS.quotechar or '"',
    "strict": CSV_SETTINGS.strict if CSV_SETTINGS.strict is not None else True,
}
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# New: invalid ZIPs list
INVALID_ZIP5 = set(SETTINGS.etl.zip_normalization.invalid_zip5 or ["00000"])

# Optional: only present if you add it to settings; None disables sniffing
raw_sniffer = getattr(CSV_SETTINGS, "sniffer_delimiters", None)
if raw_sniffer:
    if isinstance(raw_sniffer, (list, tuple)):
        SNIFFER_DELIMS = "".join(raw_sniffer)
    elif isinstance(raw_sniffer, str):
        SNIFFER_DELIMS = raw_sniffer
    else:
        SNIFFER_DELIMS = None
else:
    SNIFFER_DELIMS = None


# ----------------------
# Utility: ZIP5 normalization
# ----------------------
def normalize_zip5(postal_code: str | None) -> str | None:
    if not postal_code:
        return None
    digits = "".join(ch for ch in postal_code if ch.isdigit())
    if len(digits) >= 5:
        z = digits[:5]
        return None if z in INVALID_ZIP5 else z
    return None


# ----------------------
# Utility: domain mapping
# ----------------------
def to_domain(property_type: str | None) -> str:
    if (property_type or "").strip().lower() == "rental":
        return "RENTAL"
    return "SALE"


# ----------------------
# Utility: canonicalize + hash
# ----------------------
def canon_dt_iso8601(dt_str: str | None) -> str | None:
    if not dt_str:
        return None
    try:
        # Accept ISO with/without Z
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        # Fallback common pattern
        try:
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canon_date(d: str | None) -> str | None:
    if not d:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(d, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


def canon_money(x: str | None) -> str | None:
    if x is None or str(x).strip() == "":
        return None
    s = str(x).strip().replace(",", "")
    if s.startswith("$"):
        s = s[1:]
    try:
        return f"{float(s):.2f}"
    except Exception:
        return None


def canon_int(x: str | None) -> str | None:
    if x is None or str(x).strip() == "":
        return None
    s = "".join(ch for ch in str(x) if ch.isdigit())
    return s if s else None


def normalized_row_tuple(rec: Dict[str, str]) -> Tuple[str, ...]:
    listing_key = (rec.get("MLS #") or "").strip()
    domain      = to_domain(rec.get("PropertyType"))
    status      = (rec.get("Status") or "").strip()

    # use the canonical name ONLY
    list_date  = canon_date(rec.get("ListingContractDate"))  # <— here
    close_date = canon_date(rec.get("CloseDate"))
    mm_iso      = canon_dt_iso8601(rec.get("MatrixModifiedDT"))

    list_price  = canon_money(rec.get("ListPrice"))
    close_price = canon_money(rec.get("ClosePrice"))
    photo_count = canon_int(rec.get("PhotoCount"))
    zip5        = normalize_zip5(rec.get("PostalCode"))

    return (
        listing_key, domain, status.lower(),
        list_date or "", close_date or "", mm_iso or "",
        list_price or "", close_price or "", photo_count or "", zip5 or "",
    )


def hash_row(rec: Dict[str, str]) -> str:
    joined = "|".join(normalized_row_tuple(rec))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# ----------------------
# DB helpers
# ----------------------
def connect() -> psycopg.Connection:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(2)
    return psycopg.connect(dsn, row_factory=dict_row)


def file_already_ingested(cur, file_hash: str) -> bool:
    cur.execute("SELECT 1 FROM etl.file_ingest_ledger WHERE file_hash=%s", (file_hash,))
    return cur.fetchone() is not None


def ledger_insert(cur, file_hash: str, raw_source: str):
    cur.execute(
        "INSERT INTO etl.file_ingest_ledger (file_hash, raw_source) VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (file_hash, raw_source),
    )


def insert_quarantine(cur, raw_source: str, line_no: int | None, reason: str, details: dict):
    cur.execute(
        "INSERT INTO etl.quarantine (raw_source, line_no, reason, context) VALUES (%s,%s,%s,%s)",
        (raw_source, line_no, reason, json.dumps(details)),
    )


def insert_conflict(cur, listing_key: str, domain: str, mm: str, old_hash: str, new_hash: str, raw_source: str):
    cur.execute(
        """
        INSERT INTO etl.conflicts (listing_key, domain, matrix_modified_dt, old_hash, new_hash, raw_source)
        VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (listing_key, domain, mm, old_hash, new_hash, raw_source),
    )


def upsert_raw_listing_row(cur, rec: Dict[str, str], raw_source: str, file_hash: str):
    """
    Insert into etl.raw_listing_row with uniqueness on (listing_key, domain, matrix_modified_dt).
    If key exists but hash differs, do not overwrite; emit conflict.
    """
    listing_key = (rec.get("MLS #") or "").strip()
    domain = to_domain(rec.get("PropertyType"))
    status = (rec.get("Status") or "").strip()
    list_date = canon_date(rec.get("ListDate") or rec.get("ListingDate"))
    close_date = canon_date(rec.get("CloseDate"))
    mm_iso = canon_dt_iso8601(rec.get("MatrixModifiedDT"))
    list_price = canon_money(rec.get("ListPrice"))
    close_price = canon_money(rec.get("ClosePrice"))
    photo_count = canon_int(rec.get("PhotoCount"))
    zip5 = normalize_zip5(rec.get("PostalCode"))

    if not listing_key or not domain or not mm_iso:
        insert_quarantine(
            cur,
            raw_source,
            None,
            "missing_required_col",
            {"missing": ["MLS # or PropertyType or MatrixModifiedDT"], "listing_key": listing_key},
        )
        return False, None

    n_hash = hash_row(rec)
    record_json = json.dumps(rec, ensure_ascii=False)

    # Try insert
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
            listing_key, domain, mm_iso, status, list_date, close_date,
            list_price, close_price, int(photo_count) if photo_count else None, zip5,
            n_hash, raw_source, file_hash, record_json
        )
    )

    if cur.rowcount == 1:
        return True, (listing_key, domain)

    # Key exists: compare hash
    cur.execute(
        """
        SELECT normalized_row_hash
        FROM etl.raw_listing_row
        WHERE listing_key=%s AND domain=%s AND matrix_modified_dt=%s
        """,
        (listing_key, domain, mm_iso)
    )
    row = cur.fetchone()
    if row and row["normalized_row_hash"] != n_hash:
        insert_conflict(cur, listing_key, domain, mm_iso, row["normalized_row_hash"], n_hash, raw_source)
    return False, None


def refresh_listing_snapshot(cur, touched_keys: List[Tuple[str, str]]):
    if not touched_keys:
        return
    seen = {(k, d) for k, d in touched_keys}
    params: List[str] = []
    values_sql: List[str] = []
    for k, d in seen:
        params.extend([k, d])
        values_sql.append("(%s::text, %s::text)")
    vsql = ", ".join(values_sql)

    cur.execute(f"""
    WITH keys(listing_key, domain) AS (VALUES {vsql}),
    latest AS (
      SELECT DISTINCT ON (r.listing_key, r.domain)
             r.listing_key, r.domain, r.status, r.list_date, r.close_date,
             r.matrix_modified_dt, r.list_price, r.close_price, r.photo_count, r.postal_code_zip5
      FROM etl.raw_listing_row r
      JOIN keys k USING (listing_key, domain)
      ORDER BY r.listing_key, r.domain, r.matrix_modified_dt DESC
    )
    INSERT INTO etl.listing AS l
      (listing_key, domain, status, list_date, close_date, matrix_modified_dt,
       list_price, close_price, photo_count, postal_code_zip5, updated_at)
    SELECT listing_key, domain, status, list_date, close_date, matrix_modified_dt,
           list_price, close_price, photo_count, postal_code_zip5, now()
    FROM latest
    ON CONFLICT (listing_key, domain) DO UPDATE
      SET status=EXCLUDED.status,
          list_date=EXCLUDED.list_date,
          close_date=EXCLUDED.close_date,
          matrix_modified_dt=EXCLUDED.matrix_modified_dt,
          list_price=EXCLUDED.list_price,
          close_price=EXCLUDED.close_price,
          photo_count=EXCLUDED.photo_count,
          postal_code_zip5=EXCLUDED.postal_code_zip5,
          updated_at=now();
    """, params)


# ----------------------
# CSV discovery (UPDATED)
# ----------------------
def discover_csv_files(raw_root: Path) -> List[Path]:
    """
    Discover CSV files under `raw_root` with the following rules:
    - Include any *.csv / *.CSV directly under raw_root
    - Include any *.csv / *.CSV **recursively** under subfolders whose name ends with 'Data' (case-insensitive)
    """
    files: List[Path] = []

    # 1) any CSV directly under raw_root
    if raw_root.is_dir():
        files.extend(sorted(list(raw_root.glob("*.csv")) + list(raw_root.glob("*.CSV"))))

    # 2) any CSV below a folder that ends with 'Data' (case-insensitive)
    # Walk one level to find candidate subfolders, then recurse within them
    for child in raw_root.iterdir() if raw_root.exists() and raw_root.is_dir() else []:
        if child.is_dir() and child.name.lower().endswith("data"):
            files.extend(sorted(child.rglob("*.csv")))
            files.extend(sorted(child.rglob("*.CSV")))

    # De-dup and return (preserve deterministic ordering)
    uniq = sorted({f.resolve() for f in files})
    return uniq


# ----------------------
# CSV ingest driver
# ----------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_csv_rows(path: Path):
    csv_file = path.open("r", encoding=ENCODING, newline="")
    try:
        if SNIFFER_DELIMS:
            sample = csv_file.read(64 * 1024)
            csv_file.seek(0)
            try:
                sniffed = csv.Sniffer().sniff(sample, delimiters=SNIFFER_DELIMS)
                sniffed.strict = CSV_KW.get("strict", True)
                reader = csv.reader(csv_file, sniffed)
                header = next(reader)
            except Exception:
                csv_file.seek(0)
                reader = csv.reader(csv_file, **CSV_KW)
                header = next(reader)
        else:
            reader = csv.reader(csv_file, **CSV_KW)
            header = next(reader)

        header = [HEADER_ALIASES.get(h, h) for h in header]
        return header, reader, csv_file
    except Exception:
        csv_file.close()
        raise


def validate_required_header(header: List[str]) -> Tuple[bool, List[str]]:
    missing = [h for h in REQUIRED_HEADERS if h not in header]
    return (len(missing) == 0), missing


def run_one_file(conn, path: Path, force: bool):
    raw_source = str(path)
    file_hash = sha256_file(path)

    with conn.cursor() as cur:
        if not force and file_already_ingested(cur, file_hash):
            print(f"SKIP already ingested: {path.name}")
            return

        try:
            header, reader, csv_file = iter_csv_rows(path)
        except Exception as e:
            insert_quarantine(cur, raw_source, None, "bad_quote", {"error": str(e)})
            conn.commit()
            print(f"QUARANTINE bad_quote: {path.name}")
            return

        try:
            ok, missing = validate_required_header(header)
            if not ok:
                insert_quarantine(cur, raw_source, 1, "missing_required_col", {"missing": missing})
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
                    insert_quarantine(cur, raw_source, line_no, "column_mismatch",
                                      {"expected": len(header), "got": len(row)})
                    continue

                rec = {h: row[header_idx[h]] for h in header}
                inserted, key = upsert_raw_listing_row(cur, rec, raw_source, file_hash)
                if inserted and key:
                    touched.append(key)
                    inserted_rows += 1
        finally:
            csv_file.close()

        if touched:
            refresh_listing_snapshot(cur, touched)

        # File ledger
        ledger_insert(cur, file_hash, raw_source)
        conn.commit()
        print(f"INGEST OK: {path.name} (inserted {inserted_rows} rows)")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw_root", nargs="?", default="data/raw", help="Root folder containing CSVs (default: data/raw)")
    ap.add_argument("--force", action="store_true", help="Reprocess even if file_hash already seen")
    args = ap.parse_args()

    raw_root = Path(args.raw_root)
    if not raw_root.exists():
        print(f"ERROR: path not found: {raw_root}", file=sys.stderr)
        sys.exit(1)

    files = discover_csv_files(raw_root)
    if not files:
        print(f"No CSV files found under {raw_root} (looked in direct files and *Data/ subfolders).", file=sys.stderr)
        sys.exit(1)

    print(f"Discovered {len(files)} CSV file(s).")
    # Optional: print first few for sanity
    for p in files[:10]:
        print(f"  - {p}")

    with connect() as conn:
        for f in files:
            run_one_file(conn, f, force=args.force)


if __name__ == "__main__":
    main()
