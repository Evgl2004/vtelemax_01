param(
    [switch]$Recreate = $false,
    [switch]$SkipInstall = $false
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
$sitePackages = Join-Path $venvPath 'Lib\site-packages'
$fallbackPython = 'C:\Program Files\PostgreSQL\17\pgAdmin 4\python\python.exe'
$tmpDir = Join-Path $projectRoot '.tmp'

New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$env:TMP = $tmpDir
$env:TEMP = $tmpDir

$pythonCandidates = @(
    'C:\Users\admin_eas\AppData\Local\Programs\Python\Python313\python.exe',
    $fallbackPython
)

if ($Recreate -and (Test-Path $venvPath)) {
    Write-Host "Removing existing virtual environment: $venvPath"
    Remove-Item -Recurse -Force $venvPath
}

$selectedPythonForVenv = $null
foreach ($candidate in $pythonCandidates) {
    if (Test-Path $candidate) {
        try {
            & $candidate --version | Out-Null
            & $candidate -m venv --help | Out-Null
            $selectedPythonForVenv = $candidate
            break
        } catch {
            # Candidate is not suitable for venv creation.
        }
    }
}

if (-not (Test-Path $fallbackPython)) {
    throw "Fallback Python not found: $fallbackPython"
}

$realVenvReady = $false
if ($selectedPythonForVenv -and -not (Test-Path $venvPython)) {
    Write-Host "Creating real .venv using: $selectedPythonForVenv"
    & $selectedPythonForVenv -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Real .venv creation command failed with exit code $LASTEXITCODE."
    }
}

if (Test-Path $venvPython) {
    $realVenvReady = $true
}

if ($realVenvReady) {
    if (-not $SkipInstall) {
        Write-Host "Upgrading pip and installing project dependencies into real .venv..."
        & $venvPython -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) {
            throw "pip upgrade failed in real .venv mode."
        }
        & $venvPython -m pip install -e ".[dev,telegram,vk,max]"
        if ($LASTEXITCODE -ne 0) {
            throw "Dependency installation failed in real .venv mode."
        }
    }
    Write-Host "Done. Real virtual environment path: $venvPath"
    exit 0
}

# Fallback mode for environments where "python -m venv" is unavailable.
Write-Warning "Real .venv creation is unavailable. Switching to fallback site-packages mode."
New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null

if (-not $SkipInstall) {
    Write-Host "Installing dependencies into fallback target: $sitePackages"
    Push-Location $projectRoot
    try {
        & $fallbackPython -m pip install --target $sitePackages --upgrade ".[dev,telegram,vk,max]"
        if ($LASTEXITCODE -ne 0) {
            throw "Dependency installation failed in fallback mode."
        }
    } finally {
        Pop-Location
    }
}

Write-Host "Done. Fallback dependencies installed in: $sitePackages"
