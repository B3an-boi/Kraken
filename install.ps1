# kraken installer for Windows. Run from the repo folder:  .\install.cmd   (or: powershell -ExecutionPolicy Bypass -File install.ps1)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
Write-Host ""
Write-Host "  kraken installer" -ForegroundColor Cyan
Write-Host ""

function Find-Python {
    foreach ($c in @(@("py", "-3"), @("python"), @("python3"))) {
        try {
            $exe = $c[0]; $args_ = @($c | Select-Object -Skip 1)
            $v = & $exe @args_ -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v) {
                $parts = $v.Trim().Split("."); if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) { return ,$c }
            }
        } catch {}
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "Python 3.10+ not found." -ForegroundColor Yellow
    Write-Host "Install it with:  winget install -e --id Python.Python.3.12"
    Write-Host "(or from https://www.python.org/downloads/ - tick 'Add python.exe to PATH'), then run this installer again."
    exit 1
}
Write-Host "[1/3] Python OK ($($py -join ' '))" -ForegroundColor Green

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $exe = $py[0]; $rest = @($py | Select-Object -Skip 1)
    & $exe @rest -m venv .venv
}
& .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
Write-Host "[2/3] Dependencies installed in .venv" -ForegroundColor Green

$gm = Get-Command gmgn-cli -ErrorAction SilentlyContinue
if ($gm) {
    Write-Host "[3/3] gmgn-cli found" -ForegroundColor Green
} elseif (Get-Command npm -ErrorAction SilentlyContinue) {
    $a = Read-Host "[3/3] Install gmgn-cli for live GMGN data? (needed only with an API key) [y/N]"
    if ($a -match '^[yY]') { npm install -g gmgn-cli }
} else {
    Write-Host "[3/3] Skipped gmgn-cli (Node.js not installed). kraken runs on demo data without it." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done! Start kraken with:  .\run.cmd   (or double-click run.cmd)" -ForegroundColor Cyan
Write-Host "Optional - connect your GMGN key:  .\.venv\Scripts\python.exe -m kraken setup"
Write-Host ""
