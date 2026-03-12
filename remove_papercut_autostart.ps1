<#
.SYNOPSIS
    Entfernt den PaperCut Client Autostart Task.

.DESCRIPTION
    Entfernt den Task Scheduler Task für den automatischen Start des PaperCut Clients
    und beendet optional den laufenden Prozess.

.PARAMETER TaskName
    Name des zu entfernenden Task Scheduler Tasks.
    Standard: "PaperCut Client Autostart"

.PARAMETER StopProcess
    Beendet auch den laufenden PaperCut Client Prozess.
    Standard: $false

.EXAMPLE
    .\remove_papercut_autostart.ps1
    
.EXAMPLE
    .\remove_papercut_autostart.ps1 -StopProcess

.NOTES
    Erfordert Administrator-Rechte.
    Erstellt von: FSMB Regensburg
    Datum: 2026-03
#>

param(
    [string]$TaskName = "PaperCut Client Autostart",
    [switch]$StopProcess = $false
)

# ============================================================================
# Konfiguration
# ============================================================================

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "PaperCut Client Autostart Deinstallation"

# Farben für Ausgabe
function Write-Success { param($msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Warn { param($msg) Write-Host "[WARNUNG] $msg" -ForegroundColor Yellow }
function Write-Err { param($msg) Write-Host "[FEHLER] $msg" -ForegroundColor Red }

# ============================================================================
# Administrator-Check
# ============================================================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Yellow
Write-Host "  PaperCut Client Autostart Deinstallation" -ForegroundColor Yellow
Write-Host "  FSMB Regensburg - Skriptendruck" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Yellow
Write-Host ""

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Err "Dieses Skript erfordert Administrator-Rechte!"
    Write-Host "Bitte starten Sie PowerShell als Administrator und führen Sie das Skript erneut aus."
    exit 1
}

Write-Success "Administrator-Rechte vorhanden"

# ============================================================================
# Task prüfen
# ============================================================================

Write-Host ""
Write-Info "Suche Task '$TaskName'..."

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if (-not $existingTask) {
    Write-Warn "Task '$TaskName' existiert nicht."
    Write-Host ""
    
    # Liste alle PaperCut-bezogenen Tasks
    Write-Info "Suche nach anderen PaperCut Tasks..."
    $pcTasks = Get-ScheduledTask | Where-Object { $_.TaskName -like "*PaperCut*" -or $_.TaskName -like "*pc-client*" }
    
    if ($pcTasks) {
        Write-Host "Gefundene PaperCut-bezogene Tasks:"
        foreach ($task in $pcTasks) {
            Write-Host "  - $($task.TaskName) (Status: $($task.State))"
        }
    }
    else {
        Write-Host "Keine PaperCut-bezogenen Tasks gefunden."
    }
    
    exit 0
}

# Task-Details anzeigen
Write-Success "Task gefunden!"
Write-Host ""
Write-Host "Task-Details:"
Write-Host "  Name:    $($existingTask.TaskName)"
Write-Host "  Status:  $($existingTask.State)"
Write-Host "  Pfad:    $($existingTask.TaskPath)"

# ============================================================================
# Bestätigung
# ============================================================================

Write-Host ""
$confirm = Read-Host "Möchten Sie diesen Task wirklich entfernen? (j/n)"

if ($confirm -ne "j" -and $confirm -ne "J" -and $confirm -ne "y" -and $confirm -ne "Y") {
    Write-Info "Abbruch durch Benutzer."
    exit 0
}

# ============================================================================
# Task stoppen falls aktiv
# ============================================================================

if ($existingTask.State -eq "Running") {
    Write-Info "Stoppe laufenden Task..."
    try {
        Stop-ScheduledTask -TaskName $TaskName
        Write-Success "Task gestoppt"
    }
    catch {
        Write-Warn "Task konnte nicht gestoppt werden: $_"
    }
}

# ============================================================================
# Task entfernen
# ============================================================================

Write-Host ""
Write-Info "Entferne Task '$TaskName'..."

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Success "Task erfolgreich entfernt!"
}
catch {
    Write-Err "Fehler beim Entfernen des Tasks: $_"
    exit 1
}

# ============================================================================
# Prozess beenden (optional)
# ============================================================================

if ($StopProcess) {
    Write-Host ""
    Write-Info "Suche laufende PaperCut Client Prozesse..."
    
    $processes = Get-Process -Name "pc-client" -ErrorAction SilentlyContinue
    
    if ($processes) {
        Write-Warn "Beende $($processes.Count) PaperCut Client Prozess(e)..."
        
        foreach ($proc in $processes) {
            try {
                Stop-Process -Id $proc.Id -Force
                Write-Success "Prozess $($proc.Id) beendet"
            }
            catch {
                Write-Err "Prozess $($proc.Id) konnte nicht beendet werden: $_"
            }
        }
    }
    else {
        Write-Info "Keine laufenden PaperCut Client Prozesse gefunden."
    }
}

# ============================================================================
# Zusammenfassung
# ============================================================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Deinstallation abgeschlossen!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Der PaperCut Client wird nicht mehr automatisch beim Systemstart gestartet."
Write-Host ""
Write-Host "Zum erneuten Einrichten führen Sie aus:"
Write-Host "  .\setup_papercut_autostart.ps1"
Write-Host ""
