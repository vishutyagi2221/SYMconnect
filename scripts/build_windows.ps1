[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^wss://')]
  [string]$ServerUrl,

  [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9]+)?$')]
  [string]$Version = '0.2.0',

  [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $ProjectRoot

$NormalizedServerUrl = $ServerUrl.Trim().TrimEnd('/')
$ConfigDirectory = Join-Path $ProjectRoot 'build-config'
$ConfigPath = Join-Path $ConfigDirectory 'server_url.txt'
New-Item -ItemType Directory -Force -Path $ConfigDirectory | Out-Null
[System.IO.File]::WriteAllText(
  $ConfigPath,
  $NormalizedServerUrl,
  [System.Text.UTF8Encoding]::new($false)
)

$PythonCandidates = @(
  (Join-Path $ProjectRoot '.venv-symconnect-build\Scripts\python.exe'),
  (Join-Path $ProjectRoot '.venv\Scripts\python.exe')
)
$PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($PythonCommand) {
  $PythonCandidates += $PythonCommand.Source
}

$Python = $null
foreach ($Candidate in $PythonCandidates) {
  if (-not (Test-Path -LiteralPath $Candidate)) {
    continue
  }
  & $Candidate -c 'import PyInstaller, PIL, mss, pynput, pythonnet, websockets, webview' 2>$null
  if ($LASTEXITCODE -eq 0) {
    $Python = $Candidate
    break
  }
}
if (-not $Python) {
  throw 'No build Python has all required packages. Install requirements-build.txt first.'
}
Write-Host "Build Python: $Python"

& $Python -m PyInstaller --clean --noconfirm '.\SYMconnect.spec'
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if ($SkipInstaller) {
  Write-Host "Portable EXE: $(Join-Path $ProjectRoot 'dist\SYMconnect.exe')"
  exit 0
}

$IsccCandidates = @(
  (Join-Path $ProjectRoot '.tools\InnoSetup\ISCC.exe'),
  (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
  (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
)
$Iscc = $IsccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Iscc) {
  $IsccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
  if ($IsccCommand) {
    $Iscc = $IsccCommand.Source
  }
}
if (-not $Iscc) {
  throw 'Inno Setup 6 is required. Install it system-wide or under .tools\InnoSetup.'
}

& $Iscc "/DMyAppVersion=$Version" '.\installer\SYMconnect.iss'
if ($LASTEXITCODE -ne 0) {
  throw "Inno Setup failed with exit code $LASTEXITCODE"
}

$InstallerPath = Join-Path $ProjectRoot "installer\output\SYMconnect-Setup-$Version.exe"
$Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $InstallerPath
$ChecksumPath = "$InstallerPath.sha256"
$ChecksumLine = "$($Hash.Hash)  $(Split-Path -Leaf $InstallerPath)"
[System.IO.File]::WriteAllText(
  $ChecksumPath,
  "$ChecksumLine`n",
  [System.Text.UTF8Encoding]::new($false)
)
Write-Host "Installer: $InstallerPath"
Write-Host "SHA256:   $($Hash.Hash)"
Write-Host "Checksum:  $ChecksumPath"
