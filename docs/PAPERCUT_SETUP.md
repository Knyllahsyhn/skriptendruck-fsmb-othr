# PaperCut NG Integration – Setup-Anleitung

Diese Anleitung beschreibt, wie PaperCut NG für das Skriptendruck-Dashboard eingerichtet wird,
damit alle Druckaufträge **headless** (ohne Popup) über einen lokalen Service-Account gedruckt
und über das **Shared Account „Skriptendruck"** in PaperCut abgerechnet werden.

## Voraussetzungen

- PaperCut NG ist auf dem Server installiert
- Admin-Zugriff auf die PaperCut-Verwaltungsoberfläche
- Das CLI-Tool `pc-print` ist verfügbar (wird mit PaperCut mitgeliefert)
- Lokaler Administrator-Zugriff auf den Windows-Server

---

## Schritt 1: Lokalen Windows-User anlegen

> **Hinweis:** Da kein Domain-Controller verfügbar ist, wird ein **lokaler** Windows-User angelegt.

### Via PowerShell (als Administrator)

```powershell
# Lokalen User "skriptendruck-service" anlegen
$Password = Read-Host -AsSecureString "Passwort für skriptendruck-service"
New-LocalUser -Name "skriptendruck-service" `
              -Password $Password `
              -Description "Service-Account für Skriptendruck-Druckaufträge" `
              -PasswordNeverExpires

# Optional: User zur Gruppe "Users" hinzufügen
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

## Schritt 3: Shared Account „Skriptendruck" erstellen

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
4. Alternativ: Unter **Benutzer** → `skriptendruck-service` → **Shared Accounts**:
   - `Skriptendruck` als Standard-Konto zuweisen

---

## Schritt 5: pc-print testen

Öffne eine **Eingabeaufforderung (CMD)** oder **PowerShell** auf dem Server:

```cmd
# Pfad zu pc-print prüfen (Standard-Installationspfad)
"C:\Program Files\PaperCut NG\client\win\pc-print.exe" --help
```

### Testdruck ausführen

```cmd
"C:\Program Files\PaperCut NG\client\win\pc-print.exe" ^
    --user=skriptendruck-service ^
    --account=Skriptendruck ^
    --printer="DRUCKERNAME" ^
    "C:\Pfad\zur\Testdatei.pdf"
```

> **Tipp:** Den genauen Druckernamen findest du unter **Systemsteuerung** → **Geräte und Drucker**
> oder in PaperCut unter **Drucker**.

### Erwartetes Ergebnis

- Der Druckauftrag wird an den Drucker gesendet
- In PaperCut wird der Auftrag unter dem Shared Account **Skriptendruck** verbucht
- Der Benutzer `skriptendruck-service` erscheint als Auftraggeber
- **Kein Popup** oder interaktives Fenster

### Fehlerbehebung

| Problem | Lösung |
|---|---|
| `pc-print` nicht gefunden | Installationspfad prüfen, ggf. `PC_PRINT_PATH` in `.env` anpassen |
| "User not found" | User in PaperCut registrieren (Schritt 2) |
| "Account not found" | Shared Account Name prüfen (Groß-/Kleinschreibung beachten) |
| "Access denied" | User dem Shared Account zuordnen (Schritt 4) |
| Drucker nicht erreichbar | Druckername prüfen, Drucker-Status in PaperCut checken |

---

## Schritt 6: Skriptendruck-Dashboard konfigurieren

Ergänze folgende Variablen in der `.env`-Datei:

```env
# PaperCut Integration
# --------------------
# Pfad zur pc-print.exe (PaperCut Client CLI)
PC_PRINT_PATH=C:\Program Files\PaperCut NG\client\win\pc-print.exe

# PaperCut Benutzername (lokaler Windows-User)
PAPERCUT_USER=skriptendruck-service

# PaperCut Shared Account Name
PAPERCUT_ACCOUNT=Skriptendruck
```

> **Fallback:** Wenn `PC_PRINT_PATH` nicht gesetzt oder die Datei nicht existiert,
> fällt das System automatisch auf **SumatraPDF Silent Print** zurück.
> Eine Warnung wird im Log ausgegeben.

---

## Architektur-Übersicht

```
Dashboard (Web-UI)
    │
    ▼
PrintingService
    │
    ├── PC_PRINT_PATH gesetzt & Datei existiert?
    │       │
    │       ├── JA  → pc-print --user=... --account=... --printer=... file.pdf
    │       │           └── Abrechnung über PaperCut Shared Account
    │       │
    │       └── NEIN → Fallback: SumatraPDF Silent Print
    │                   └── Keine PaperCut-Abrechnung
    │
    ▼
Drucker (physisch)
```

---

## Sicherheitshinweise

- Der `skriptendruck-service`-User sollte **nur** für Druckaufträge verwendet werden
- Passwort sicher aufbewahren (z.B. im Windows Credential Manager)
- Zugriff auf das Shared Account auf den Service-User beschränken
- PaperCut-Logs regelmäßig prüfen (unter **Protokolle** in der Admin-Oberfläche)
- Den Service-Account **nicht** für interaktive Anmeldungen verwenden

---

## Weiterführende Dokumentation

- [PaperCut NG Admin Guide](https://www.papercut.com/help/manuals/ng-mf/)
- [pc-print CLI Reference](https://www.papercut.com/help/manuals/ng-mf/common/tools-pc-print/)
- [Skriptendruck README](../README_DASHBOARD.md)
