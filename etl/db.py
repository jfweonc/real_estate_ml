from __future__ import annotations

import json
import os
from typing import Iterable, Tuple

import psycopg
from psycopg import Connection, Cursor
from psycopg.rows import dict_row

DSN_ENV = "DATABASE_URL"


def connect(
    dsn: str | None = None,
    *,
    row_factory = dict_row,
    autocommit: bool = False,
) -> Connection:
    """Create a psycopg3 connection using the configured DATABASE_URL."""
    target_dsn = dsn or os.environ.get(DSN_ENV)
    if not target_dsn:
        raise RuntimeError(f"{DSN_ENV} not set")
    return psycopg.connect(target_dsn, row_factory=row_factory, autocommit=autocommit)


def file_ingest_seen(cur: Cursor, file_hash: str) -> bool:
    cur.execute("SELECT 1 FROM etl.file_ingest_ledger WHERE file_hash=%s", (file_hash,))
    return cur.fetchone() is not None


def file_ingest_record(cur: Cursor, file_hash: str, raw_source: str) -> None:
    cur.execute(
        "INSERT INTO etl.file_ingest_ledger (file_hash, raw_source) VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (file_hash, raw_source),
    )


def quarantine_insert(
    cur: Cursor,
    raw_source: str,
    line_no: int | None,
    reason: str,
    details: dict | None,
) -> None:
    cur.execute(
        "INSERT INTO etl.quarantine (raw_source, line_no, reason, context) VALUES (%s,%s,%s,%s)",
        (raw_source, line_no, reason, json.dumps(details or {})),
    )


def conflict_insert(
    cur: Cursor,
    listing_key: str,
    domain: str,
    matrix_modified_dt: str,
    old_hash: str,
    new_hash: str,
    raw_source: str,
) -> None:
    cur.execute(
        """
        INSERT INTO etl.conflicts (listing_key, domain, matrix_modified_dt, old_hash, new_hash, raw_source)
        VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (listing_key, domain, matrix_modified_dt, old_hash, new_hash, raw_source),
    )


def refresh_listing_snapshot(cur: Cursor, touched_keys: Iterable[Tuple[str, str]]) -> None:
    unique = list({(listing_key, domain) for listing_key, domain in touched_keys})
    if not unique:
        return

    params: list[str] = []
    values_sql: list[str] = []
    for listing_key, domain in unique:
        params.extend([listing_key, domain])
        values_sql.append("(%s::text, %s::text)")

    values_clause = ", ".join(values_sql)
    cur.execute(
        f"""
        WITH keys(listing_key, domain) AS (VALUES {values_clause}),
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
        """,
        params,
    )


class Db:
    def __init__(self, conn: Connection):
        self.conn = conn

    @classmethod
    def from_env(cls) -> "Db":
        conn = connect(autocommit=True)
        return cls(conn)

    def quarantine(self, raw_source: str, reason: str, context: str | None = None, line_no: int | None = None) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                    INSERT INTO etl.quarantine(raw_source, line_no, reason, context)
                    VALUES (%s,%s,%s,%s)
                """,
                (raw_source, line_no, reason, context),
            )

    def get_listing_identity(self, listing_key: str):
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                    SELECT listing_key, domain, photo_count
                    FROM etl.listing
                    WHERE listing_key=%s
                """,
                (listing_key,),
            )
            return cur.fetchone()

    def get_photocount(self, listing_key: str) -> int | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT photo_count FROM etl.listing WHERE listing_key=%s", (listing_key,))
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else None

    def count_images(self, listing_key: str, domain: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                    SELECT COUNT(*) FROM etl.image
                    WHERE listing_key=%s AND domain=%s
                """,
                (listing_key, domain),
            )
            return int(cur.fetchone()[0])

    def insert_image(
        self,
        listing_key: str,
        domain: str,
        sha1: str,
        rel_path: str,
        source: str,
        filesize: int | None,
        width: int | None,
        height: int | None,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                    INSERT INTO etl.image (listing_key, domain, sha1, rel_path, source, filesize, width, height)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (listing_key, domain, sha1) DO NOTHING
                """,
                (listing_key, domain, sha1, rel_path, source, filesize, width, height),
            )

    def update_listing_checks(
        self,
        listing_key: str,
        domain: str,
        *,
        images_count: int,
        images_download_status: str,
        images_last_checked,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                    UPDATE etl.listing
                       SET images_count=%s,
                           images_download_status=%s,
                           images_last_checked=%s
                     WHERE listing_key=%s AND domain=%s
                """,
                (images_count, images_download_status, images_last_checked, listing_key, domain),
            )

    def get_listing_status_field(self, listing_key: str, domain: str) -> str | None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                    SELECT images_download_status
                    FROM etl.listing
                    WHERE listing_key=%s AND domain=%s
                """,
                (listing_key, domain),
            )
            row = cur.fetchone()
            return row[0] if row else None
