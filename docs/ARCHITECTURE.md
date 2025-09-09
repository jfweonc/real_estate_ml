# Architecture

## Goals (Phase 0–1)
- Deterministic, idempotent ETL from HAR Matrix via Playwright.
- Reproducible containerized runs.
- Clear config/env boundaries.

## Context Diagram
- **Browser Automation (Node/Playwright)** → downloads CSVs & images → **ETL Staging** (data/raw)
- **Python ETL** → clean/normalize → **Interim/Processed**
- **Feature Contracts** expose tables/files to modeling jobs.

## Runtime Views
- Container: Playwright browsers + Python runtime
- Volumes: ./data mounted at /app/data
- Secrets: .env

## Config Strategy
- Static: `config/settings.yaml`
- Secrets: `.env` (never committed)
- Runtime overrides via env vars
