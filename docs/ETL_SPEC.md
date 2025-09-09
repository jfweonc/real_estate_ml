# ETL Spec

## Inputs
- Saved search URLs (Matrix), login form creds from `.env`.
- Date ranges to export (Phase 1).

## Steps (Phase 1 preview)
1. Login (persist `artifacts/storage-state.json`).
2. Navigate to saved search.
3. Trigger exports by date window (idempotent naming).
4. Save CSVs under `data/raw/<entity>/<YYYYMMDD>/...`
5. Download listing images for chosen listings under `data/raw/images/<mls_id>/...`

## Idempotence
- Filename scheme includes MLS id + date window.
- Skip if exact file exists (size+hash match).

## Errors & Retries
- Retries with backoff: `limits.max_retries`.
- Non-200s → logged to `data/logs/etl.log`.
