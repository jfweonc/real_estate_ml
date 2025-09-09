#!/usr/bin/env bash
set -euo pipefail

REBUILD="${REBUILD:-0}"   # or pass --rebuild

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild) REBUILD=1; shift ;;
    *) echo "Unknown arg: $1"; exit 2 ;;
  esac
done

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

echo "[bootstrap] repo: $root_dir"

# 1) .env
if [[ ! -f .env ]]; then
  echo "[bootstrap] creating .env from config/env.example"
  cp config/env.example .env
else
  echo "[bootstrap] .env already present"
fi

# 2) data dirs
echo "[bootstrap] ensuring data directories"
mkdir -p data/raw data/interim data/processed data/logs

# 3) (optional) rebuild
if [[ "$REBUILD" == "1" ]]; then
  echo "[bootstrap] rebuilding Docker image"
  docker compose build
else
  echo "[bootstrap] skip rebuild (pass --rebuild or REBUILD=1 to force)"
fi

# 4) smoke inside Docker
echo "[bootstrap] python + package smoke"
docker compose run --rm app python -c "import relml,sys; print('relml', relml.__version__); print(sys.version)"
echo "[bootstrap] pytest smoke"
docker compose run --rm app pytest -q

# 5) (optional) dev ergonomics if installed
if docker compose run --rm app sh -lc "command -v pre-commit >/dev/null"; then
  echo "[bootstrap] installing pre-commit hook"
  docker compose run --rm app pre-commit install || true
fi

# 6) (optional) Node/Playwright peek
docker compose run --rm app node -v >/dev/null 2>&1 && \
  docker compose run --rm app node -v || true
docker compose run --rm app npx playwright --version >/dev/null 2>&1 && \
  docker compose run --rm app npx playwright --version || true

echo "[bootstrap] done ✅"
