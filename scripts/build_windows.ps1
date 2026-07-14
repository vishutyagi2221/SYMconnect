[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^wss://')]
  [string]$ServerUrl,

  [string]$Version = '',

  [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $ProjectRoot

$VersionSource = Get-Content -LiteralPath (Join-Path $ProjectRoot 'symconnect\version.py') -Raw
if ($VersionSource -notmatch 'VERSION\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"') {
  throw 'Could not read the application version from symconnect\version.py.'
}
$SourceVersion = $Matches[1]
if ([string]::IsNullOrWhiteSpace($Version)) {
  $Version = $SourceVersion
}
if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
  throw "Invalid build version: $Version"
}
if ($Version -ne $SourceVersion) {
  throw "Build version $Version does not match source version $SourceVersion."
}

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

$PytestTemp = Join-Path $ProjectRoot 'build\pytest-tmp'
New-Item -ItemType Directory -Force -Path $PytestTemp | Out-Null
& $Python -B -m pytest -q -p no:cacheprovider --basetemp $PytestTemp
if ($LASTEXITCODE -ne 0) {
  throw "Tests failed with exit code $LASTEXITCODE"
}

$Node = Get-Command node.exe -ErrorAction SilentlyContinue
if (-not $Node) {
  throw 'Node.js is required to validate the packaged JavaScript.'
}
& $Node.Source --check '.\symconnect\static\app.js'
if ($LASTEXITCODE -ne 0) {
  throw "JavaScript validation failed with exit code $LASTEXITCODE"
}

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

$WebView2Bootstrapper = Join-Path $ProjectRoot 'installer\MicrosoftEdgeWebView2Setup.exe'
if (-not (Test-Path -LiteralPath $WebView2Bootstrapper)) {
  Write-Host 'Downloading the official Microsoft Edge WebView2 bootstrapper...'
  Invoke-WebRequest `
    -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' `
    -OutFile $WebView2Bootstrapper `
    -UseBasicParsing
}
$WebView2Signature = Get-AuthenticodeSignature -LiteralPath $WebView2Bootstrapper
if (
  $WebView2Signature.Status -ne 'Valid' -or
  $WebView2Signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation'
) {
  throw "WebView2 bootstrapper signature is not valid: $($WebView2Signature.Status)"
}

& $Iscc "/DMyAppVersion=$Version" '.\installer\SYMconnect.iss'
if ($LASTEXITCODE -ne 0) {
  throw "Inno Setup failed with exit code $LASTEXITCODE"
}

$InstallerPath = Join-Path $ProjectRoot "installer\output\SYMconnect-Setup-$Version.exe"
$Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $InstallerPath
$HashValue = $Hash.Hash.ToLowerInvariant()
$ChecksumPath = "$InstallerPath.sha256"
$AssetName = Split-Path -Leaf $InstallerPath
$ChecksumLine = "$HashValue  $AssetName"
[System.IO.File]::WriteAllText(
  $ChecksumPath,
  "$ChecksumLine`n",
  [System.Text.UTF8Encoding]::new($false)
)
$ManifestPath = Join-Path $ProjectRoot 'installer\output\update.json'
$Manifest = [ordered]@{
  version = $Version
  download_url = "https://github.com/vishutyagi2221/SYMconnect/releases/download/v$Version/$AssetName"
  size = (Get-Item -LiteralPath $InstallerPath).Length
  sha256 = $HashValue
} | ConvertTo-Json
[System.IO.File]::WriteAllText(
  $ManifestPath,
  "$Manifest`n",
  [System.Text.UTF8Encoding]::new($false)
)
Write-Host "Installer: $InstallerPath"
Write-Host "SHA256:   $HashValue"
Write-Host "Checksum:  $ChecksumPath"
Write-Host "Manifest:  $ManifestPath"
