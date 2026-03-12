#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Installiert das Skriptendruck-Dashboard als Windows-Service via NSSM.

.DESCRIPTION
    Dieses Skript:
    - Lädt NSSM herunter (falls nicht vorhanden)
    - Installiert den Service "SkriptendruckDashboard"
    - Konfiguriert den Service für Auto-Start und Restart bei Fehler
    - Startet den Service

.PARAMETER ServiceUser
    Der lokale Windows-User unter dem der Service läuft.
    Standard: skriptendruck-service

.PARAMETER ServicePassword
    Das Passwort für den Service-User.
    Wird interaktiv abgefragt wenn nicht angegeben.

.PARAMETER Port
    Der Port auf dem das Dashboard lauscht.
    Standard: 8000

.EXAMPLE
    .\install_service.ps1

.EXAMPLE
    .\install_service.ps1 -ServiceUser "myuser" -Port 8080
#>

param(
    [string]$ServiceUser = "skriptendruck-service",
    [SecureString]$ServicePassword,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

# ============================================
# Konfiguration
# ============================================
$ServiceName = "SkriptendruckDashboard"
$ServiceDisplayName = "Skriptendruck Dashboard"
$ServiceDescription = "Web-Dashboard für das Skriptendruck-System der FSMB Regensburg"
$ProjectRoot = $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$NssmDir = Join-Path $ProjectRoot "tools\nssm"
$NssmExe = Join-Path $NssmDir "nssm.exe"
$NssmDownloadUrl = "https://nssm.cc/release/nssm-2.24.zip"
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

function Install-NSSM {
    Write-Header "NSSM Installation"
    
    if (Test-Path $NssmExe) {
        Write-Success "NSSM bereits vorhanden: $NssmExe"
        return
    }
    
    Write-Step "Erstelle tools-Verzeichnis..."
    New-Item -ItemType Directory -Path $NssmDir -Force | Out-Null
    
    Write-Step "Lade NSSM herunter..."
    $ZipPath = Join-Path $env:TEMP "nssm.zip"
    
    try {
        Invoke-WebRequest -Uri $NssmDownloadUrl -OutFile $ZipPath -UseBasicParsing
    } catch {
        Write-Error "NSSM Download fehlgeschlagen. Bitte manuell herunterladen von: https://nssm.cc/download"
        throw
    }
    
    Write-Step "Entpacke NSSM..."
    $ExtractPath = Join-Path $env:TEMP "nssm_extract"
    Expand-Archive -Path $ZipPath -DestinationPath $ExtractPath -Force
    
    # Finde die richtige nssm.exe (64-bit bevorzugt)
    $NssmSource = Get-ChildItem -Path $ExtractPath -Recurse -Filter "nssm.exe" | 
                  Where-Object { $_.Directory.Name -eq "win64" } | 
                  Select-Object -First 1
    
    if (-not $NssmSource) {
        $NssmSource = Get-ChildItem -Path $ExtractPath -Recurse -Filter "nssm.exe" | 
                      Select-Object -First 1
    }
    
    if (-not $NssmSource) {
        Write-Error "nssm.exe nicht im Download gefunden!"
        throw "NSSM Installation fehlgeschlagen"
    }
    
    Copy-Item -Path $NssmSource.FullName -Destination $NssmExe -Force
    
    # Cleanup
    Remove-Item -Path $ZipPath -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $ExtractPath -Recurse -Force -ErrorAction SilentlyContinue
    
    Write-Success "NSSM installiert: $NssmExe"
}

function Test-Prerequisites {
    Write-Header "Voraussetzungen prüfen"
    
    # Python venv prüfen
    Write-Step "Prüfe Virtual Environment..."
    if (-not (Test-Path $PythonExe)) {
        Write-Error "Python venv nicht gefunden: $VenvPath"
        Write-Host "  Bitte zuerst ausführen: Skriptendruck_Setup.ps1"
        throw "Virtual Environment nicht vorhanden"
    }
    Write-Success "Python venv gefunden: $PythonExe"
    
    # Service-User prüfen
    Write-Step "Prüfe Service-User '$ServiceUser'..."
    $user = Get-LocalUser -Name $ServiceUser -ErrorAction SilentlyContinue
    if (-not $user) {
        Write-Error "Lokaler User '$ServiceUser' nicht gefunden!"
        Write-Host "  Bitte zuerst anlegen:"
        Write-Host '  $Password = Read-Host -AsSecureString "Passwort"'
        Write-Host "  New-LocalUser -Name '$ServiceUser' -Password `$Password -PasswordNeverExpires"
        throw "Service-User nicht vorhanden"
    }
    Write-Success "Service-User '$ServiceUser' existiert"
    
    # .env prüfen
    Write-Step "Prüfe .env Datei..."
    $envFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path $envFile)) {
        Write-Error ".env Datei nicht gefunden!"
        Write-Host "  Bitte .env.example kopieren und anpassen"
        throw ".env Datei fehlt"
    }
    Write-Success ".env Datei vorhanden"
}

function Get-ServicePassword {
    if ($ServicePassword) {
        return $ServicePassword
    }
    
    Write-Host ""
    Write-Host "Passwort für Service-User '$ServiceUser' eingeben:" -ForegroundColor Yellow
    $password = Read-Host -AsSecureString
    return $password
}

function Install-DashboardService {
    Write-Header "Service Installation"
    
    # Prüfen ob Service bereits existiert
    if (Test-ServiceExists -Name $ServiceName) {
        Write-Step "Service existiert bereits, wird entfernt..."
        & $NssmExe stop $ServiceName 2>$null
        & $NssmExe remove $ServiceName confirm
        Start-Sleep -Seconds 2
    }
    
    # Log-Verzeichnis erstellen
    Write-Step "Erstelle Log-Verzeichnis..."
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    
    # Service installieren
    Write-Step "Installiere Service '$ServiceName'..."
    
    $AppArguments = "-m uvicorn skriptendruck.web.app:app --host 0.0.0.0 --port $Port --app-dir src"
    
    & $NssmExe install $ServiceName $PythonExe $AppArguments
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Service-Installation fehlgeschlagen!"
        throw "NSSM install failed"
    }
    
    # Service konfigurieren
    Write-Step "Konfiguriere Service..."
    
    # Anzeigename und Beschreibung
    & $NssmExe set $ServiceName DisplayName $ServiceDisplayName
    & $NssmExe set $ServiceName Description $ServiceDescription
    
    # Arbeitsverzeichnis
    & $NssmExe set $ServiceName AppDirectory $ProjectRoot
    
    # Umgebungsvariablen (für .env Laden)
    & $NssmExe set $ServiceName AppEnvironmentExtra "PYTHONUNBUFFERED=1"
    
    # Logging
    $StdoutLog = Join-Path $LogDir "service_stdout.log"
    $StderrLog = Join-Path $LogDir "service_stderr.log"
    & $NssmExe set $ServiceName AppStdout $StdoutLog
    & $NssmExe set $ServiceName AppStderr $StderrLog
    & $NssmExe set $ServiceName AppStdoutCreationDisposition 4  # Append
    & $NssmExe set $ServiceName AppStderrCreationDisposition 4  # Append
    & $NssmExe set $ServiceName AppRotateFiles 1
    & $NssmExe set $ServiceName AppRotateBytes 10485760  # 10 MB
    
    # Startup-Typ: Automatisch
    & $NssmExe set $ServiceName Start SERVICE_AUTO_START
    
    # Restart bei Fehler
    & $NssmExe set $ServiceName AppExit Default Restart
    & $NssmExe set $ServiceName AppRestartDelay 5000  # 5 Sekunden
    
    # Service-Account konfigurieren
    Write-Step "Konfiguriere Service-Account..."
    $password = Get-ServicePassword
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
    $PlainPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)
    
    # Lokaler User: .\username Format
    $FullUserName = ".\$ServiceUser"
    & $NssmExe set $ServiceName ObjectName $FullUserName $PlainPassword
    
    # Passwort aus Speicher löschen
    $PlainPassword = $null
    [GC]::Collect()
    
    Write-Success "Service '$ServiceName' installiert"
}

function Grant-LogonAsService {
    Write-Step "Gewähre 'Anmelden als Dienst' Recht..."
    
    # Exportiere aktuelle Security-Policy
    $TempFile = Join-Path $env:TEMP "secpol.cfg"
    secedit /export /cfg $TempFile /quiet
    
    # Lese Datei
    $content = Get-Content $TempFile
    
    # Finde SeServiceLogonRight Zeile
    $lineIndex = -1
    for ($i = 0; $i -lt $content.Count; $i++) {
        if ($content[$i] -match "^SeServiceLogonRight") {
            $lineIndex = $i
            break
        }
    }
    
    if ($lineIndex -ge 0) {
        # User hinzufügen wenn nicht vorhanden
        if ($content[$lineIndex] -notmatch $ServiceUser) {
            $content[$lineIndex] = $content[$lineIndex] + ",$ServiceUser"
        }
    } else {
        # Zeile hinzufügen
        $content += "SeServiceLogonRight = $ServiceUser"
    }
    
    # Schreibe zurück
    $content | Set-Content $TempFile
    
    # Importiere Policy
    secedit /configure /db secedit.sdb /cfg $TempFile /quiet 2>$null
    
    # Cleanup
    Remove-Item $TempFile -Force -ErrorAction SilentlyContinue
    Remove-Item "secedit.sdb" -Force -ErrorAction SilentlyContinue
    
    Write-Success "Berechtigung erteilt"
}

function Start-DashboardService {
    Write-Header "Service starten"
    
    Write-Step "Starte Service '$ServiceName'..."
    & $NssmExe start $ServiceName
    
    Start-Sleep -Seconds 3
    
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service -and $service.Status -eq "Running") {
        Write-Success "Service läuft!"
        Write-Host ""
        Write-Host "Dashboard erreichbar unter: http://localhost:$Port" -ForegroundColor Green
        Write-Host "  oder: http://$(hostname):$Port" -ForegroundColor Green
    } else {
        Write-Error "Service konnte nicht gestartet werden!"
        Write-Host "  Logs prüfen: $LogDir\service_stderr.log"
        Write-Host "  Status: nssm status $ServiceName"
    }
}

function Show-Summary {
    Write-Header "Zusammenfassung"
    
    Write-Host "Service-Name:    $ServiceName"
    Write-Host "Service-User:    .\$ServiceUser"
    Write-Host "Port:            $Port"
    Write-Host "Projekt-Root:    $ProjectRoot"
    Write-Host "Log-Verzeichnis: $LogDir"
    Write-Host ""
    Write-Host "Nützliche Befehle:" -ForegroundColor Yellow
    Write-Host "  Status:    $NssmExe status $ServiceName"
    Write-Host "  Stoppen:   $NssmExe stop $ServiceName"
    Write-Host "  Starten:   $NssmExe start $ServiceName"
    Write-Host "  Neustarten: $NssmExe restart $ServiceName"
    Write-Host "  Logs:      Get-Content '$LogDir\service_stderr.log' -Tail 50"
}

# ============================================
# Hauptprogramm
# ============================================

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     Skriptendruck Dashboard - Windows Service Installation    ║" -ForegroundColor Cyan
Write-Host "║                    FSMB Regensburg e.V.                       ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan

try {
    Test-Prerequisites
    Install-NSSM
    Grant-LogonAsService
    Install-DashboardService
    Start-DashboardService
    Show-Summary
    
    Write-Host ""
    Write-Success "Installation erfolgreich abgeschlossen!"
    
} catch {
    Write-Host ""
    Write-Error "Installation fehlgeschlagen: $_"
    exit 1
}
