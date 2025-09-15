#!/usr/bin/env python3
from __future__ import annotations
import csv, sys, re, unicodedata, hashlib, argparse, os
from datetime import datetime, timezone
import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from typing import List, Tuple
from pathlib import Path
import sys

# Ensure project src/ is importable, then import from the package
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from relml.config import load_settings  # and EnvSettings/Settings if you need them
# from relml.config import EnvSettings, Settings  # optional



# ---------- Settings ----------
S = load_settings().etl

REQUIRED = S.required_headers
HEADER_ALIASES = S.header_aliases or {}

CSV_ENCODING = S.csv.encoding
CSV_DELIMITER = S.csv.delimiter
CSV_QUOTECHAR = S.csv.quotechar
CSV_STRICT = S.csv.strict
DEFAULT_JOBS = S.concurrency if S.concurrency and S.concurrency > 0 else min(8, (os.cpu_count() or 4))

INVALID_ZIP5 = set((S.zip_normalization.invalid_zip5 or []))

# ---------- Helpers / Normalizers ----------
def norm_text(x, casefold=True):
    if x is None:
        return ""
    s = unicodedata.normalize("NFC", str(x)).strip()
    s = re.sub(r"\s+", " ", s)
    return s.casefold() if casefold else s

DATE_INPUT_FORMATS = ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y")
def norm_date(x):
    s = norm_text(x)
    if not s:
        return ""
    for fmt in DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()  # YYYY-MM-DD
        except ValueError:
            pass
    return ""

def norm_ts_utc(x):
    s = norm_text(x)
    if not s:
        return ""
    TS_INPUTS = (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
        "%m-%d-%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S",
    )
    for fmt in TS_INPUTS:
        try:
            dt = datetime.strptime(s, fmt)
            dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", s):
        return s
    return ""

def norm_num(x):
    s = norm_text(x, casefold=False).replace(",", "")
    if not s:
        return ""
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        return ""
    return str(float(s)).rstrip("0").rstrip(".") if "." in s else str(int(float(s)))

def norm_int(x):
    s = norm_num(x)
    return str(int(float(s))) if s else ""

def to_zip5(x):
    s = re.sub(r"\D+", "", norm_text(x, casefold=False))
    if len(s) >= 5:
        z = s[:5]
        return "" if z in INVALID_ZIP5 else z
    return ""

def to_domain(property_type):
    return "RENTAL" if norm_text(property_type) == "rental" else "SALE"

def apply_header_aliases(header: List[str]) -> List[str]:
    return [HEADER_ALIASES.get(h.strip(), h.strip()) for h in header]

def row_hash(record):
    parts = [
        norm_text(record.get("MLS #"), casefold=False),
        to_domain(record.get("PropertyType")),
        norm_text(record.get("Status")),
        norm_date(record.get("ListingContractDate")),   # updated name
        norm_date(record.get("CloseDate")),
        norm_ts_utc(record.get("MatrixModifiedDT")),
        norm_num(record.get("ListPrice")),
        norm_num(record.get("ClosePrice")),
        norm_int(record.get("PhotoCount")),
        to_zip5(record.get("PostalCode")),
    ]
    # Joiner: a literal pipe character
    JOINER = "|"
    canon = JOINER.join(parts)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest(), canon

# ---------- Core per-file check ----------
def check_one_csv(path: Path, encoding=CSV_ENCODING, delimiter=CSV_DELIMITER, quotechar=CSV_QUOTECHAR, strict=CSV_STRICT, sample_print=0, headers_only=False):
    stats = {"raw_source": str(path), "rows_total": 0, "rows_quarantined": 0, "file_reasons": set(), "status": "ok"}
    issues: List[Tuple[str,int,str,str]] = []

    try:
        # Some Python versions don't support strict=... in csv.reader; handle gracefully
        with path.open("r", encoding=encoding, newline="") as f:
            # Build the CSV reader (cross-version safe: some Python builds don't accept 'strict')
            try:
                reader = csv.reader(f, delimiter=delimiter, quotechar=quotechar, strict=strict)
            except TypeError:
                # Fallback for Python builds without the 'strict' parameter
                reader = csv.reader(f, delimiter=delimiter, quotechar=quotechar)

            try:
                header = next(reader)
            except Exception as e:
                issues.append((str(path), 1, "bad_quote", f"header_error={e}"))
                stats["status"] = "bad"
                stats["file_reasons"].add("bad_quote")
                return stats, issues

            header = apply_header_aliases(header)

            # Required header presence
            missing = [h for h in REQUIRED if h not in header]
            if missing:
                issues.append((str(path), 1, "missing_required_col", ";".join(missing)))
                stats["status"] = "bad"
                stats["file_reasons"].add("missing_required_col")
                return stats, issues

            if headers_only:
                return stats, issues

            idx = {name: i for i, name in enumerate(header)}
            line_no = 1
            printed = 0
            for row in reader:
                line_no += 1
                stats["rows_total"] += 1
                if len(row) != len(header):
                    issues.append((str(path), line_no, "column_mismatch", f"got={len(row)} expected={len(header)}"))
                    stats["rows_quarantined"] += 1
                    stats["file_reasons"].add("column_mismatch")
                    continue
                rec = {name: row[idx[name]] for name in header}
                if printed < sample_print:
                    h, canon = row_hash(rec)
                    print(f"[sample] {path.name}: line {line_no} hash={h[:12]} canon={canon}")
                    printed += 1

    except csv.Error as e:
        issues.append((str(path), 0, "bad_quote", f"csv_error={e}"))
        stats["status"] = "bad"
        stats["file_reasons"].add("bad_quote")
    except UnicodeDecodeError as e:
        issues.append((str(path), 0, "bad_quote", f"unicode_error={e}"))
        stats["status"] = "bad"
        stats["file_reasons"].add("bad_quote")
    except Exception as e:
        issues.append((str(path), 0, "bad_quote", f"unexpected_error={e}"))
        stats["status"] = "bad"
        stats["file_reasons"].add("bad_quote")

    return stats, issues

# ---------- Input expansion (Windows-friendly) ----------
def _has_glob_chars(s: str) -> bool:
    return any(ch in s for ch in ("*", "?", "["))

def expand_inputs(paths, recursive=False):
    out = []
    for raw in paths:
        s = str(raw)
        # globs first (avoid Path().is_dir() on wildcard strings on Windows)
        if _has_glob_chars(s):
            for q in Path().glob(s):
                if q.is_file():
                    out.append(q)
            continue
        p = Path(s)
        if p.is_dir():
            it = p.rglob("*.csv") if recursive else p.glob("*.csv")
            out.extend([q for q in it if q.is_file()])
            continue
        if p.is_file():
            out.append(p)
    # dedup + sort
    seen, deduped = set(), []
    for q in out:
        sp = str(q.resolve())
        if sp not in seen:
            seen.add(sp); deduped.append(q)
    deduped.sort()
    return deduped

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(description="CSV sanity pass (multi-file, config-driven)")
    ap.add_argument("inputs", nargs="+", help="Files, dirs, or globs (e.g., data/raw/*Data/*.csv)")
    ap.add_argument("--encoding", default=CSV_ENCODING)
    ap.add_argument("--delimiter", default=CSV_DELIMITER)
    ap.add_argument("--quotechar", default=CSV_QUOTECHAR)
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    ap.add_argument("--samples", type=int, default=0, help="print N sample row hashes per file")
    ap.add_argument("--report", default=None, help="quarantine CSV path (default uses timestamp)")
    ap.add_argument("--summary", default=None, help="summary CSV path (default uses timestamp)")
    ap.add_argument("--missing-headers", default=None, help="missing-headers CSV path (default uses timestamp)")
    ap.add_argument("--headers-only", action="store_true", help="only check headers; skip row parsing")
    ap.add_argument("--recursive", action="store_true", help="recurse when a directory is provided")
    args = ap.parse_args()

    all_paths = expand_inputs(args.inputs, recursive=args.recursive)
    if not all_paths:
        print("No CSVs found from provided inputs.", file=sys.stderr)
        sys.exit(2)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(args.report or f"data/reports/csv_sanity_quarantine_{ts}.csv")
    summary_path = Path(args.summary or f"data/reports/csv_sanity_summary_{ts}.csv")
    missing_summary_path = Path(args.missing_headers or f"data/reports/csv_missing_headers_{ts}.csv")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    rows_quarantined_total = 0
    per_file_stats = []
    issues_all = []
    missing_header_counter = Counter()

    print(f"Scanning {len(all_paths)} files with {args.jobs} workers…")
    def task(p):
        stats, issues = check_one_csv(
            p,
            encoding=args.encoding,
            delimiter=args.delimiter,
            quotechar=args.quotechar,
            strict=CSV_STRICT,
            sample_print=args.samples,
            headers_only=args.headers_only,
        )
        # accumulate missing header counts from file-level issues
        for _, _, reason, ctx in issues:
            if reason == "missing_required_col":
                for name in (ctx.split(";") if ctx else []):
                    if name:
                        missing_header_counter.update([name])
        return stats, issues

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(task, p): p for p in all_paths}
        for fut in as_completed(futs):
            stats, issues = fut.result()
            per_file_stats.append(stats)
            issues_all.extend(issues)

    # write quarantine (row + file issues)
    if issues_all:
        with report_path.open("w", encoding="utf-8", newline="") as out:
            w = csv.writer(out)
            w.writerow(["raw_source","line_no","reason","context"])
            w.writerows(issues_all)

    # write missing-headers summary
    if missing_header_counter:
        with missing_summary_path.open("w", encoding="utf-8", newline="") as out:
            w = csv.writer(out)
            w.writerow(["missing_header","files_missing_count"])
            for name, cnt in missing_header_counter.most_common():
                w.writerow([name, cnt])

    # write per-file summary
    files_bad = 0
    with summary_path.open("w", encoding="utf-8", newline="") as out:
        w = csv.writer(out)
        w.writerow(["raw_source","rows_total","rows_quarantined","file_reasons","status"])
        for st in per_file_stats:
            files_bad += 1 if st["status"] != "ok" or st["rows_quarantined"] > 0 else 0
            rows_quarantined_total += st["rows_quarantined"]
            reasons = ",".join(sorted(st["file_reasons"])) if st["file_reasons"] else ""
            w.writerow([st["raw_source"], st["rows_total"], st["rows_quarantined"], reasons, st["status"]])

    print(f"Done. Files: {len(all_paths)}, with issues: {files_bad}, quarantined rows: {rows_quarantined_total}")
    if issues_all:
        print(f"Quarantine report: {report_path}")
    if missing_header_counter:
        print(f"Missing-headers summary: {missing_summary_path}")
    print(f"Summary report:    {summary_path}")

    # exit non-zero if anything was quarantined or any file-level issue
    if files_bad or rows_quarantined_total:
        sys.exit(4)
    sys.exit(0)

if __name__ == "__main__":
    main()
