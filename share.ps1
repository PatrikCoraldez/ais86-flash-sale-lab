$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
docker compose --profile share up -d tunnel
if ($LASTEXITCODE -ne 0) { throw "No se pudo abrir el túnel." }
Write-Host "Copia la URL HTTPS trycloudflare.com del registro. Detén el acceso con docker compose stop tunnel."
docker compose logs -f tunnel
