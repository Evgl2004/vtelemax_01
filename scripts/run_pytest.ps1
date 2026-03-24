param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$srcRoot = Join-Path $projectRoot 'src'
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$sitePackages = Join-Path $projectRoot '.venv\Lib\site-packages'
$fallbackPython = 'C:\Program Files\PostgreSQL\17\pgAdmin 4\python\python.exe'

if (-not $PytestArgs -or $PytestArgs.Count -eq 0) {
    $PytestArgs = @('tests')
}

$canUseVenvPython = $false
if (Test-Path $venvPython) {
    try {
        & $venvPython --version 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $canUseVenvPython = $true
        }
    } catch {
        $canUseVenvPython = $false
    }
}

if ($canUseVenvPython) {
    & $venvPython -m pytest @PytestArgs
    exit $LASTEXITCODE
}

if (-not (Test-Path $sitePackages)) {
    throw "site-packages directory not found: $sitePackages"
}

if (-not (Test-Path $fallbackPython)) {
    throw "Fallback python not found: $fallbackPython"
}

# Fallback path: run pytest via stable Python and inject dependencies from .venv.
$pytestCall = @(
    'import sys'
    "sys.path.insert(0, r'$srcRoot')"
    "sys.path.insert(0, r'$projectRoot')"
    "sys.path.insert(0, r'$sitePackages')"
    'import pytest'
)

$escapedArgs = ($PytestArgs | ForEach-Object { $_.Replace("'", "''") })
$argsLiteral = $escapedArgs | ForEach-Object { "'$_'" }
$pytestCall += "raise SystemExit(pytest.main(['-p', 'no:cacheprovider', $($argsLiteral -join ', ')]))"
$inlineCode = $pytestCall -join '; '

& $fallbackPython -c $inlineCode
exit $LASTEXITCODE
