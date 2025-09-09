param(
  [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
Set-Location $root
Write-Host "[bootstrap] repo: $root"

# 1) .env
if (-not (Test-Path ".env")) {
  Write-Host "[bootstrap] creating .env from config/env.example"
  Copy-Item "config/env.example" ".env"
} else {
  Write-Host "[bootstrap] .env already present"
}

# 2) data dirs
Write-Host "[bootstrap] ensuring data directories"
@("data","data/raw","data/interim","data/processed","data/logs") | ForEach-Object {
  New-Item -ItemType Directory -Path $_ -Force | Out-Null
}

# 3) (optional) rebuild
if ($Rebuild.IsPresent) {
  Write-Host "[bootstrap] rebuilding Docker image"
  docker compose build
} else {
  Write-Host "[bootstrap] skip rebuild (use -Rebuild to force)"
}

# 4) smoke inside Docker
Write-Host "[bootstrap] python + package smoke"
docker compose run --rm app python -c "import relml,sys; print('relml', relml.__version__); print(sys.version)"

Write-Host "[bootstrap] pytest smoke"
docker compose run --rm app pytest -q

# 5) (optional) dev ergonomics if installed
try {
  docker compose run --rm app pre-commit --version | Out-Null
  Write-Host "[bootstrap] installing pre-commit hook"
  docker compose run --rm app pre-commit install
} catch { }

# 6) (optional) Node/Playwright peek
try { docker compose run --rm app node -v } catch { }
try { docker compose run --rm app npx playwright --version } catch { }

Write-Host "[bootstrap] done ✅"
