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
    
    Unterstützt sowohl lokale als auch Domain-User:
    - Lokal: username oder .\username
    - Domain: DOMAIN\username oder username@domain.com

.PARAMETER ServiceUser
    Der Windows-User unter dem der Service läuft.
    Formate:
      - Lokal: username, .\username
      - Domain: DOMAIN\username, username@domain.com
    Standard: skriptendruck-service (lokal)

.PARAMETER ServicePassword
    Das Passwort für den Service-User.
    Wird interaktiv abgefragt wenn nicht angegeben.

.PARAMETER Port
    Der Port auf dem das Dashboard lauscht.
    Standard: 8000

.EXAMPLE
    .\install_service.ps1
    # Interaktive Eingabe mit Standardwerten

.EXAMPLE
    .\install_service.ps1 -ServiceUser "myuser" -Port 8080
    # Lokaler User mit angepasstem Port

.EXAMPLE
    .\install_service.ps1 -ServiceUser "DOMAIN\serviceaccount"
    # Domain-User

.EXAMPLE
    .\install_service.ps1 -ServiceUser "serviceaccount@domain.local"
    # Domain-User im UPN-Format
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
# User-Typ Erkennung
# ============================================

# Enum für User-Typ
$script:UserType = @{
    Local = "Local"
    Domain = "Domain"
}

function Get-UserTypeFromInput {
    <#
    .SYNOPSIS
        Erkennt den User-Typ aus dem eingegebenen Benutzernamen.
    .OUTPUTS
        Hashtable mit Type, Username, Domain, NssmFormat
    #>
    param([string]$InputUser)
    
    $result = @{
        Type = $script:UserType.Local
        Username = $InputUser
        Domain = $null
        NssmFormat = $null
        OriginalInput = $InputUser
    }
    
    # Fall 1: DOMAIN\username Format
    if ($InputUser -match '^([^\\@]+)\\(.+)$') {
        $domain = $Matches[1]
        $username = $Matches[2]
        
        # Prüfe ob es .\ (lokaler User) ist
        if ($domain -eq ".") {
            $result.Type = $script:UserType.Local
            $result.Username = $username
            $result.Domain = "."
            $result.NssmFormat = ".\$username"
        } else {
            $result.Type = $script:UserType.Domain
            $result.Username = $username
            $result.Domain = $domain
            $result.NssmFormat = "$domain\$username"
        }
    }
    # Fall 2: username@domain.com Format (UPN)
    elseif ($InputUser -match '^([^@]+)@(.+)$') {
        $username = $Matches[1]
        $domain = $Matches[2]
        
        # UPN wird zu DOMAIN\user konvertiert für NSSM
        $result.Type = $script:UserType.Domain
        $result.Username = $username
        $result.Domain = $domain
        # Für NSSM verwenden wir das UPN Format direkt
        $result.NssmFormat = $InputUser
    }
    # Fall 3: Nur username - könnte lokal oder Domain sein
    else {
        $result.Type = $script:UserType.Local  # Default, wird ggf. interaktiv geändert
        $result.Username = $InputUser
        $result.Domain = "."
        $result.NssmFormat = ".\$InputUser"
    }
    
    return $result
}

function Resolve-UserInput {
    <#
    .SYNOPSIS
        Löst einen Benutzernamen auf und fragt ggf. nach Local/Domain.
    #>
    param([string]$InputUser)
    
    $userInfo = Get-UserTypeFromInput -InputUser $InputUser
    
    # Wenn nur ein einfacher Username (ohne Domain/.\), frage nach
    if (-not ($InputUser -match '\\') -and -not ($InputUser -match '@')) {
        Write-Host ""
        Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Yellow
        Write-Host "║  User-Typ für '$InputUser' auswählen:" -ForegroundColor Yellow
        Write-Host "╠════════════════════════════════════════════════════════════════╣" -ForegroundColor Yellow
        Write-Host "║  [L] Lokaler User        (.\$InputUser)" -ForegroundColor Yellow
        Write-Host "║  [D] Domain-User         ($env:USERDOMAIN\$InputUser)" -ForegroundColor Yellow
        Write-Host "║  [A] Anderer User/Format (manuell eingeben)" -ForegroundColor Yellow
        Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Aktuelle Domain: $env:USERDOMAIN" -ForegroundColor Cyan
        Write-Host "Aktueller Computer: $env:COMPUTERNAME" -ForegroundColor Cyan
        Write-Host ""
        
        $choice = Read-Host "Auswahl [L/D/A] (Standard: L)"
        
        switch ($choice.ToUpper()) {
            "D" {
                $userInfo.Type = $script:UserType.Domain
                $userInfo.Domain = $env:USERDOMAIN
                $userInfo.NssmFormat = "$env:USERDOMAIN\$InputUser"
                Write-Host "→ Domain-User: $($userInfo.NssmFormat)" -ForegroundColor Green
            }
            "A" {
                Write-Host ""
                Write-Host "Gib den vollständigen Benutzernamen ein:" -ForegroundColor Yellow
                Write-Host "  Beispiele:" -ForegroundColor Gray
                Write-Host "    - Lokal:  .\serviceuser" -ForegroundColor Gray
                Write-Host "    - Domain: DOMAIN\serviceuser" -ForegroundColor Gray
                Write-Host "    - UPN:    serviceuser@domain.local" -ForegroundColor Gray
                $customUser = Read-Host "Benutzername"
                
                if ([string]::IsNullOrWhiteSpace($customUser)) {
                    Write-Host "Keine Eingabe, verwende lokalen User." -ForegroundColor Yellow
                } else {
                    $userInfo = Get-UserTypeFromInput -InputUser $customUser
                }
                Write-Host "→ $($userInfo.Type) User: $($userInfo.NssmFormat)" -ForegroundColor Green
            }
            default {
                # L oder leer = Lokal
                $userInfo.Type = $script:UserType.Local
                $userInfo.Domain = "."
                $userInfo.NssmFormat = ".\$InputUser"
                Write-Host "→ Lokaler User: $($userInfo.NssmFormat)" -ForegroundColor Green
            }
        }
    }
    
    return $userInfo
}

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

function Write-Warning {
    param([string]$Text)
    Write-Host "[!] $Text" -ForegroundColor DarkYellow
}

function Write-ErrorMsg {
    param([string]$Text)
    Write-Host "[✗] $Text" -ForegroundColor Red
}

function Test-ServiceExists {
    param([string]$Name)
    $service = Get-Service -Name $Name -ErrorAction SilentlyContinue
    return $null -ne $service
}

function Test-LocalUserExists {
    <#
    .SYNOPSIS
        Prüft ob ein lokaler User existiert.
    #>
    param([string]$Username)
    
    try {
        $user = Get-LocalUser -Name $Username -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Test-DomainUserExists {
    <#
    .SYNOPSIS
        Prüft ob ein Domain-User existiert (falls AD-Module verfügbar).
    #>
    param(
        [string]$Username,
        [string]$Domain
    )
    
    # Prüfe ob AD-Modul verfügbar ist
    $adModuleAvailable = $false
    try {
        if (Get-Module -ListAvailable -Name ActiveDirectory) {
            Import-Module ActiveDirectory -ErrorAction Stop
            $adModuleAvailable = $true
        }
    } catch {
        # AD-Modul nicht verfügbar
    }
    
    if (-not $adModuleAvailable) {
        Write-Warning "Active Directory PowerShell-Modul nicht verfügbar."
        Write-Host "         Domain-User kann nicht validiert werden." -ForegroundColor DarkYellow
        Write-Host "         Installation: Install-WindowsFeature RSAT-AD-PowerShell" -ForegroundColor Gray
        Write-Host "         oder: Add-WindowsCapability -Online -Name Rsat.ActiveDirectory.DS-LDS.Tools*" -ForegroundColor Gray
        return $null  # Unbekannt
    }
    
    try {
        # Versuche User in AD zu finden
        $adUser = Get-ADUser -Identity $Username -Server $Domain -ErrorAction Stop
        return $true
    } catch [Microsoft.ActiveDirectory.Management.ADIdentityNotFoundException] {
        return $false
    } catch {
        Write-Warning "AD-Abfrage fehlgeschlagen: $_"
        return $null  # Unbekannt
    }
}

function Test-UserExists {
    <#
    .SYNOPSIS
        Prüft ob der angegebene User existiert (lokal oder Domain).
    .OUTPUTS
        $true = existiert, $false = existiert nicht, $null = konnte nicht geprüft werden
    #>
    param([hashtable]$UserInfo)
    
    if ($UserInfo.Type -eq $script:UserType.Local) {
        return Test-LocalUserExists -Username $UserInfo.Username
    } else {
        return Test-DomainUserExists -Username $UserInfo.Username -Domain $UserInfo.Domain
    }
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
        Write-ErrorMsg "NSSM Download fehlgeschlagen. Bitte manuell herunterladen von: https://nssm.cc/download"
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
        Write-ErrorMsg "nssm.exe nicht im Download gefunden!"
        throw "NSSM Installation fehlgeschlagen"
    }
    
    Copy-Item -Path $NssmSource.FullName -Destination $NssmExe -Force
    
    # Cleanup
    Remove-Item -Path $ZipPath -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $ExtractPath -Recurse -Force -ErrorAction SilentlyContinue
    
    Write-Success "NSSM installiert: $NssmExe"
}

function Test-Prerequisites {
    param([hashtable]$UserInfo)
    
    Write-Header "Voraussetzungen prüfen"
    
    # Python venv prüfen
    Write-Step "Prüfe Virtual Environment..."
    if (-not (Test-Path $PythonExe)) {
        Write-ErrorMsg "Python venv nicht gefunden: $VenvPath"
        Write-Host "  Bitte zuerst ausführen: Skriptendruck_Setup.ps1"
        throw "Virtual Environment nicht vorhanden"
    }
    Write-Success "Python venv gefunden: $PythonExe"
    
    # Service-User prüfen
    Write-Step "Prüfe Service-User '$($UserInfo.NssmFormat)'..."
    
    $userExists = Test-UserExists -UserInfo $UserInfo
    
    if ($userExists -eq $true) {
        Write-Success "Service-User '$($UserInfo.NssmFormat)' existiert"
    } elseif ($userExists -eq $false) {
        if ($UserInfo.Type -eq $script:UserType.Local) {
            Write-ErrorMsg "Lokaler User '$($UserInfo.Username)' nicht gefunden!"
            Write-Host "  Bitte zuerst anlegen:" -ForegroundColor Gray
            Write-Host '  $Password = Read-Host -AsSecureString "Passwort"' -ForegroundColor Gray
            Write-Host "  New-LocalUser -Name '$($UserInfo.Username)' -Password `$Password -PasswordNeverExpires" -ForegroundColor Gray
            throw "Service-User nicht vorhanden"
        } else {
            Write-ErrorMsg "Domain-User '$($UserInfo.NssmFormat)' nicht gefunden!"
            Write-Host "  Bitte Active Directory prüfen oder User-Eingabe korrigieren." -ForegroundColor Gray
            throw "Service-User nicht vorhanden"
        }
    } else {
        # $null = konnte nicht geprüft werden
        Write-Warning "User-Existenz konnte nicht geprüft werden (AD-Modul fehlt)."
        Write-Host ""
        Write-Host "Möchtest du trotzdem fortfahren? [J/N] " -ForegroundColor Yellow -NoNewline
        $continue = Read-Host
        if ($continue.ToUpper() -ne "J") {
            throw "Installation durch Benutzer abgebrochen"
        }
    }
    
    # .env prüfen
    Write-Step "Prüfe .env Datei..."
    $envFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path $envFile)) {
        Write-ErrorMsg ".env Datei nicht gefunden!"
        Write-Host "  Bitte .env.example kopieren und anpassen"
        throw ".env Datei fehlt"
    }
    Write-Success ".env Datei vorhanden"
}

function Get-ServicePassword {
    param([hashtable]$UserInfo)
    
    if ($ServicePassword) {
        return $ServicePassword
    }
    
    Write-Host ""
    Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Yellow
    Write-Host "║  Passwort für Service-User eingeben" -ForegroundColor Yellow
    Write-Host "╠════════════════════════════════════════════════════════════════╣" -ForegroundColor Yellow
    Write-Host "║  User: $($UserInfo.NssmFormat)" -ForegroundColor Yellow
    Write-Host "║  Typ:  $($UserInfo.Type)" -ForegroundColor Yellow
    Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Yellow
    Write-Host ""
    $password = Read-Host -AsSecureString "Passwort"
    return $password
}

function Install-DashboardService {
    param([hashtable]$UserInfo)
    
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
        Write-ErrorMsg "Service-Installation fehlgeschlagen!"
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
    $password = Get-ServicePassword -UserInfo $UserInfo
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
    $PlainPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)
    
    # User-Format für NSSM (bereits korrekt formatiert in UserInfo.NssmFormat)
    & $NssmExe set $ServiceName ObjectName $UserInfo.NssmFormat $PlainPassword
    
    # Passwort aus Speicher löschen
    $PlainPassword = $null
    [GC]::Collect()
    
    Write-Success "Service '$ServiceName' installiert"
}

function Grant-LogonAsService {
    param([hashtable]$UserInfo)
    
    Write-Step "Gewähre 'Anmelden als Dienst' Recht..."
    
    # Für Domain-User das vollständige Format verwenden
    $userForPolicy = $UserInfo.NssmFormat
    
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
        # Escapen von Backslash für Regex
        $escapedUser = [regex]::Escape($userForPolicy)
        if ($content[$lineIndex] -notmatch $escapedUser) {
            $content[$lineIndex] = $content[$lineIndex] + ",$userForPolicy"
        }
    } else {
        # Zeile hinzufügen
        $content += "SeServiceLogonRight = $userForPolicy"
    }
    
    # Schreibe zurück
    $content | Set-Content $TempFile
    
    # Importiere Policy
    secedit /configure /db secedit.sdb /cfg $TempFile /quiet 2>$null
    
    # Cleanup
    Remove-Item $TempFile -Force -ErrorAction SilentlyContinue
    Remove-Item "secedit.sdb" -Force -ErrorAction SilentlyContinue
    
    Write-Success "Berechtigung erteilt für: $userForPolicy"
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
        Write-ErrorMsg "Service konnte nicht gestartet werden!"
        Write-Host "  Logs prüfen: $LogDir\service_stderr.log"
        Write-Host "  Status: nssm status $ServiceName"
    }
}

function Show-Summary {
    param([hashtable]$UserInfo)
    
    Write-Header "Zusammenfassung"
    
    Write-Host "Service-Name:    $ServiceName"
    Write-Host "Service-User:    $($UserInfo.NssmFormat)"
    Write-Host "User-Typ:        $($UserInfo.Type)"
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

function Show-InstallConfirmation {
    param([hashtable]$UserInfo)
    
    Write-Host ""
    Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║  Installation wird durchgeführt mit folgenden Einstellungen:" -ForegroundColor Cyan
    Write-Host "╠════════════════════════════════════════════════════════════════╣" -ForegroundColor Cyan
    Write-Host "║  Service-Name:  $ServiceName" -ForegroundColor Cyan
    Write-Host "║  Service-User:  $($UserInfo.NssmFormat)" -ForegroundColor Cyan
    Write-Host "║  User-Typ:      $($UserInfo.Type)" -ForegroundColor Cyan
    Write-Host "║  Port:          $Port" -ForegroundColor Cyan
    Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Fortfahren? [J/N] " -ForegroundColor Yellow -NoNewline
    $confirm = Read-Host
    if ($confirm.ToUpper() -ne "J") {
        Write-Host "Installation abgebrochen." -ForegroundColor Yellow
        exit 0
    }
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
    # User-Info ermitteln
    $UserInfo = Resolve-UserInput -InputUser $ServiceUser
    
    # Bestätigung anzeigen
    Show-InstallConfirmation -UserInfo $UserInfo
    
    Test-Prerequisites -UserInfo $UserInfo
    Install-NSSM
    Grant-LogonAsService -UserInfo $UserInfo
    Install-DashboardService -UserInfo $UserInfo
    Start-DashboardService
    Show-Summary -UserInfo $UserInfo
    
    Write-Host ""
    Write-Success "Installation erfolgreich abgeschlossen!"
    
} catch {
    Write-Host ""
    Write-ErrorMsg "Installation fehlgeschlagen: $_"
    exit 1
}
