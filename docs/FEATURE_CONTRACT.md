# Feature Contract

## Tabular Baseline (Phase 1)
- **Input**: `listings_clean` columns: beds, baths, sqft, year_built, zip, hoa, etc.
- **Output**: `features/tabular.parquet` with:
  - normalized numeric cols
  - categorical encodings (one-hot / target mean)
  - train/valid/test splits with seed

## Image Features (Phase 2 preview)
- Per-mls_id curated subset → `features/images/<mls_id>/*.jpg`
- Manifest CSV mapping image → label (kitchen/bath/etc.) when available.
