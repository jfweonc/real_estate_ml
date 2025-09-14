-- Create your working schema
CREATE SCHEMA IF NOT EXISTS etl;

-- Create enum in *etl* (schema-qualified)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'image_download_status' AND n.nspname = 'etl'
  ) THEN
    CREATE TYPE etl.image_download_status AS ENUM ('none','partial','complete');
  END IF;
END $$;