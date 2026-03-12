<#
.SYNOPSIS
    Konfiguriert PaperCut Client für automatischen Start beim Systemstart.

.DESCRIPTION
    Erstellt einen Windows Task Scheduler Task, der den PaperCut Client (pcclient.exe)
    automatisch beim Systemstart startet. Der Task wird unter einem konfigurierbaren
    Benutzer ausgeführt.

.PARAMETER ServiceUser
    Der Windows-Benutzer, unter dem pcclient laufen soll.
    Standard: .\skriptendruck-service

.PARAMETER ServicePassword
    Das Passwort für den Service-Benutzer.
    Wird interaktiv abgefragt, wenn nicht angegeben.

.PARAMETER PaperCutPath
    Optionaler Pfad zu pcclient.exe.
    Standard: Automatische Suche in bekannten Verzeichnissen.

.PARAMETER TaskName
    Name des Task Scheduler Tasks.
    Standard: "PaperCut Client Autostart"

.EXAMPLE
    .\setup_papercut_autostart.ps1
    
.EXAMPLE
    .\setup_papercut_autostart.ps1 -ServiceUser ".\print-user" -PaperCutPath "D:\PaperCut\pc-client.exe"

.NOTES
    Erfordert Administrator-Rechte.
    Erstellt von: FSMB Regensburg
    Datum: 2026-03
#>

param(
    [string]$ServiceUser = ".\skriptendruck-service",
    [string]$ServicePassword = "",
    [string]$PaperCutPath = "",
    [string]$TaskName = "PaperCut Client Autostart"
)

# ============================================================================
# Konfiguration
# ============================================================================

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "PaperCut Client Autostart Setup"

# Farben für Ausgabe
function Write-Success { param($msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Warn { param($msg) Write-Host "[WARNUNG] $msg" -ForegroundColor Yellow }
function Write-Err { param($msg) Write-Host "[FEHLER] $msg" -ForegroundColor Red }

# ============================================================================
# Administrator-Check
# ============================================================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  PaperCut Client Autostart Setup" -ForegroundColor Cyan
Write-Host "  FSMB Regensburg - Skriptendruck" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Err "Dieses Skript erfordert Administrator-Rechte!"
    Write-Host "Bitte starten Sie PowerShell als Administrator und führen Sie das Skript erneut aus."
    exit 1
}

Write-Success "Administrator-Rechte vorhanden"

# ============================================================================
# PaperCut Client finden
# ============================================================================

Write-Host ""
Write-Info "Suche PaperCut Client..."

$searchPaths = @(
    "C:\Program Files\PaperCut NG\client\pc-client.exe",
    "C:\Program Files\PaperCut NG\client\win\pc-client.exe",
    "C:\Program Files\PaperCut NG\pcclient.exe",
    "C:\Program Files\PaperCut MF\client\pc-client.exe",
    "C:\Program Files\PaperCut MF\client\win\pc-client.exe",
    "C:\Program Files (x86)\PaperCut NG\client\pc-client.exe",
    "C:\Program Files (x86)\PaperCut NG\client\win\pc-client.exe",
    "C:\Program Files (x86)\PaperCut MF\client\pc-client.exe",
    "C:\PaperCut NG\client\pc-client.exe",
    "C:\PaperCut MF\client\pc-client.exe"
)

$foundPath = ""

# Falls Pfad manuell angegeben wurde
if ($PaperCutPath -ne "" -and (Test-Path $PaperCutPath)) {
    $foundPath = $PaperCutPath
    Write-Success "Manuell angegebener Pfad gefunden: $foundPath"
}
else {
    # Automatische Suche
    foreach ($path in $searchPaths) {
        if (Test-Path $path) {
            $foundPath = $path
            Write-Success "PaperCut Client gefunden: $foundPath"
            break
        }
    }
    
    # Erweiterte Suche mit Get-ChildItem
    if ($foundPath -eq "") {
        Write-Info "Starte erweiterte Suche..."
        
        $extendedSearch = Get-ChildItem -Path "C:\Program Files*" -Recurse -Filter "pc-client.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        
        if ($extendedSearch) {
            $foundPath = $extendedSearch.FullName
            Write-Success "PaperCut Client gefunden (erweiterte Suche): $foundPath"
        }
    }
}

if ($foundPath -eq "") {
    Write-Err "PaperCut Client (pc-client.exe) konnte nicht gefunden werden!"
    Write-Host ""
    Write-Host "Bitte geben Sie den Pfad manuell an:" -ForegroundColor Yellow
    Write-Host '  .\setup_papercut_autostart.ps1 -PaperCutPath "C:\Pfad\zu\pc-client.exe"'
    Write-Host ""
    Write-Host "Typische Installationsorte:"
    foreach ($path in $searchPaths | Select-Object -First 5) {
        Write-Host "  - $path"
    }
    exit 1
}

# ============================================================================
# Benutzer-Credentials
# ============================================================================

Write-Host ""
Write-Info "Konfiguriere Service-Benutzer: $ServiceUser"

if ($ServicePassword -eq "") {
    Write-Host ""
    Write-Warn "Passwort für '$ServiceUser' wird benötigt."
    $securePassword = Read-Host "Passwort eingeben" -AsSecureString
    $ServicePassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword))
}

if ($ServicePassword -eq "") {
    Write-Err "Kein Passwort angegeben. Abbruch."
    exit 1
}

# ============================================================================
# Bestehenden Task prüfen und entfernen
# ============================================================================

Write-Host ""
Write-Info "Prüfe auf bestehenden Task '$TaskName'..."

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Write-Warn "Task '$TaskName' existiert bereits."
    $confirm = Read-Host "Möchten Sie den bestehenden Task überschreiben? (j/n)"
    
    if ($confirm -eq "j" -or $confirm -eq "J" -or $confirm -eq "y" -or $confirm -eq "Y") {
        Write-Info "Entferne bestehenden Task..."
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Success "Bestehender Task entfernt"
    }
    else {
        Write-Info "Setup abgebrochen."
        exit 0
    }
}

# ============================================================================
# Task Scheduler Task erstellen
# ============================================================================

Write-Host ""
Write-Info "Erstelle Task Scheduler Task..."

try {
    # Action: PaperCut Client starten
    $action = New-ScheduledTaskAction -Execute $foundPath
    
    # Trigger: Bei Systemstart
    $trigger = New-ScheduledTaskTrigger -AtStartup
    
    # Principal: Als angegebener Benutzer ausführen
    $principal = New-ScheduledTaskPrincipal -UserId $ServiceUser -LogonType Password -RunLevel Limited
    
    # Settings: Konfiguration
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -RestartCount 3 `
        -ExecutionTimeLimit (New-TimeSpan -Days 0) `
        -MultipleInstances IgnoreNew
    
    # Task registrieren
    $task = Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -User $ServiceUser `
        -Password $ServicePassword `
        -Description "Startet den PaperCut Client automatisch beim Systemstart für die Druckabrechnung. Konfiguriert von Skriptendruck Setup."
    
    Write-Success "Task '$TaskName' erfolgreich erstellt!"
    
}
catch {
    Write-Err "Fehler beim Erstellen des Tasks: $_"
    exit 1
}

# ============================================================================
# Task testen
# ============================================================================

Write-Host ""
$testTask = Read-Host "Möchten Sie den Task jetzt testen und PaperCut Client starten? (j/n)"

if ($testTask -eq "j" -or $testTask -eq "J" -or $testTask -eq "y" -or $testTask -eq "Y") {
    Write-Info "Starte Task '$TaskName'..."
    
    try {
        Start-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 3
        
        # Prüfen ob pcclient läuft
        $process = Get-Process -Name "pc-client" -ErrorAction SilentlyContinue
        
        if ($process) {
            Write-Success "PaperCut Client läuft! (PID: $($process.Id))"
        }
        else {
            Write-Warn "PaperCut Client-Prozess nicht gefunden. Überprüfen Sie die Task-Konfiguration."
        }
    }
    catch {
        Write-Err "Fehler beim Starten des Tasks: $_"
    }
}

# ============================================================================
# Zusammenfassung
# ============================================================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Setup abgeschlossen!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Task-Details:"
Write-Host "  Name:        $TaskName"
Write-Host "  Benutzer:    $ServiceUser"
Write-Host "  Programm:    $foundPath"
Write-Host "  Trigger:     Systemstart"
Write-Host ""
Write-Host "Nächste Schritte:"
Write-Host "  1. Überprüfen Sie den Task im Task Scheduler (taskschd.msc)"
Write-Host "  2. Testen Sie einen Neustart des Systems"
Write-Host "  3. Überprüfen Sie die PaperCut-Abrechnung"
Write-Host ""
Write-Host "Zum Entfernen des Tasks führen Sie aus:"
Write-Host "  .\remove_papercut_autostart.ps1"
Write-Host ""
