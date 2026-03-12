#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Deinstalliert den Skriptendruck-Dashboard Windows-Service.

.DESCRIPTION
    Dieses Skript:
    - Stoppt den Service "SkriptendruckDashboard"
    - Entfernt den Service aus Windows
    - Bereinigt optional die Log-Dateien

.PARAMETER KeepLogs
    Wenn gesetzt, werden die Log-Dateien nicht gelöscht.

.EXAMPLE
    .\uninstall_service.ps1

.EXAMPLE
    .\uninstall_service.ps1 -KeepLogs
#>

param(
    [switch]$KeepLogs
)

$ErrorActionPreference = "Stop"

# ============================================
# Konfiguration
# ============================================
$ServiceName = "SkriptendruckDashboard"
$ProjectRoot = $PSScriptRoot
$NssmDir = Join-Path $ProjectRoot "tools\nssm"
$NssmExe = Join-Path $NssmDir "nssm.exe"
$LogDir = Join-Path $ProjectRoot "logs"

# ============================================
# Funktionen
# ============================================

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host " $Text" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
}

function Write-Step {
    param([string]$Text)
    Write-Host "[>] $Text" -ForegroundColor Yellow
}

function Write-Success {
    param([string]$Text)
    Write-Host "[✓] $Text" -ForegroundColor Green
}

function Write-Error {
    param([string]$Text)
    Write-Host "[✗] $Text" -ForegroundColor Red
}

function Test-ServiceExists {
    param([string]$Name)
    $service = Get-Service -Name $Name -ErrorAction SilentlyContinue
    return $null -ne $service
}

# ============================================
# Hauptprogramm
# ============================================

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Yellow
Write-Host "║    Skriptendruck Dashboard - Windows Service Deinstallation  ║" -ForegroundColor Yellow
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Yellow

# Prüfen ob NSSM vorhanden
if (-not (Test-Path $NssmExe)) {
    # Fallback: sc.exe verwenden
    Write-Step "NSSM nicht gefunden, verwende sc.exe..."
    $UseScExe = $true
} else {
    $UseScExe = $false
}

# Prüfen ob Service existiert
if (-not (Test-ServiceExists -Name $ServiceName)) {
    Write-Host ""
    Write-Host "Service '$ServiceName' ist nicht installiert." -ForegroundColor Yellow
    exit 0
}

Write-Header "Service deinstallieren"

# Service stoppen
Write-Step "Stoppe Service '$ServiceName'..."
try {
    if ($UseScExe) {
        sc.exe stop $ServiceName 2>$null
    } else {
        & $NssmExe stop $ServiceName 2>$null
    }
    Start-Sleep -Seconds 2
    Write-Success "Service gestoppt"
} catch {
    Write-Host "  (Service war möglicherweise bereits gestoppt)" -ForegroundColor Gray
}

# Service entfernen
Write-Step "Entferne Service..."
if ($UseScExe) {
    sc.exe delete $ServiceName
} else {
    & $NssmExe remove $ServiceName confirm
}

if ($LASTEXITCODE -eq 0) {
    Write-Success "Service '$ServiceName' entfernt"
} else {
    Write-Error "Service-Entfernung möglicherweise fehlgeschlagen"
}

# Log-Dateien bereinigen
if (-not $KeepLogs -and (Test-Path $LogDir)) {
    Write-Step "Bereinige Log-Dateien..."
    
    $confirm = Read-Host "Log-Dateien in '$LogDir' löschen? (j/N)"
    if ($confirm -eq "j" -or $confirm -eq "J") {
        Remove-Item -Path "$LogDir\service_*.log" -Force -ErrorAction SilentlyContinue
        Write-Success "Log-Dateien gelöscht"
    } else {
        Write-Host "  Log-Dateien behalten" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Success "Deinstallation abgeschlossen!"
Write-Host ""
Write-Host "Hinweis: NSSM und das tools-Verzeichnis wurden nicht entfernt." -ForegroundColor Gray
Write-Host "         Zum vollständigen Entfernen: Remove-Item '$NssmDir' -Recurse" -ForegroundColor Gray
