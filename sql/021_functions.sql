-- 021_functions.sql
-- Materializes the current snapshot into etl.listing (UPSERT).
-- Leaves image coverage fields as-is (images_count, images_last_checked, images_download_status).

CREATE OR REPLACE FUNCTION etl.refresh_listing_from_raw() RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  INSERT INTO etl.listing (
    listing_key,
    domain,
    status,
    list_date,
    close_date,
    matrix_modified_dt,
    list_price,
    close_price,
    photo_count,
    postal_code_zip5
  )
  SELECT
    v.listing_key,
    v.domain,
    v.status,
    v.list_date,
    v.close_date,
    v.matrix_modified_dt,
    v.list_price,
    v.close_price,
    v.photo_count,
    v.postal_code_zip5
  FROM etl.current_listings_v AS v
  ON CONFLICT (listing_key, domain)
  DO UPDATE SET
    status             = EXCLUDED.status,
    list_date          = EXCLUDED.list_date,
    close_date         = EXCLUDED.close_date,
    matrix_modified_dt = EXCLUDED.matrix_modified_dt,
    list_price         = EXCLUDED.list_price,
    close_price        = EXCLUDED.close_price,
    photo_count        = EXCLUDED.photo_count,
    postal_code_zip5   = EXCLUDED.postal_code_zip5,
    updated_at         = now()
  -- Only move forward or equal in time; prevents accidental regressions
  WHERE EXCLUDED.matrix_modified_dt >= etl.listing.matrix_modified_dt;

  -- Note: image coverage fields are intentionally NOT touched here.
  -- They are maintained by your image indexing/refresh modules.
END;
$$;
