-- no need for SET search_path if you fully qualify

CREATE TABLE IF NOT EXISTS etl.raw_listing_row (
  listing_key          TEXT        NOT NULL,
  domain               TEXT        NOT NULL CHECK (domain IN ('SALE','RENTAL')),
  matrix_modified_dt   TIMESTAMPTZ NOT NULL,
  status               TEXT,
  list_date            DATE,
  close_date           DATE,
  list_price           NUMERIC(14,2),
  close_price          NUMERIC(14,2),
  photo_count          INTEGER CHECK (photo_count IS NULL OR photo_count >= 0),
  postal_code_zip5     CHAR(5) CHECK (postal_code_zip5 ~ '^\d{5}$'),
  normalized_row_hash  TEXT        NOT NULL,
  raw_source           TEXT        NOT NULL,
  file_hash            TEXT        NOT NULL,
  ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  record_json          JSONB       NOT NULL,
  CONSTRAINT raw_listing_row_pk PRIMARY KEY (listing_key, domain, matrix_modified_dt)
);

CREATE INDEX IF NOT EXISTS idx_rlr_modified ON etl.raw_listing_row (matrix_modified_dt);
CREATE INDEX IF NOT EXISTS idx_rlr_status   ON etl.raw_listing_row (status);
CREATE INDEX IF NOT EXISTS idx_rlr_zip5     ON etl.raw_listing_row (postal_code_zip5);

CREATE TABLE IF NOT EXISTS etl.listing (
  listing_key              TEXT        NOT NULL,
  domain                   TEXT        NOT NULL CHECK (domain IN ('SALE','RENTAL')),
  status                   TEXT,
  list_date                DATE,
  close_date               DATE,
  matrix_modified_dt       TIMESTAMPTZ NOT NULL,
  list_price               NUMERIC(14,2),
  close_price              NUMERIC(14,2),
  photo_count              INTEGER CHECK (photo_count IS NULL OR photo_count >= 0),
  postal_code_zip5         CHAR(5) CHECK (postal_code_zip5 ~ '^\d{5}$'),

  images_count             INTEGER     NOT NULL DEFAULT 0,
  images_last_checked      TIMESTAMPTZ,
  images_download_status   etl.image_download_status NOT NULL DEFAULT 'none',

  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT listing_pk PRIMARY KEY (listing_key, domain)
);

CREATE INDEX IF NOT EXISTS idx_listing_status   ON etl.listing (status);
CREATE INDEX IF NOT EXISTS idx_listing_zip5     ON etl.listing (postal_code_zip5);
CREATE INDEX IF NOT EXISTS idx_listing_modified ON etl.listing (matrix_modified_dt);

CREATE TABLE IF NOT EXISTS etl.image (
  listing_key    TEXT        NOT NULL,
  domain         TEXT        NOT NULL CHECK (domain IN ('SALE','RENTAL')),
  sha1           CHAR(40)    NOT NULL,
  rel_path       TEXT        NOT NULL,
  source         TEXT        NOT NULL CHECK (source IN ('manual','automation')),
  filesize       BIGINT,
  width          INTEGER,
  height         INTEGER,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT image_unique UNIQUE (listing_key, domain, sha1)
);
CREATE INDEX IF NOT EXISTS idx_image_key   ON etl.image (listing_key, domain);
CREATE INDEX IF NOT EXISTS idx_image_sha1  ON etl.image (sha1);

CREATE TABLE IF NOT EXISTS etl.file_ingest_ledger (
  file_hash   TEXT PRIMARY KEY,
  raw_source  TEXT NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS etl.conflicts (
  id                    BIGSERIAL PRIMARY KEY,
  listing_key           TEXT NOT NULL,
  domain                TEXT NOT NULL CHECK (domain IN ('SALE','RENTAL')),
  matrix_modified_dt    TIMESTAMPTZ NOT NULL,
  old_hash              TEXT NOT NULL,
  new_hash              TEXT NOT NULL,
  raw_source            TEXT NOT NULL,
  noted_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS etl.quarantine (
  id          BIGSERIAL PRIMARY KEY,
  raw_source  TEXT NOT NULL,
  line_no     INTEGER,
  reason      TEXT NOT NULL CHECK (reason IN ('bad_quote','column_mismatch','missing_required_col','other')),
  context     TEXT,
  noted_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
