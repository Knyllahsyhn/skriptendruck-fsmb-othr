# Windows-Service Setup – Skriptendruck Dashboard

Diese Anleitung beschreibt, wie das Skriptendruck-Dashboard als **Windows-Service** eingerichtet wird, damit es automatisch beim Serverstart läuft und alle Druckaufträge unter dem Service-Account `skriptendruck-service` ausgeführt werden.

## Übersicht

```
┌─────────────────────────────────────────────────────────────────┐
│                    Windows Server                                │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Service: SkriptendruckDashboard              │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  User: .\skriptendruck-service                     │  │  │
│  │  │  App:  uvicorn skriptendruck.web.app:app           │  │  │
│  │  │  Port: 8000                                        │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  │                         │                                 │  │
│  │                         ▼                                 │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  Drucker (via SumatraPDF)                          │  │  │
│  │  │  → PaperCut ordnet Aufträge automatisch            │  │  │
│  │  │    dem User "skriptendruck-service" zu             │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Voraussetzungen

### 1. Python-Umgebung

Das Projekt muss bereits eingerichtet sein:

```powershell
# Virtual Environment und Dependencies installieren
.\Skriptendruck_Setup.ps1
```

### 2. Service-Account anlegen

Ein Windows-User wird benötigt, unter dem der Service läuft. Das kann ein **lokaler User** oder ein **Domain-User** sein.

#### Option A: Lokaler User (Standard)

```powershell
# Als Administrator ausführen
$Password = Read-Host -AsSecureString "Passwort für skriptendruck-service"
New-LocalUser -Name "skriptendruck-service" `
              -Password $Password `
              -Description "Service-Account für Skriptendruck-Dashboard" `
              -PasswordNeverExpires

# User zur Users-Gruppe hinzufügen
Add-LocalGroupMember -Group "Users" -Member "skriptendruck-service"
```

#### Option B: Domain-User

Wenn ein Domain-User verwendet werden soll (z.B. für zentrale Verwaltung oder spezielle Berechtigungen):

1. **User in Active Directory anlegen** (durch AD-Administrator)
2. **Berechtigungen vergeben:**
   - Zugriff auf das Projektverzeichnis
   - Zugriff auf die Drucker
   - Ggf. Zugriff auf Netzlaufwerke

**Unterstützte Formate:**
| Format | Beispiel | Beschreibung |
|--------|----------|--------------|
| `DOMAIN\username` | `FSMB\skriptendruck` | NetBIOS-Domain |
| `username@domain.com` | `skriptendruck@fsmb.local` | UPN-Format |
| `.\username` | `.\skriptendruck-service` | Explizit lokaler User |
| `username` | `skriptendruck-service` | Standard (interaktive Nachfrage) |

### 3. .env Datei konfigurieren

Kopiere `.env.example` zu `.env` und passe die Werte an:

```powershell
Copy-Item .env.example .env
notepad .env
```

---

## Service installieren

### Automatische Installation (empfohlen)

Das Installationsskript erledigt alles automatisch:

```powershell
# Als Administrator ausführen
.\install_service.ps1
```

Das Skript:
1. Prüft die Voraussetzungen (venv, User, .env)
2. Lädt NSSM herunter (falls nicht vorhanden)
3. Erstellt den Windows-Service
4. Konfiguriert Auto-Start und Restart bei Fehler
5. Startet den Service

### Installation mit Parametern

```powershell
# Anderer Port
.\install_service.ps1 -Port 8080

# Lokaler User
.\install_service.ps1 -ServiceUser "mein-service-user"

# Domain-User (DOMAIN\username Format)
.\install_service.ps1 -ServiceUser "FSMB\skriptendruck"

# Domain-User (UPN-Format)
.\install_service.ps1 -ServiceUser "skriptendruck@fsmb.local"
```

### Interaktive User-Auswahl

Wenn nur ein einfacher Username ohne Domain angegeben wird, fragt das Skript interaktiv nach:

```
╔════════════════════════════════════════════════════════════════╗
║  User-Typ für 'skriptendruck-service' auswählen:               ║
╠════════════════════════════════════════════════════════════════╣
║  [L] Lokaler User        (.\skriptendruck-service)             ║
║  [D] Domain-User         (FSMB\skriptendruck-service)          ║
║  [A] Anderer User/Format (manuell eingeben)                    ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Service verwalten

### Mit NSSM (empfohlen)

```powershell
# Status prüfen
.\tools\nssm\nssm.exe status SkriptendruckDashboard

# Service stoppen
.\tools\nssm\nssm.exe stop SkriptendruckDashboard

# Service starten
.\tools\nssm\nssm.exe start SkriptendruckDashboard

# Service neustarten
.\tools\nssm\nssm.exe restart SkriptendruckDashboard

# Konfiguration bearbeiten (GUI)
.\tools\nssm\nssm.exe edit SkriptendruckDashboard
```

### Mit Windows-Diensten (services.msc)

1. **Windows-Taste + R** → `services.msc` → Enter
2. Suche "Skriptendruck Dashboard"
3. Rechtsklick für Start/Stop/Neustarten

### Mit PowerShell

```powershell
# Status
Get-Service -Name SkriptendruckDashboard

# Stoppen
Stop-Service -Name SkriptendruckDashboard

# Starten
Start-Service -Name SkriptendruckDashboard

# Neustarten
Restart-Service -Name SkriptendruckDashboard
```

---

## Logs überprüfen

### Service-Logs

Die Service-Ausgaben werden in `logs/` gespeichert:

```powershell
# Letzte Fehler anzeigen
Get-Content logs\service_stderr.log -Tail 50

# Ausgabe live verfolgen
Get-Content logs\service_stdout.log -Wait

# Fehler live verfolgen
Get-Content logs\service_stderr.log -Wait
```

### Windows Event Log

```powershell
# Service-Events anzeigen
Get-EventLog -LogName Application -Source "nssm" -Newest 20
```

---

## Service deinstallieren

```powershell
# Als Administrator ausführen
.\uninstall_service.ps1

# Logs behalten
.\uninstall_service.ps1 -KeepLogs
```

---

## Troubleshooting

### Service startet nicht

1. **Logs prüfen:**
   ```powershell
   Get-Content logs\service_stderr.log -Tail 100
   ```

2. **Berechtigungen prüfen:**
   - Hat der Service-User Zugriff auf das Projektverzeichnis?
   - Hat der Service-User "Anmelden als Dienst"-Rechte?

3. **Manuell testen:**
   ```powershell
   # Als Service-User ausführen
   runas /user:.\skriptendruck-service "powershell -File start_dashboard.ps1"
   ```

### "Anmelden als Dienst" Berechtigung

Falls der Service mit "Logon failure" fehlschlägt:

```powershell
# Lokale Sicherheitsrichtlinie öffnen
secpol.msc

# Navigiere zu:
# Lokale Richtlinien → Zuweisen von Benutzerrechten → Anmelden als Dienst
# → User "skriptendruck-service" hinzufügen
```

Oder per PowerShell (wird vom install-Skript automatisch gemacht):

```powershell
# Als Administrator
ntrights +r SeServiceLogonRight -u skriptendruck-service
```

### Netzlaufwerk nicht erreichbar

Wenn `BASE_PATH` auf ein Netzlaufwerk zeigt:

1. **UNC-Pfad verwenden** (empfohlen):
   ```env
   BASE_PATH=\\\\server\\share\\skriptendruck
   ```

2. **Netzlaufwerk für Service-User einrichten:**
   ```powershell
   # Als skriptendruck-service anmelden und Laufwerk mappen
   runas /user:.\skriptendruck-service "cmd /c net use H: \\\\server\\share /persistent:yes"
   ```

### Port bereits belegt

```powershell
# Prüfen welcher Prozess den Port nutzt
netstat -ano | findstr :8000

# Anderen Port verwenden
.\install_service.ps1 -Port 8080
```

### Service nach Windows-Update nicht mehr lauffähig

```powershell
# Service neu installieren
.\uninstall_service.ps1
.\install_service.ps1
```

### Domain-User spezifische Probleme

#### AD-Modul nicht verfügbar

Falls bei Domain-Usern die Validierung nicht funktioniert:

```powershell
# RSAT-Tools installieren (Windows 10/11)
Add-WindowsCapability -Online -Name Rsat.ActiveDirectory.DS-LDS.Tools~~~~0.0.1.0

# Auf Windows Server
Install-WindowsFeature RSAT-AD-PowerShell
```

**Hinweis:** Das Skript funktioniert auch ohne AD-Modul – es kann nur den User nicht vorher validieren.

#### Domänen-Anmeldung fehlgeschlagen

Typische Fehler und Lösungen:

| Fehler | Ursache | Lösung |
|--------|---------|--------|
| "The user name or password is incorrect" | Falsches Passwort | Passwort erneut eingeben |
| "The trust relationship between this workstation and the primary domain failed" | Domain-Trust-Problem | IT-Administrator kontaktieren |
| "The specified domain either does not exist or could not be contacted" | Domain nicht erreichbar | Netzwerkverbindung prüfen |
| "Logon failure: the user has not been granted the requested logon type" | Fehlende Berechtigung | "Anmelden als Dienst" Recht vergeben |

#### "Anmelden als Dienst" für Domain-User

```powershell
# Lokale Sicherheitsrichtlinie öffnen
secpol.msc

# Navigiere zu:
# Lokale Richtlinien → Zuweisen von Benutzerrechten → Anmelden als Dienst
# → Domain-User hinzufügen: DOMAIN\username
```

Oder per Gruppenrichtlinie (GPO) vom AD-Administrator einrichten lassen.

---

## PaperCut-Integration

Da der Service unter dem konfigurierten Account läuft, werden **alle Druckaufträge automatisch** diesem User in PaperCut zugeordnet.

### Vorteile

- Kein `pc-print.exe` erforderlich
- Automatische User-Zuordnung durch PaperCut
- Einfaches Tracking aller Skriptendruck-Aufträge
- Funktioniert mit lokalen UND Domain-Usern

### PaperCut Konfiguration

1. Service-User in PaperCut registrieren:
   - Lokaler User: `COMPUTERNAME\skriptendruck-service`
   - Domain-User: `DOMAIN\skriptendruck-service` (erscheint automatisch durch AD-Sync)
2. Optional: Shared Account "Skriptendruck" erstellen und zuweisen
3. Drucker-Zugriff für den User erlauben

Siehe [PAPERCUT_SETUP.md](PAPERCUT_SETUP.md) für Details.

---

## Konfiguration anpassen

### Port ändern

```powershell
# Service stoppen
.\tools\nssm\nssm.exe stop SkriptendruckDashboard

# Argumente ändern
.\tools\nssm\nssm.exe set SkriptendruckDashboard AppParameters "-m uvicorn skriptendruck.web.app:app --host 0.0.0.0 --port 8080 --app-dir src"

# Service starten
.\tools\nssm\nssm.exe start SkriptendruckDashboard
```

### Service-User ändern

```powershell
# Service stoppen
.\tools\nssm\nssm.exe stop SkriptendruckDashboard

# Lokaler User ändern
.\tools\nssm\nssm.exe set SkriptendruckDashboard ObjectName ".\\neuer-user" "passwort"

# Domain-User ändern
.\tools\nssm\nssm.exe set SkriptendruckDashboard ObjectName "DOMAIN\\neuer-user" "passwort"

# Service starten
.\tools\nssm\nssm.exe start SkriptendruckDashboard
```

**Hinweis:** Bei Domain-Usern wird der Backslash verdoppelt (`DOMAIN\\user`), da NSSM dies erwartet.

---

## Sicherheitshinweise

- **Passwort sicher aufbewahren:** Das Service-Passwort wird in Windows gespeichert, aber notiere es sicher für Wartungszwecke.
- **Minimale Berechtigungen:** Der Service-User braucht nur Zugriff auf:
  - Das Projektverzeichnis (lesen/schreiben)
  - Die Drucker
  - Das Netzlaufwerk (falls verwendet)
- **Firewall:** Port 8000 (oder gewählter Port) muss für interne Zugriffe freigegeben sein.
- **HTTPS:** Für Produktiveinsatz sollte ein Reverse-Proxy (nginx, IIS) mit SSL vorgeschaltet werden.

---

## Weiterführende Dokumentation

- [NSSM - Non-Sucking Service Manager](https://nssm.cc/)
- [Uvicorn Deployment](https://www.uvicorn.org/deployment/)
- [PaperCut Setup](PAPERCUT_SETUP.md)
- [Dashboard README](../README_DASHBOARD.md)
