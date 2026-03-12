# PaperCut NG Integration – Setup-Anleitung

Diese Anleitung beschreibt, wie PaperCut NG für das Skriptendruck-Dashboard eingerichtet wird,
damit alle Druckaufträge automatisch dem Service-Account `skriptendruck-service` zugeordnet werden.

## Konzept

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Windows Server                                    │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │           Windows-Service: SkriptendruckDashboard              │ │
│  │           läuft unter: .\skriptendruck-service                 │ │
│  │  ┌──────────────────────────────────────────────────────────┐  │ │
│  │  │  SumatraPDF sendet Druckauftrag                          │  │ │
│  │  │       │                                                  │  │ │
│  │  │       ▼                                                  │  │ │
│  │  │  PaperCut erkennt User "skriptendruck-service"           │  │ │
│  │  │  und verbucht automatisch auf Shared Account             │  │ │
│  │  └──────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

**Vorteile dieses Ansatzes:**
- Kein `pc-print.exe` erforderlich
- Automatische User-Zuordnung durch PaperCut
- Einfaches Tracking aller Skriptendruck-Aufträge
- SumatraPDF für zuverlässiges Silent-Printing

## Voraussetzungen

- PaperCut NG ist auf dem Server installiert
- Admin-Zugriff auf die PaperCut-Verwaltungsoberfläche
- Lokaler Administrator-Zugriff auf den Windows-Server
- Dashboard läuft als Windows-Service (siehe [WINDOWS_SERVICE_SETUP.md](WINDOWS_SERVICE_SETUP.md))

---

## Schritt 1: Lokalen Windows-User anlegen

> **Hinweis:** Dieser Schritt wird vom `install_service.ps1` Skript geprüft.
> Falls der User noch nicht existiert, muss er vorab angelegt werden.

### Via PowerShell (als Administrator)

```powershell
# Lokalen User "skriptendruck-service" anlegen
$Password = Read-Host -AsSecureString "Passwort für skriptendruck-service"
New-LocalUser -Name "skriptendruck-service" `
              -Password $Password `
              -Description "Service-Account für Skriptendruck-Druckaufträge" `
              -PasswordNeverExpires

# User zur Gruppe "Users" hinzufügen
Add-LocalGroupMember -Group "Users" -Member "skriptendruck-service"
```

### Via GUI (Alternative)

1. **Windows-Taste + R** → `lusrmgr.msc` → Enter
2. Links auf **Benutzer** klicken
3. Rechtsklick → **Neuer Benutzer...**
4. Benutzername: `skriptendruck-service`
5. Beschreibung: `Service-Account für Skriptendruck-Druckaufträge`
6. Passwort vergeben
7. ☑ **Kennwort läuft nie ab** aktivieren
8. ☐ **Benutzer muss Kennwort bei nächster Anmeldung ändern** deaktivieren
9. **Erstellen** klicken

---

## Schritt 2: User in PaperCut registrieren

1. PaperCut Admin-Oberfläche öffnen: `http://localhost:9191/admin`
2. Navigiere zu **Benutzer** → **Neuen Benutzer anlegen** (oder warten bis PaperCut den User automatisch synchronisiert)
3. Falls der User nicht automatisch erkannt wird:
   - **Benutzer** → **Importieren/Synchronisieren**
   - Sicherstellen, dass lokale Windows-Benutzer einbezogen werden
4. Prüfen, dass `skriptendruck-service` in der Benutzerliste erscheint

### Benutzer-Einstellungen in PaperCut

| Einstellung | Wert |
|---|---|
| Benutzername | `skriptendruck-service` |
| Kontotyp | Beschränkt (restricted) – kein eigenes Guthaben nötig |
| Drucker-Zugriff | Alle relevanten Drucker erlauben |

---

## Schritt 3: Shared Account „Skriptendruck" erstellen (optional)

Wenn alle Druckkosten auf ein zentrales Konto verbucht werden sollen:

1. In der PaperCut Admin-Oberfläche: **Konten** → **Shared Accounts**
2. **Neues Shared Account erstellen**
3. Einstellungen:

| Einstellung | Wert |
|---|---|
| Kontoname | `Skriptendruck` |
| Beschreibung | `Sammelkonto für alle Skriptendruck-Druckaufträge der FSMB` |
| Kontotyp | Standard |
| Anfangsguthaben | Ausreichend hoch setzen (z.B. 1000 €) oder unbegrenzt |
| Aktiviert | ☑ Ja |

---

## Schritt 4: User dem Shared Account zuordnen

1. **Konten** → **Shared Accounts** → **Skriptendruck** anklicken
2. Tab **Sicherheit** oder **Zugriff**
3. `skriptendruck-service` als berechtigten Benutzer hinzufügen
4. **Automatische Zuweisung konfigurieren:**
   - Unter **Benutzer** → `skriptendruck-service` → **Shared Accounts**
   - `Skriptendruck` als **Standard-Konto** für alle Druckaufträge zuweisen
   - Option aktivieren: "Shared Account automatisch belasten"

---

## Schritt 5: Windows-Service installieren

```powershell
# Als Administrator ausführen
.\install_service.ps1
```

Das Skript:
1. Installiert NSSM (falls nicht vorhanden)
2. Erstellt den Service "SkriptendruckDashboard"
3. Konfiguriert den Service für den User `skriptendruck-service`
4. Startet den Service

Siehe [WINDOWS_SERVICE_SETUP.md](WINDOWS_SERVICE_SETUP.md) für Details.

---

## Schritt 5b: PaperCut Client Autostart (Optional)

Falls der PaperCut Client (`pcclient.exe`) separat unter einem anderen Benutzer laufen soll
(z.B. für spezielle Abrechnungsanforderungen), kann dieser über Task Scheduler automatisch
beim Systemstart gestartet werden.

### Warum pcclient separat starten?

- Das Dashboard läuft unter `skriptendruck-service` für die Print-Attribution
- Der PaperCut Client kann unter einem anderen User laufen (z.B. für Client-seitige Popup-Benachrichtigungen)
- Trennung von Dashboard-Service und PaperCut Client

### Installation

```powershell
# Als Administrator ausführen
.\setup_papercut_autostart.ps1
```

Das Skript:
1. Findet `pc-client.exe` automatisch in bekannten PaperCut-Installationspfaden
2. Erstellt einen Task Scheduler Task "PaperCut Client Autostart"
3. Konfiguriert den Task für automatischen Start bei Systemboot
4. Ermöglicht optionalen Teststart

#### Mit manuellem Pfad

```powershell
.\setup_papercut_autostart.ps1 -PaperCutPath "D:\PaperCut\client\pc-client.exe"
```

#### Mit anderem Service-User

```powershell
.\setup_papercut_autostart.ps1 -ServiceUser ".\print-user"
```

### Task-Konfiguration

Der erstellte Task hat folgende Eigenschaften:

| Eigenschaft | Wert |
|---|---|
| Name | PaperCut Client Autostart |
| Trigger | Bei Systemstart |
| Benutzer | `.\skriptendruck-service` (konfigurierbar) |
| Neustart bei Fehler | 3 Versuche, 1 Minute Intervall |
| Mehrere Instanzen | Ignorieren |

### Deinstallation

```powershell
# Task entfernen
.\remove_papercut_autostart.ps1

# Task entfernen und Prozess beenden
.\remove_papercut_autostart.ps1 -StopProcess
```

### Überprüfung

#### Task im Task Scheduler prüfen

```powershell
# Task-Status anzeigen
Get-ScheduledTask -TaskName "PaperCut Client Autostart"

# Task-Details anzeigen
Get-ScheduledTaskInfo -TaskName "PaperCut Client Autostart"
```

Oder visuell:
1. **Windows-Taste + R** → `taskschd.msc` → Enter
2. Im linken Panel: **Aufgabenplanungsbibliothek**
3. Task "PaperCut Client Autostart" suchen

#### Prüfen ob pcclient läuft

```powershell
Get-Process -Name "pc-client" -ErrorAction SilentlyContinue
```

#### Task manuell starten

```powershell
Start-ScheduledTask -TaskName "PaperCut Client Autostart"
```

### Alternative: PaperCut Client als Windows-Service

PaperCut bietet keine native Service-Option für den Client (`pcclient.exe`), aber es gibt Alternativen:

**Option 1: NSSM (empfohlen für Headless-Server)**
```powershell
# pcclient als Service mit NSSM installieren
nssm install PaperCutClient "C:\Program Files\PaperCut NG\client\pc-client.exe"
nssm set PaperCutClient Start SERVICE_AUTO_START
nssm set PaperCutClient ObjectName .\skriptendruck-service <password>
```

**Option 2: PaperCut User Client mit Login-Script**
Falls interaktive Anmeldung erforderlich, kann der Client per Login-Script gestartet werden:
```batch
@echo off
start "" "C:\Program Files\PaperCut NG\client\pc-client.exe"
```

> **Hinweis:** Die Task Scheduler-Methode (dieses Skript) ist die empfohlene Lösung,
> da sie robust ist und den Client unabhängig von Benutzeranmeldungen startet.

### Troubleshooting

| Problem | Lösung |
|---|---|
| pcclient startet nicht nach Neustart | Task im Task Scheduler prüfen, Trigger-Status überprüfen |
| "Zugriff verweigert" Fehler | Passwort des Service-Users prüfen, neu eingeben |
| Task läuft aber pcclient nicht sichtbar | Normal bei "Run whether user is logged on or not" – Prozess existiert |
| pcclient stürzt wiederholt ab | PaperCut Server-Verbindung prüfen, Logs in `%APPDATA%\PaperCut NG` |
| Falscher User für Druckabrechnung | Service-User im Task Scheduler ändern |

---

## Schritt 6: Funktionstest

### Service-Status prüfen

```powershell
Get-Service -Name SkriptendruckDashboard
```

### Testdruck ausführen

1. Dashboard im Browser öffnen: `http://localhost:8000`
2. Einen Test-Auftrag verarbeiten
3. "Drucken" aktivieren und Auftrag starten

### In PaperCut prüfen

1. **Protokolle** → **Druckaufträge**
2. Suche nach `skriptendruck-service`
3. Verifizieren:
   - User: `skriptendruck-service`
   - Account: `Skriptendruck` (falls konfiguriert)

---

## Architektur-Übersicht

```
                    ┌─────────────────────┐
                    │    Web-Browser      │
                    │    (Benutzer)       │
                    └─────────┬───────────┘
                              │ HTTP
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                Windows-Service: SkriptendruckDashboard          │
│                User: .\skriptendruck-service                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                  FastAPI Dashboard                        │  │
│  │                        │                                  │  │
│  │                        ▼                                  │  │
│  │              PrintingService                              │  │
│  │                        │                                  │  │
│  │                        ▼                                  │  │
│  │   SumatraPDF -print-to "Drucker" -silent file.pdf         │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        PaperCut NG                              │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Erkennt Druckauftrag von: skriptendruck-service          │  │
│  │  Verbucht auf Shared Account: Skriptendruck               │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │      Drucker        │
                    └─────────────────────┘
```

---

## Troubleshooting

| Problem | Lösung |
|---|---|
| User nicht in PaperCut sichtbar | PaperCut User-Sync prüfen, lokale User einbeziehen |
| Druckauftrag wird nicht verbucht | Prüfen ob Service wirklich unter dem richtigen User läuft |
| Falscher User in PaperCut | Service stoppen, User in NSSM prüfen, neu starten |
| "Access denied" bei Drucker | Drucker-Berechtigungen für skriptendruck-service prüfen |
| Shared Account wird nicht belastet | Auto-Zuweisung in PaperCut prüfen (Schritt 4) |

### Service-User verifizieren

```powershell
# Welcher User führt den Service aus?
Get-WmiObject Win32_Service -Filter "Name='SkriptendruckDashboard'" | 
    Select-Object Name, StartName
```

### PaperCut-Logs prüfen

In der PaperCut Admin-Oberfläche:
- **Protokolle** → **Druckaufträge** → Nach User filtern
- **Protokolle** → **Anwendungsprotokoll** → Fehler prüfen

---

## Sicherheitshinweise

- Der `skriptendruck-service`-User sollte **nur** für den Dashboard-Service verwendet werden
- Passwort sicher aufbewahren (z.B. im Windows Credential Manager)
- Zugriff auf das Shared Account auf den Service-User beschränken
- PaperCut-Logs regelmäßig prüfen (unter **Protokolle** in der Admin-Oberfläche)
- Den Service-Account **nicht** für interaktive Anmeldungen verwenden

---

## Weiterführende Dokumentation

- [Windows-Service Setup](WINDOWS_SERVICE_SETUP.md)
- [PaperCut NG Admin Guide](https://www.papercut.com/help/manuals/ng-mf/)
- [Skriptendruck README](../README_DASHBOARD.md)
