# DB Schema (Draft)

## Option A: DuckDB (local analytics)
- Tables:
  - listings_raw
  - listings_clean
  - photos (path, mls_id, room_label?)
  - exports (batch_id, window_start, window_end, file_path)

## Option B: Postgres (shared)
- Same logical schema; add indexes for MLS id/date.

## Data Contracts
- Primary key: (mls_id, close_date) when available; else (mls_id, export_batch)
