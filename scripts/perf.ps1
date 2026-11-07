<# Same isolated benchmark for either release executable. Requires Python for the developer harness only. #>
param(
    [Parameter(Mandatory)] [string]$Exe,
    [string]$Ledger = '',
    [string]$Out = 'docs/perf-result.json',
    [int]$Settle = 60,
    [int]$Idle = 30
)
$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path (Split-Path $PSScriptRoot -Parent) '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = (Get-Command python -ErrorAction Stop).Source }
$arguments = @((Join-Path $PSScriptRoot 'bench_release.py'), $Exe, '--output', $Out, '--settle', $Settle, '--idle', $Idle)
if ($Ledger) { $arguments += @('--ledger', $Ledger) }
& $pythonPath @arguments
if ($LASTEXITCODE -ne 0) { throw "Benchmark failed ($LASTEXITCODE)" }
