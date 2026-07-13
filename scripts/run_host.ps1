param(
  [string]$Server = 'ws://127.0.0.1:8765',
  [int]$Fps = 8,
  [int]$Monitor = 1,
  [int]$MaxWidth = 1366,
  [int]$Quality = 62
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $ProjectRoot

$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
  $Python = (Get-Command python.exe -ErrorAction Stop).Source
}

& $Python -m symconnect.agent `
  --server $Server `
  --fps $Fps `
  --monitor $Monitor `
  --max-width $MaxWidth `
  --quality $Quality
