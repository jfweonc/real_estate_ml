import os
import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

# import the indexer as a module so we can call main()
# assumes repo layout where 'etl' is importable; adjust sys.path if needed
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root
from etl.index_images import main as index_images_main

from tests.conftest import insert_listing, get_quarantine, get_image_count, get_listing_checks
from tests.util_zip import png_bytes, make_zip

@pytest.mark.usefixtures("clean_db")
def test_bad_filename_goes_to_quarantine(tmp_path, db, monkeypatch):
    # Arrange: make a zip with an invalid filename
    z = make_zip(tmp_path/"badnames.zip", {
        "weirdname.jpg": png_bytes(),        # invalid (no listing_key_seq pattern)
        "12345678-notseq.png": png_bytes(),  # invalid pattern
    })

    # Act
    monkeypatch.setenv("DATABASE_URL", os.environ["DATABASE_URL"])
    sys.argv = ["etl/index_images.py", str(z), "--source", "manual", "--dry-run"]
    index_images_main()

    # Assert
    reasons = [r for r,_ in get_quarantine(db)]
    assert "unparseable_filename" in reasons
    # no image rows inserted
    assert get_image_count(db, "12345678", "SALE") == 0  # 0 even if guessed, since nothing valid

@pytest.mark.usefixtures("clean_db")
def test_duplicate_zip_noop(tmp_path, db, monkeypatch):
    # Arrange: a listing expecting 2 photos
    insert_listing(db, "L100", "SALE", photo_count=2)
    z = make_zip(tmp_path/"dup.zip", {
        "L100_01.jpg": png_bytes(),
        "L100_02.jpg": png_bytes(),
    })

    # First run
    monkeypatch.setenv("DATABASE_URL", os.environ["DATABASE_URL"])
    sys.argv = ["etl/index_images.py", str(z), "--source", "manual"]
    index_images_main()
    c1 = get_image_count(db, "L100", "SALE")

    # Second run (same zip)
    index_images_main()
    c2 = get_image_count(db, "L100", "SALE")

    assert c1 == 2 and c2 == 2  # no new rows
    images_count, status = get_listing_checks(db, "L100", "SALE")
    assert images_count == 2 and status == "complete"

@pytest.mark.usefixtures("clean_db")
def test_partial_to_complete(tmp_path, db, monkeypatch):
    # Arrange: listing expects 3 photos, first zip has 2
    insert_listing(db, "L200", "SALE", photo_count=3)
    z1 = make_zip(tmp_path/"p1.zip", {
        "L200_01.jpg": png_bytes(),
        "L200_02.jpg": png_bytes(),
    })
    z2 = make_zip(tmp_path/"p2.zip", {
        "L200_03.jpg": png_bytes(),
    })

    monkeypatch.setenv("DATABASE_URL", os.environ["DATABASE_URL"])

    # Run zip 1 → expect partial
    sys.argv = ["etl/index_images.py", str(z1), "--source", "manual"]
    index_images_main()
    images_count, status = get_listing_checks(db, "L200", "SALE")
    assert images_count == 2 and status == "partial"

    # Run zip 2 → expect complete (2+1 >= 3)
    sys.argv = ["etl/index_images.py", str(z2), "--source", "manual"]
    index_images_main()
    images_count, status = get_listing_checks(db, "L200", "SALE")
    assert images_count >= 3 and status == "complete"
