# disable-autostart.ps1 - stop SXSnap from starting with Windows
$ErrorActionPreference = "Continue"

$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$had = (Get-ItemProperty -Path $run -Name "SXSnap" -ErrorAction SilentlyContinue).SXSnap

if ($null -eq $had) {
    Write-Host "[i] SXSnap is not registered for autostart." -ForegroundColor Yellow
} else {
    Remove-ItemProperty -Path $run -Name "SXSnap" -ErrorAction SilentlyContinue
    Write-Host "[v] Autostart removed." -ForegroundColor Green
}
