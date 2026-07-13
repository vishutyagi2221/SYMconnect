param([int]$Port = 8765)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
  $Python = (Get-Command python.exe -ErrorAction Stop).Source
}

$ServerProcess = Start-Process `
  -FilePath $Python `
  -ArgumentList '-m', 'symconnect.server', '--host', '127.0.0.1', '--port', $Port `
  -WorkingDirectory $ProjectRoot `
  -WindowStyle Hidden `
  -PassThru

try {
  Start-Sleep -Seconds 2
  $env:SYMCONNECT_SERVER_URL = "ws://127.0.0.1:$Port"
  & $Python -m symconnect.desktop_app
}
finally {
  if (-not $ServerProcess.HasExited) {
    Stop-Process -Id $ServerProcess.Id -Force
  }
}
