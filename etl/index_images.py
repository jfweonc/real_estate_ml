#!/usr/bin/env python3
import argparse, hashlib, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile, BadZipFile

from etl.media_utils import sha256_file, probe_image_size
from etl.db import Db

FNAME_RE = re.compile(r"^(?P<listing_key>[A-Za-z0-9]+)_(?P<seq>\d+)\.(?P<ext>jpg|jpeg|png)$", re.IGNORECASE)

def parse_args():
    ap = argparse.ArgumentParser("etl/index_images")
    ap.add_argument("zip_path", help="A ZIP file or a folder containing ZIPs")
    ap.add_argument("--source", choices=["manual", "automation"], required=True)
    ap.add_argument("--domain", choices=["SALE","RENTAL"], help="Override domain for the whole batch (only if missing in DB)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out-log", default="data/reports/image_index_log.csv")
    return ap.parse_args()

def iter_zip_files(root: Path):
    p = Path(root)
    if p.is_file() and p.suffix.lower() == ".zip":
        yield p
    elif p.is_dir():
        for z in sorted(p.rglob("*.zip")):
            yield z
    else:
        raise FileNotFoundError(f"Not a zip or directory: {root}")

def normalize_target(domain: str, listing_key: str, original_name: str) -> Path:
    return Path("data/raw")/domain/"images"/listing_key/original_name

def ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

def main():
    args = parse_args()
    db = Db.from_env()
    now = datetime.now(timezone.utc)

    # open log
    Path(args.out_log).parent.mkdir(parents=True, exist_ok=True)
    if not Path(args.out_log).exists():
        with open(args.out_log, "w", encoding="utf-8") as f:
            f.write("zip,listing_key,domain,added_images,images_count_after,images_status_after,notes\n")

    for zip_file in iter_zip_files(Path(args.zip_path)):
        added_by_listing = {}
        notes_by_listing = {}
        try:
            with ZipFile(zip_file, "r") as zf:
                members = [m for m in zf.infolist() if not m.is_dir()]
                for m in members:
                    fname = Path(m.filename).name  # ignore internal dirs
                    mname = fname.strip()
                    match = FNAME_RE.match(mname)
                    if not match:
                        db.quarantine(raw_source=str(zip_file), reason="unparseable_filename", context=mname)
                        continue

                    listing_key = match.group("listing_key")
                    # Resolve domain & photocount from DB
                    r = db.get_listing_identity(listing_key)
                    if not r:
                        # allow override domain if provided (fallback), else quarantine & skip
                        if args.domain:
                            domain = args.domain
                            photocount = None
                        else:
                            db.quarantine(raw_source=str(zip_file), reason="missing_listing_match", context=listing_key)
                            continue
                    else:
                        domain = r["domain"]
                        photocount = r["photo_count"]

                    # extract to temp bytes (avoid writing twice)
                    try:
                        with zf.open(m, "r") as src:
                            data = src.read()
                    except Exception as e:
                        db.quarantine(raw_source=str(zip_file), reason="bad_zip", context=f"{mname}: {e}")
                        continue

                    # compute sha256 and (optionally) image dimensions
                    sha = hashlib.sha256(data).hexdigest()
                    width, height = probe_image_size(data)

                    # target path
                    target = normalize_target(domain, listing_key, mname)
                    ensure_parent(target)

                    added = False
                    if not target.exists():
                        if not args.dry_run:
                            try:
                                with open(target, "wb") as out:
                                    out.write(data)
                                added = True
                            except OSError as e:
                                db.quarantine(raw_source=str(zip_file), reason="io_error", context=f"{target}: {e}")
                                continue

                    # insert metadata (idempotent via UNIQUE)
                    rel_path = str(target)
                    if not args.dry_run:
                        db.insert_image(listing_key=listing_key, domain=domain, sha1=sha,
                                        rel_path=rel_path, source=args.source,
                                        filesize=len(data), width=width, height=height)

                    # track counters
                    if added:
                        added_by_listing[(listing_key, domain)] = added_by_listing.get((listing_key, domain), 0) + 1

                # after processing this zip, recompute check fields for listings touched
                for (listing_key, domain), added_n in added_by_listing.items():
                    if not args.dry_run:
                        images_count = db.count_images(listing_key, domain)
                        status = "none"
                        if images_count == 0:
                            status = "none"
                        else:
                            # if we know expected photocount, use it. otherwise, treat >0 as partial/complete heuristic
                            expected = db.get_photocount(listing_key) or 0
                            if expected and images_count >= expected:
                                status = "complete"
                            elif expected == 0:
                                status = "complete"  # some MLS rows legitimately have 0
                            else:
                                status = "partial"

                            db.update_listing_checks(
                                listing_key, domain,
                                images_count=images_count,
                                images_download_status=status,
                                images_last_checked=now
                            )

                        notes_by_listing[(listing_key, domain)] = f"expected={db.get_photocount(listing_key) or 'NA'}"

                    # write per-listing log line
                    with open(args.out_log, "a", encoding="utf-8") as f:
                        images_count_after = db.count_images(listing_key, domain) if not args.dry_run else ""
                        status_after = db.get_listing_status_field(listing_key, domain) if not args.dry_run else ""
                        notes = notes_by_listing.get((listing_key, domain), "")
                        f.write(f"{zip_file},{listing_key},{domain},{added_n},{images_count_after},{status_after},{notes}\n")

        except BadZipFile as e:
            db.quarantine(raw_source=str(zip_file), reason="bad_zip", context=str(e))
            continue

    return 0

if __name__ == "__main__":
    sys.exit(main())
