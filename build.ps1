param([switch]$SkipTests, [string]$Dotnet = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_NOLOGO = '1'
$output = 'dist-v0.4'

# 1. .NET 10 SDK for the replay reader: -Dotnet path, a project-local .dotnet, a system SDK, or a fresh local install.
function Test-Sdk($exe) { $exe -and (Test-Path -LiteralPath $exe) -and ((& $exe --list-sdks 2>$null) -match '^10\.') }
$local = Join-Path $PSScriptRoot '.dotnet\dotnet.exe'
if (-not (Test-Sdk $Dotnet)) {
    $system = (Get-Command dotnet -ErrorAction SilentlyContinue).Source
    if (Test-Sdk $local) { $Dotnet = $local }
    elseif (Test-Sdk $system) { $Dotnet = $system }
    else {
        Write-Output 'Installing a private .NET 10 SDK into .dotnet (no system changes)...'
        $installer = Join-Path $env:TEMP 'dotnet-install.ps1'
        Invoke-WebRequest -UseBasicParsing 'https://dot.net/v1/dotnet-install.ps1' -OutFile $installer
        & $installer -Channel 10.0 -InstallDir (Join-Path $PSScriptRoot '.dotnet') -NoPath
        $Dotnet = $local
    }
}

# 2. Python environment and tests.
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    py -3.14 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install 64-bit Python 3.14, or create .venv with Python 3.11-3.14.' }
}
& $pythonPath -m pip install -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $pythonPath -m pip install --no-deps --no-build-isolation -e .
if ($LASTEXITCODE -ne 0) { throw 'Application installation failed' }

# 3. Replay reader: a self-contained single-file exe (no .NET install needed on the player's PC).
& $Dotnet publish 'replay-reader\LootLedger.ReplayReader.csproj' -c Release -o 'replay-reader\publish' -clp:ErrorsOnly
if ($LASTEXITCODE -ne 0) { throw 'Replay reader build failed' }
& $Dotnet build-server shutdown | Out-Null

if (-not $SkipTests) {
    & $pythonPath -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; executable was not built' }
}

# 4. Desktop app.
$env:LOOTLEDGER_DOTNET_ROOT = Split-Path -Parent $Dotnet
& $pythonPath -m PyInstaller --noconfirm --distpath $output LootLedger.spec
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
Write-Output "Built $output\LootLedger.exe (single file; licences are bundled inside)."
