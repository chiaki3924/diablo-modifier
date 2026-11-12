# Build the single-file Windows executable.
# Requires Python 3.12 (the bundled .pyc modules are 3.12 bytecode) and PyInstaller.
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1 -Python C:\Python312\python.exe
param(
    [string]$Python = "python",
    [switch]$SkipSelftest
)
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

$Root = Split-Path -Parent $PSScriptRoot
$App = Join-Path $Root "app"
$Lib = Join-Path $Root "lib"
$Pyc = Join-Path $Root "_d1pyc"
$Data = Join-Path $Root "data\game-tables"
$Build = Join-Path $Root "build"
$Stage = Join-Path $Build "stage"
$Dist = Join-Path $Root "dist"
$Work = Join-Path $Build "pyinstaller"
$ExeName = "暗黑破坏神1存档修改器-v2"
$Exe = Join-Path $Dist "$ExeName.exe"

# ---------- 1. toolchain check ----------
$ver = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($LASTEXITCODE -ne 0) { throw "Cannot run Python: $Python" }
if ($ver.Trim() -ne "3.12") { throw "Python 3.12 required (got $ver). Use -Python <path-to-python3.12>" }
& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) { throw "PyInstaller missing. Run: $Python -m pip install -r requirements.txt" }

# ---------- 2. stage bundled data ----------
Remove-Item $Stage, $Work, $Dist -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path `
    (Join-Path $Stage "_d1pyc"), `
    (Join-Path $Stage "_d1lib"), `
    (Join-Path $Stage "_d1lib\py"), `
    (Join-Path $Stage "_d1lib\data"), `
    (Join-Path $Stage "DevilutionX-1.5.5\Source"), `
    (Join-Path $Stage "devilutionX\assets\txtdata\items") | Out-Null

$pycNames = @("d1save", "d1codec", "d1mpq", "d1pkware", "d1rng", "d1items", "d1spells")
foreach ($n in $pycNames) {
    $src = Join-Path $Pyc "$n.pyc"
    if (-not (Test-Path $src)) { throw "Missing $src" }
    Copy-Item $src (Join-Path $Stage "_d1pyc")
}
Write-Host "== staged legacy pyc modules"

Copy-Item (Join-Path $Lib "d1stash2.py") (Join-Path $Stage "_d1lib")
foreach ($n in @("d1itemgen", "d1tables", "d1i18n")) {
    $src = Join-Path $Lib "$n.py"
    if (-not (Test-Path $src)) { throw "Missing $src" }
    Copy-Item $src (Join-Path $Stage "_d1lib\py")
}
Copy-Item (Join-Path $Lib "data\zh_CN.json") (Join-Path $Stage "_d1lib\data")
Copy-Item (Join-Path $App "zh_fallback.json") $Stage
Write-Host "== staged lib + zh_CN.json"

$srcFiles = @("itemdat.h", "items.h", "spelldat.h", "itemdat.cpp", "items.cpp", "spelldat.cpp", "cursor.cpp")
foreach ($f in $srcFiles) {
    $src = Join-Path $Data "DevilutionX-1.5.5\Source\$f"
    if (-not (Test-Path $src)) { throw "Missing data table $src" }
    Copy-Item $src (Join-Path $Stage "DevilutionX-1.5.5\Source")
}
$tsvDir = Join-Path $Data "devilutionX\assets\txtdata\items"
if (Test-Path $tsvDir) {
    Copy-Item (Join-Path $tsvDir "*.tsv") (Join-Path $Stage "devilutionX\assets\txtdata\items")
}
Write-Host "== staged 1.5.5 item tables + 1.6.0 TSV"

# ---------- 3. PyInstaller (onefile / windowed) ----------
$args = @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", $ExeName,
    "--distpath", $Dist,
    "--workpath", $Work,
    "--specpath", $Build,
    "--paths", $App,
    "--add-data", "$Stage\_d1pyc;_d1pyc",
    "--add-data", "$Stage\_d1lib;_d1lib",
    "--add-data", "$Stage\zh_fallback.json;.",
    "--add-data", "$Stage\DevilutionX-1.5.5;DevilutionX-1.5.5",
    "--add-data", "$Stage\devilutionX;devilutionX",
    "--hidden-import", "tkinter",
    "--hidden-import", "tkinter.ttk",
    "--hidden-import", "tkinter.filedialog",
    "--hidden-import", "tkinter.messagebox",
    "--hidden-import", "tkinter.font",
    "--hidden-import", "glob",
    "--hidden-import", "shutil",
    "--hidden-import", "bz2",
    "--hidden-import", "zlib",
    "--hidden-import", "struct",
    "--hidden-import", "time",
    "--hidden-import", "os",
    "--hidden-import", "sys"
)
$icon = Join-Path $PSScriptRoot "icon.ico"
if (Test-Path $icon) { $args += @("--icon", $icon) }
$args += (Join-Path $App "d1editor2.py")

Push-Location $Root
try {
    & $Python @args
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

if (-not (Test-Path $Exe)) { throw "Output missing: $Exe" }
$size = [math]::Round((Get-Item $Exe).Length / 1MB, 2)
$sha = (Get-FileHash $Exe -Algorithm SHA256).Hash
Write-Host "== output: $Exe ($size MB)"
Write-Host "== sha256: $sha"

# ---------- 4. selftest ----------
if (-not $SkipSelftest) {
    $log = Join-Path $env:TEMP "d1editor2_selftest.log"
    Remove-Item $log -ErrorAction SilentlyContinue
    $p = Start-Process -FilePath $Exe -ArgumentList "--selftest" -PassThru -Wait
    if (Test-Path $log) { Get-Content $log -Encoding UTF8 }
    if ($p.ExitCode -ne 0) { throw "Packaged selftest failed (exit $($p.ExitCode))" }
    Write-Host "== BUILD OK"
}
