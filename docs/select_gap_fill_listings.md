# recon/select_gap_fill_listings — Spec (Phase 0.5)

## Reasons
no_images, partial, late_active_change

## Filters (today)
- ZIP: --zip all or --zip 77479 ... (ZIP5)
- Date: --date-field {MatrixModifiedDT|ListDate|CloseDate} --from --to

## Future
--filter / --filter-spec for City, Beds, Price, etc.

## Output
data/interim/selected_listings.parquet (echo filter fields for audit)
