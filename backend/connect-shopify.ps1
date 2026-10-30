<#
  Connect (or disconnect) your Shopify store. Saves the settings into backend\.env.
  Connect:     powershell -ExecutionPolicy Bypass -File .\connect-shopify.ps1
  Disconnect:  powershell -ExecutionPolicy Bypass -File .\connect-shopify.ps1 -Disconnect
  The key is typed hidden and is never printed. No server restart is needed.
#>
param([switch]$Disconnect)
$ErrorActionPreference = "Stop"
$envFile = Join-Path $PSScriptRoot ".env"
$lines = @()
if (Test-Path $envFile) { $lines = @(Get-Content $envFile -Encoding UTF8) }
$lines = @($lines | Where-Object { $_ -notmatch '^\s*SHOPIFY_(SHOP|STORE|ACCESS_TOKEN|CLIENT_ID|CLIENT_SECRET|DEMO)\s*=' })

function Write-Env([string[]]$extra) {
  [IO.File]::WriteAllLines($envFile, [string[]](@($lines) + $extra), (New-Object Text.UTF8Encoding $false))
}
function Read-Secret([string]$prompt) {
  $s = Read-Host $prompt -AsSecureString
  $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
  try { [Runtime.InteropServices.Marshal]::PtrToStringAuto($b) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

if ($Disconnect) {
  Write-Env @()
  Write-Host "Disconnected. The writer is back on the sample store." -ForegroundColor Yellow
  exit
}

Write-Host ""
Write-Host "  Connect your Shopify store" -ForegroundColor Cyan
Write-Host "  You need an app with the read_products and write_products permissions, installed on the store."
Write-Host ""
$shop = (Read-Host "  Store name (the part before .myshopify.com)").Trim()
$shop = $shop -replace '^https?://', '' -replace '\.myshopify\.com.*$', '' -replace '/.*$', ''
if (-not $shop) { throw "A store name is needed." }

Write-Host "    1) Admin API access token (starts with shpat_)"
Write-Host "    2) Client ID and secret (Dev Dashboard app)"
$choice = (Read-Host "  Choose 1 or 2").Trim()
if ($choice -eq "2") {
  $id = (Read-Host "  Client ID").Trim()
  $secret = (Read-Secret "  Client secret (hidden)").Trim()
  if (-not $id -or -not $secret) { throw "Both the client ID and the secret are needed." }
  Write-Env @("SHOPIFY_SHOP=$shop", "SHOPIFY_CLIENT_ID=$id", "SHOPIFY_CLIENT_SECRET=$secret")
} else {
  $token = (Read-Secret "  Access token (hidden)").Trim()
  if (-not $token) { throw "The access token is needed." }
  Write-Env @("SHOPIFY_SHOP=$shop", "SHOPIFY_ACCESS_TOKEN=$token")
}
Write-Host ""
Write-Host "  Saved to $envFile" -ForegroundColor Green

try {
  $r = Invoke-RestMethod "http://127.0.0.1:8000/shopify/check" -TimeoutSec 60
  if ($r.ok) { Write-Host "  Connected to $($r.shop). Refresh the page." -ForegroundColor Green }
  else { Write-Host "  Saved, but Shopify said: $($r.message)" -ForegroundColor Yellow }
} catch {
  Write-Host "  The writer isn't running yet. Start it, then press Check connection on the page." -ForegroundColor Yellow
}
