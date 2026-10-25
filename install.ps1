# OMGA installer — Windows (PowerShell 5.1+)
# https://github.com/isPoori/omga
$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/isPoori/omga.git"
$RepoTarball = "https://github.com/isPoori/omga/archive/refs/heads/main.zip"

$OmgaRoot = if ($env:OMGA_HOME) { $env:OMGA_HOME } else { Join-Path $env:LOCALAPPDATA "omga" }
$OmgaVenv = Join-Path $OmgaRoot "venv"
$OmgaSrc = Join-Path $OmgaRoot "src"
$OmgaBin = Join-Path $OmgaRoot "bin"
$OmgaShim = Join-Path $OmgaBin "omga.cmd"

function Write-Step($msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Info($msg) { Write-Host $msg -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  [X] $msg" -ForegroundColor Red; exit 1 }

Write-Info "OMGA installer (Windows)"

# Python 3.10+
Write-Info "Checking Python 3.10+..."
$py = $null
foreach ($candidate in @("py -3.12", "py -3.11", "py -3.10", "python3", "python")) {
    try {
        $ver = Invoke-Expression "$candidate -c `"import sys; print(sys.version_info[:2])`"" 2>$null
        if ($ver -match "\(3,\s*(1[0-9]|[2-9][0-9])\)") {
            $py = $candidate
            break
        }
    } catch { }
}
if (-not $py) {
    Write-Warn "Python 3.10+ not found."
    Write-Host "  Install from https://www.python.org/downloads/ (check 'Add to PATH')"
    Fail "Python required."
}
Write-Step "Found: $py"

# Source
Write-Info "Fetching OMGA source..."
New-Item -ItemType Directory -Force -Path $OmgaRoot | Out-Null
if (Test-Path (Join-Path $OmgaSrc ".git")) {
    Push-Location $OmgaSrc
    git fetch --depth 1 origin main 2>$null
    if ($LASTEXITCODE -ne 0) { git fetch --depth 1 origin master 2>$null }
    git reset --hard FETCH_HEAD 2>$null
    Pop-Location
    Write-Step "Repository updated"
} elseif (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path $OmgaSrc) { Remove-Item -Recurse -Force $OmgaSrc }
    git clone --depth 1 $RepoUrl $OmgaSrc
    Write-Step "Cloned repository"
} else {
    Write-Warn "git not found; downloading zip..."
    $zip = Join-Path $env:TEMP "omga-main.zip"
    Invoke-WebRequest -Uri $RepoTarball -OutFile $zip -UseBasicParsing
    $extract = Join-Path $env:TEMP "omga-extract"
    if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }
    Expand-Archive -Path $zip -DestinationPath $extract -Force
    $inner = Get-ChildItem $extract -Directory | Select-Object -First 1
    if (Test-Path $OmgaSrc) { Remove-Item -Recurse -Force $OmgaSrc }
    Copy-Item -Recurse $inner.FullName $OmgaSrc
    Write-Step "Downloaded source archive"
}

# Venv
Write-Info "Setting up virtual environment..."
if (-not (Test-Path $OmgaVenv)) {
    Invoke-Expression "$py -m venv `"$OmgaVenv`""
    Write-Step "Created venv"
} else {
    Write-Step "Using existing venv"
}
$venvPython = Join-Path $OmgaVenv "Scripts\python.exe"
& $venvPython -m pip install -q --upgrade pip wheel
& $venvPython -m pip install -q -e $OmgaSrc
Write-Step "Installed omga-cli into venv"

# Shim
Write-Info "Adding omga to user PATH..."
New-Item -ItemType Directory -Force -Path $OmgaBin | Out-Null
$venvOmga = Join-Path $OmgaVenv "Scripts\omga.exe"
if (-not (Test-Path $venvOmga)) {
    $venvOmga = Join-Path $OmgaVenv "Scripts\omga-script.py"
}
@"
@echo off
"%~dp0..\venv\Scripts\omga.exe" %*
"@ | Set-Content -Path $OmgaShim -Encoding ASCII

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$paths = @($userPath -split ';' | Where-Object { $_ })
if ($paths -notcontains $OmgaBin) {
    $newPath = ($paths + $OmgaBin) -join ';'
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Step "Added $OmgaBin to user PATH"
} else {
    Write-Step "PATH already contains omga bin directory"
}

Write-Host ""
Write-Host "Installation complete." -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:"
Write-Host "    omga           Start a session"
Write-Host "    omga doctor    Run diagnostics"
Write-Host ""
Write-Warn "Open a new terminal for PATH changes to apply."
Write-Host "  Install location: $OmgaRoot"
Write-Host ""
