# etl/import_csv — Spec (Phase 0.5)

## Purpose
Stage all CSV rows; validate structure; project a minimal clean slice; update `listing` (current).

## Inputs
HAR CSV exports (SALE & RENTAL).

## Required columns (minimal clean slice)
MLS # (listing_key), PropertyType→domain, Status, ListDate, CloseDate,
MatrixModifiedDT, ListPrice, ClosePrice, PhotoCount, PostalCode→ZIP5.

## Rules
- Identity: (listing_key="MLS #", domain={SALE|RENTAL})
- Row key: (listing_key, domain, MatrixModifiedDT)
- Row hash: normalized_row_hash (trim/normalize formats)

## Outputs
- raw rows → `raw_listing_row`
- update `listing` to latest per key (max MatrixModifiedDT)
- reports: `data/reports/quarantine_rows.csv`, `data/reports/conflicts.csv`

## Quarantine reasons
- bad_quote, column_mismatch, missing_required_col

## Idempotence
- Duplicate file_hash skipped
- Same (key+hash) skipped; key collision with different hash → conflicts
