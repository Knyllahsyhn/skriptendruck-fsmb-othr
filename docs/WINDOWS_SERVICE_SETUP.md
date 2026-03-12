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

Ein lokaler Windows-User wird benötigt, unter dem der Service läuft:

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

# Anderer Service-User
.\install_service.ps1 -ServiceUser "mein-service-user"
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

---

## PaperCut-Integration

Da der Service unter dem Account `skriptendruck-service` läuft, werden **alle Druckaufträge automatisch** diesem User in PaperCut zugeordnet.

### Vorteile

- Kein `pc-print.exe` erforderlich
- Automatische User-Zuordnung durch PaperCut
- Einfaches Tracking aller Skriptendruck-Aufträge

### PaperCut Konfiguration

1. User `skriptendruck-service` in PaperCut registrieren
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

# User ändern (interaktive Passworteingabe)
.\tools\nssm\nssm.exe set SkriptendruckDashboard ObjectName ".\\neuer-user" "passwort"

# Service starten
.\tools\nssm\nssm.exe start SkriptendruckDashboard
```

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
