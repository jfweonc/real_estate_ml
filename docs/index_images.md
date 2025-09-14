# etl/index_images — Spec (Phase 0.5)

## Purpose
Unzip batches; normalize to per-listing folders; compute image check fields.

## Normalize layout
data/raw/{SALE|RENTAL}/images/{listing_key}/<original>.jpg
(parse {listingNumber}_{imageNumber}.jpg)

## Check fields (stored on `listing`)
images_count, images_last_checked, images_download_status ∈ {none, partial, complete}

## Image metadata (`image` table)
UNIQUE (listing_key, domain, sha1); store rel_path, source {manual|automation}, dims, size
