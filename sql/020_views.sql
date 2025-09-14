-- 020_views.sql
-- Defines a reusable, read-only view of the "current" (latest) row per (listing_key, domain)
-- Source: etl.raw_listing_row
-- Rule: pick the row with the greatest MatrixModifiedDT (tie-breaker: CloseDate DESC)

CREATE OR REPLACE VIEW etl.current_listings_v AS
SELECT DISTINCT ON (r.listing_key, r.domain)
  r.listing_key,
  r.domain,
  r.status,
  r.list_date,
  r.close_date,
  r.matrix_modified_dt,
  r.list_price,
  r.close_price,
  r.photo_count,
  r.postal_code_zip5
FROM etl.raw_listing_row AS r
ORDER BY
  r.listing_key,
  r.domain,
  r.matrix_modified_dt DESC,
  COALESCE(r.close_date, DATE '0001-01-01') DESC;
