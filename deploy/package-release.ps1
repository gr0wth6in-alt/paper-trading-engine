# Build the frontend on Windows and package a release tarball for the VPS.
#   powershell -ExecutionPolicy Bypass -File deploy\package-release.ps1
# Output: release\paper-trading-engine-<UTC timestamp>.tar.gz
# Never included: .env, data/ (databases), .venv, node_modules, caches, logs, test output.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host 'Building frontend (npm run build)...'
Push-Location frontend
try {
    if (-not (Test-Path 'node_modules\.bin\vite.cmd')) { npm ci }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }
if (-not (Test-Path 'frontend\dist\index.html')) { throw 'frontend\dist\index.html is missing' }

New-Item -ItemType Directory -Force -Path release | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$archive = "release\paper-trading-engine-$stamp.tar.gz"
$excludes = @(
    './.env', './.env.*.local', './data', './release', './.venv', './frontend/node_modules',
    '*/__pycache__', './.pytest_cache', './.ruff_cache', './frontend/test-results',
    './frontend/playwright-report', '*.egg-info', '*.log', '*.err', '*.exit', '*.db', '*.db-*',
    '*.lock.tmp', './.git', './.kiro'
)
$args = @('-czf', $archive) + ($excludes | ForEach-Object { "--exclude=$_" }) + @('.')
# bsdtar ships with Windows 10+; it keeps LF line endings and Unix modes are set on the VPS.
& tar.exe @args
if ($LASTEXITCODE -ne 0) { throw 'tar failed' }

$listing = & tar.exe -tzf $archive
foreach ($forbidden in @('./.env', './data/')) {
    if ($listing -contains $forbidden -or ($listing | Where-Object { $_ -like "$forbidden*" -and $_ -ne './.env.example' })) {
        Remove-Item $archive
        throw "Refusing to ship $forbidden"
    }
}
$size = [math]::Round((Get-Item $archive).Length / 1MB, 1)
Write-Host "Created $archive ($size MB, $($listing.Count) entries)"
Write-Host "Upload:  scp $archive <user>@<vps>:/tmp/"
