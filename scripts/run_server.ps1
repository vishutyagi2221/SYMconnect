param(
  [string]$HostName = '127.0.0.1',
  [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $ProjectRoot

$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
  $Python = (Get-Command python.exe -ErrorAction Stop).Source
}

& $Python -m symconnect.server --host $HostName --port $Port
