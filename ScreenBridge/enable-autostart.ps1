# enable-autostart.ps1 - start SXSnap with Windows (current user, no admin)
$ErrorActionPreference = "Stop"

$exe = Join-Path $PSScriptRoot "SXSnap.exe"
if (-not (Test-Path $exe)) {
    Write-Host "[x] SXSnap.exe not found next to this script." -ForegroundColor Red
    exit 1
}

$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
if (-not (Test-Path $run)) { New-Item -Path $run -Force | Out-Null }

New-ItemProperty -Path $run -Name "SXSnap" -Value "`"$exe`"" -PropertyType String -Force | Out-Null

$now = (Get-ItemProperty -Path $run -Name "SXSnap").SXSnap
Write-Host "[v] Autostart enabled." -ForegroundColor Green
Write-Host "    $now"
Write-Host ""
Write-Host "    Undo with: .\disable-autostart.ps1"
