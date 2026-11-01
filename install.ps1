# kraken installer for Windows. Double-click install.cmd (it runs this file).
# Installs anything missing (Python, Node.js, gmgn-cli), sets up kraken, adds a desktop shortcut,
# then starts kraken. Your GMGN key is connected on the setup page that opens in your browser.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Say($msg, $color = "Gray") { Write-Host $msg -ForegroundColor $color }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Find-Python {
    foreach ($c in @(@("py", "-3"), @("python"), @("python3"))) {
        try {
            $exe = $c[0]; $rest = @($c | Select-Object -Skip 1)
            $v = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v) {
                $p = $v.Trim().Split("."); if ([int]$p[0] -eq 3 -and [int]$p[1] -ge 10) { return ,$c }
            }
        } catch {}
    }
    return $null
}
function Install-With-Winget($id, $name) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Say "$name is missing and this PC doesn't have winget to install it automatically." Yellow
        Say "Install $name yourself, then run install.cmd again:" Yellow
        if ($name -eq "Python") { Say "  https://www.python.org/downloads/  (tick 'Add python.exe to PATH')" }
        else { Say "  https://nodejs.org  (the LTS version)" }
        Read-Host "Press Enter to close"; exit 1
    }
    Say "Installing $name (this can take a few minutes)..." Cyan
    winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
}

Write-Host ""
Say "  kraken installer" Cyan
Write-Host ""

# 1. Python
$py = Find-Python
if (-not $py) { Install-With-Winget "Python.Python.3.12" "Python"; $py = Find-Python }
if (-not $py) { Say "Python was installed, but Windows needs a fresh window to see it. Close this window and double-click install.cmd again." Yellow; Read-Host "Press Enter to close"; exit 1 }
Say "[1/5] Python ready" Green

# 2. Node.js (needed for gmgn-cli)
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Install-With-Winget "OpenJS.NodeJS.LTS" "Node.js" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Say "Node.js was installed, but Windows needs a fresh window to see it. Close this window and double-click install.cmd again." Yellow; Read-Host "Press Enter to close"; exit 1 }
Say "[2/5] Node.js ready" Green

# 3. gmgn-cli (GMGN's official command-line tool)
$needCli = -not (Get-Command gmgn-cli -ErrorAction SilentlyContinue)
if (-not $needCli) {
    # kraken needs gmgn-cli 1.7+ (call-outs, name search). Update older installs.
    try { $v = [version](((gmgn-cli --version) 2>$null | Select-String -Pattern '\d+\.\d+\.\d+').Matches[0].Value) } catch { $v = [version]"0.0.0" }
    if ($v -lt [version]"1.7.0") { Say "Updating gmgn-cli ($v -> latest)..." Cyan; $needCli = $true }
}
if ($needCli) {
    npm install -g gmgn-cli@latest
    Refresh-Path
}
Say "[3/5] gmgn-cli ready" Green

# 4. kraken's Python packages, in a private folder (.venv) so nothing else on your PC changes
if (-not (Test-Path ".venv\Scripts\python.exe")) { $exe = $py[0]; $rest = @($py | Select-Object -Skip 1); & $exe @rest -m venv .venv }
& .venv\Scripts\python.exe -m pip install --upgrade pip --quiet --disable-pip-version-check
& .venv\Scripts\python.exe -m pip install -r requirements.txt --quiet --disable-pip-version-check
Say "[4/5] kraken installed" Green

# 5. Desktop shortcut
try {
    $desk = [Environment]::GetFolderPath("Desktop")
    $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desk "kraken.lnk"))
    $lnk.TargetPath = Join-Path $PSScriptRoot "run.cmd"
    $lnk.WorkingDirectory = $PSScriptRoot
    $lnk.Description = "Start kraken"
    $lnk.Save()
    Say "[5/5] Desktop shortcut created: kraken" Green
} catch { Say "[5/5] Couldn't create a desktop shortcut (start kraken with run.cmd instead)" Yellow }

Write-Host ""
Say "All set! kraken is starting and will open in your browser." Cyan
Say "If it's your first time, the page walks you through connecting your GMGN key."
Say "Next time, just double-click the kraken icon on your desktop."
Write-Host ""
& .venv\Scripts\python.exe -m kraken
