$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".env")) {
    docker run --rm -v "${PSScriptRoot}:/work" -w /work python:3.12-slim python tools/init_env.py
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear la configuración local." }
}
docker compose up --build -d --wait
if ($LASTEXITCODE -ne 0) { throw "El arranque falló. Revisa docker compose logs api worker." }
$port = ((Get-Content .env | Where-Object { $_ -match '^FLASH_PORT=' }) -split '=',2)[1]
Write-Host "Tienda: http://localhost:$port"
Write-Host "Prueba local: docker compose exec api python /app/tools/smoke.py --target http://127.0.0.1:8000"
