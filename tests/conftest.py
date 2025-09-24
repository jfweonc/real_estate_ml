import os
import psycopg
import pytest
from datetime import datetime, timezone

@pytest.fixture(scope="session")
def db():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("Set DATABASE_URL for tests")
    conn = psycopg.connect(dsn, autocommit=True)
    yield conn
    conn.close()

@pytest.fixture
def clean_db(db):
    with db.cursor() as cur:
        # wipe test data for deterministic runs
        cur.execute("delete from etl.image;")
        cur.execute("delete from etl.quarantine;")
        cur.execute("delete from etl.listing;")
    yield
    # no teardown needed

def insert_listing(db, listing_key, domain, photo_count, status="Active"):
    now = datetime.now(timezone.utc)
    with db.cursor() as cur:
        cur.execute("""
            insert into etl.listing(listing_key, domain, status, matrix_modified_dt, list_date, photo_count,
                                    images_count, images_download_status, images_last_checked, postal_code_zip5)
            values (%s,%s,%s,%s::timestamptz, %s::date, %s, 0, 'none', NULL, '77479')
            on conflict (listing_key, domain) do update set
              status=excluded.status,
              matrix_modified_dt=excluded.matrix_modified_dt,
              list_date=excluded.list_date,
              photo_count=excluded.photo_count;
        """, (listing_key, domain, status, now.isoformat(), now.date(), photo_count))

def get_quarantine(db):
    with db.cursor() as cur:
        cur.execute("select reason, context from etl.quarantine order by id asc;")
        return cur.fetchall()

def get_image_count(db, listing_key, domain):
    with db.cursor() as cur:
        cur.execute("select count(*) from etl.image where listing_key=%s and domain=%s;",
                    (listing_key, domain))
        return cur.fetchone()[0]

def get_listing_checks(db, listing_key, domain):
    with db.cursor() as cur:
        cur.execute("""select images_count, images_download_status
                         from etl.listing where listing_key=%s and domain=%s;""",
                    (listing_key, domain))
        return cur.fetchone()
