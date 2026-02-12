# Skriptendruck v2.3

Modernisiertes Druckauftrags-Verwaltungssystem für die Fachschaft Maschinenbau, Hochschule Regensburg.
Python-Neuentwicklung des ursprünglichen MATLAB-Systems mit LDAP-Integration, automatischer Preisberechnung,
Deckblatterstellung und Ordnerverwaltung.

## Features

- **LDAP-Integration**: Benutzervalidierung über das Active Directory der HS Regensburg (ldap3, Windows-kompatibel)
- **Verschlüsselte Credentials**: LDAP-Passwort wird verschlüsselt gespeichert (Fernet/AES), kein Klartext auf dem Netzlaufwerk
- **Automatische Ordnerverwaltung**: Aufträge werden in `02_Druckfertig/sw/` bzw. `farbig/` sortiert, Fehler nach Grund in `04_Fehler/`, Originale gesichert
- **Ringbindungsgrößen**: 13-stufige Tabelle (6,9 mm bis 38 mm) mit automatischer Auswahl nach Seitenzahl
- **Deckblatt mit Vorschau**: Generiertes Deckblatt mit Thumbnail der ersten Dokumentseite (PyMuPDF)
- **SQLite-Datenbank**: Persistente Speicherung aller Aufträge und Abrechnungen
- **Excel-Export**: Auftrags- und Abrechnungslisten auf Knopfdruck
- **Parallele Verarbeitung**: Mehrere PDFs gleichzeitig verarbeiten
- **Rich CLI**: Farbige Ausgabe mit Fortschrittsanzeige
- **Doppelklick-Start**: PowerShell-Launcher für einfache Bedienung ohne Kommandozeile

## Voraussetzungen

- Python 3.11+
- [Poetry](https://python-poetry.org/)

## Installation

### Variante A: Setup-Skript (empfohlen)

`Skriptendruck_Setup.bat` doppelklicken. Das Skript prüft Python/Poetry, installiert Abhängigkeiten, erstellt die Ordnerstruktur und richtet optional die LDAP-Credentials ein.

### Variante B: Manuell

```powershell
# Abhängigkeiten installieren
poetry install

# Ordnerstruktur und Beispieldaten erstellen
poetry run skriptendruck init

# .env erstellen und anpassen
copy _env .env
# .env editieren: BASE_PATH, LDAP-Einstellungen

# LDAP-Credentials verschlüsselt speichern
poetry run skriptendruck credentials setup
```

## Verwendung

### Für Fachschaftler (Doppelklick)

Einfach **`Skriptendruck.bat`** doppelklicken. Das startet die Verarbeitung aller PDFs im Auftragsordner.

### Kommandozeile

```powershell
# Aufträge verarbeiten
poetry run skriptendruck process

# Ausführliche Ausgabe
poetry run skriptendruck process --verbose

# Ohne Dateien zu verschieben (nur verarbeiten)
poetry run skriptendruck process --no-organize

# Sequenzielle Verarbeitung
poetry run skriptendruck process --sequential

# Anderes Auftragsverzeichnis
poetry run skriptendruck process -i C:\pfad\zu\auftraegen
```

## Konfiguration

Alle Einstellungen werden über die `.env`-Datei gesteuert. Vorlage: `_env`.

```env
# Basispfad – hier liegt die Ordnerstruktur (01_Auftraege, 02_Druckfertig, etc.)
BASE_PATH=H:/stud/fsmb/03_Dienste/01_Skriptendruck

# LDAP
LDAP_ENABLED=true
LDAP_SERVER=adldap.hs-regensburg.de
LDAP_BASE_DN=dc=hs-regensburg,dc=de
LDAP_BIND_DN=abc12345@hs-regensburg.de
# Passwort NICHT hier! → poetry run skriptendruck credentials setup

# Preise
PRICE_SW=0.04
PRICE_COLOR=0.10
PRICE_BINDING_SMALL=1.00
PRICE_BINDING_LARGE=1.50
PRICE_FOLDER=0.50
```

Ohne LDAP kann eine CSV-Fallback-Datei genutzt werden (`data/users_fallback.csv`):

```
mus43225 Sebastian Müllner M
abc12345 Max Mustermann I
```

### Verschlüsselte Credentials

Das LDAP-Passwort wird verschlüsselt auf der Platte gespeichert, damit es nicht im Klartext in der `.env` steht.

```powershell
# Einrichten (einmalig als Admin)
poetry run skriptendruck credentials setup

# Prüfen ob Credentials funktionieren
poetry run skriptendruck credentials check

# Löschen und neu einrichten
poetry run skriptendruck credentials delete
```

Die Credentials werden in `.credentials.enc` (verschlüsselt, AES via Fernet) und `.credentials.key` (Schlüssel) gespeichert. Beide Dateien sind in `.gitignore`. Falls in der `.env` ein `LDAP_BIND_PASSWORD` steht, hat dieses Vorrang.

## Ordnerstruktur

`skriptendruck init` erstellt folgende Struktur unter `BASE_PATH`:

```
BASE_PATH/
├── 01_Auftraege/                  ← PDFs hier reinlegen
├── 02_Druckfertig/
│   ├── sw/                        ← Schwarz-Weiß-Aufträge mit Deckblatt
│   │   └── gedruckt/              ← Nach dem Drucken hierhin schieben
│   └── farbig/                    ← Farbaufträge mit Deckblatt
│       └── gedruckt/              ← Nach dem Drucken hierhin schieben
├── 03_Originale/                  ← Automatisches Backup der Eingabe-PDFs
│   └── 2026-01-16_12-38/          ← Zeitstempel pro Verarbeitungslauf
├── 04_Fehler/
│   ├── benutzer_nicht_gefunden/
│   ├── gesperrt/
│   ├── zu_wenig_seiten/
│   ├── zu_viele_seiten/
│   ├── passwortgeschuetzt/
│   └── sonstige/
└── 05_Manuell/                    ← Für manuelle Aufträge
```

Das Programmverzeichnis (mit `pyproject.toml`, `.env`, etc.) ist unabhängig von `BASE_PATH` und kann an einem anderen Ort liegen.

## Dateinamen-Format

PDFs im Auftragsordner müssen folgendem Schema folgen:

```
<RZ-Kennung>_<Farbmodus>_<Bindung>_<Nummer>.pdf
```

**Beispiele:**

- `mus43225_sw_mb_001.pdf` – Schwarz-Weiß, mit Bindung
- `abc12345_farbig_ob_002.pdf` – Farbe, ohne Bindung
- `def67890_sw_sh_001.pdf` – Schwarz-Weiß, Schnellhefter

Viele Schreibvarianten werden erkannt (`schwarzweiß`, `farbe`, `mitBindung`, `ohneBindung`, `Schnellhefter`, usw.).

## CLI-Befehle

| Befehl | Beschreibung |
|--------|-------------|
| `process` | Aufträge verarbeiten (Hauptbefehl) |
| `init` | Ordnerstruktur und Beispieldaten erstellen |
| `stats` | Dateisystem-Statistiken anzeigen |
| `db-stats` | Datenbank-Statistiken anzeigen |
| `export-excel` | Auftrags- und Abrechnungslisten als Excel exportieren |
| `credentials setup` | LDAP-Credentials verschlüsselt speichern |
| `credentials check` | Credentials prüfen |
| `credentials delete` | Credentials löschen |

### Verarbeitungs-Pipeline

Was bei `process` passiert:

1. PDFs aus `01_Auftraege/` einlesen
2. Dateinamen parsen (Benutzer, Farbmodus, Bindung)
3. Benutzer per LDAP/CSV validieren
4. PDF analysieren (Seitenzahl, Passwortschutz)
5. Preis berechnen inkl. Ringbindungsgröße
6. Deckblatt mit Vorschau der ersten Seite erstellen
7. Deckblatt + leere Seite + Dokument zusammenfügen
8. Ergebnis nach `02_Druckfertig/sw/` oder `farbig/` verschieben
9. Fehlerhafte Aufträge nach `04_Fehler/<Grund>/`
10. Originale nach `03_Originale/<Zeitstempel>/` sichern
11. In Datenbank speichern

### Excel-Export

```powershell
# Letzte 30 Tage (Standard)
poetry run skriptendruck export-excel

# Eigener Zeitraum
poetry run skriptendruck export-excel --days 60

# Eigenes Ausgabeverzeichnis
poetry run skriptendruck export-excel -o C:\pfad\zu\export
```

Erstellt `Auftragsliste_YYYYMMDD.xlsx` und `Abrechnungsliste_YYYYMMDD.xlsx` im konfigurierten `EXCEL_EXPORT_PATH`.

## Ringbindungsgrößen

Die Tabelle in `data/binding_sizes.json` enthält die echten Werte:

| Ø mm | Seiten  | Bindung        |
|------|---------|----------------|
| 6,9  | 1–80    | klein (1,00 €) |
| 8,0  | 81–100  | klein          |
| 9,5  | 101–120 | klein          |
| 11,0 | 121–150 | klein          |
| 12,7 | 151–180 | klein          |
| 14,3 | 181–210 | klein          |
| 16,0 | 211–240 | klein          |
| 19,0 | 241–300 | klein          |
| 22,0 | 301–360 | groß (1,50 €)  |
| 25,4 | 361–420 | groß           |
| 28,5 | 421–480 | groß           |
| 32,0 | 481–540 | groß           |
| 38,0 | 541–660 | groß           |

## Projektstruktur

```
skriptendruck/                     ← Programmverzeichnis
├── Skriptendruck.bat              ← Doppelklick-Starter
├── Skriptendruck.ps1              ← PowerShell-Logik
├── Skriptendruck_Setup.bat        ← Ersteinrichtung
├── Skriptendruck_Setup.ps1        ← Setup-Logik
├── pyproject.toml                 ← Poetry Konfiguration
├── _env                           ← .env Vorlage
├── .env                           ← Konfiguration (nicht in Git)
├── .credentials.enc               ← Verschlüsseltes Passwort (nicht in Git)
├── .credentials.key               ← Schlüssel (nicht in Git)
├── data/
│   ├── binding_sizes.json         ← Ringbindungsgrößen
│   ├── blacklist.txt              ← Gesperrte Benutzer
│   └── users_fallback.csv         ← CSV-Fallback für User-Lookup
├── tests/                         ← Unit Tests
│   ├── test_filename_parser.py
│   ├── test_pricing_service.py
│   ├── test_file_organizer.py
│   └── ...
└── src/skriptendruck/
    ├── config/
    │   ├── settings.py            ← Pydantic Settings (.env)
    │   ├── logging.py             ← Rich Logging
    │   └── credentials.py         ← Verschlüsselte Credentials
    ├── models/
    │   ├── user.py                ← User (RZ-Kennung, Name, Fakultät)
    │   ├── order.py               ← Order (Auftrag mit Status)
    │   └── pricing.py             ← Pricing, BindingSize, ColorMode
    ├── services/
    │   ├── filename_parser.py     ← Dateinamen-Parsing
    │   ├── user_service.py        ← LDAP + CSV-Fallback
    │   ├── pricing_service.py     ← Preisberechnung
    │   ├── pdf_service.py         ← PDF-Verarbeitung + Deckblatt + Thumbnail
    │   ├── file_organizer.py      ← Ordnerstruktur + Dateiverschiebung
    │   └── excel_service.py       ← Excel-Export
    ├── database/
    │   ├── models.py              ← DB-Modelle (OrderRecord, BillingRecord)
    │   └── service.py             ← DB-Operationen
    ├── processing/
    │   └── pipeline.py            ← Verarbeitungs-Pipeline
    └── cli/
        └── commands.py            ← Typer CLI
```

## Entwicklung

```powershell
# Tests
poetry run pytest

# Mit Coverage
poetry run pytest --cov

# Formatierung
poetry run black src tests

# Linting
poetry run ruff check src tests

# Type-Checking
poetry run mypy src
```

## Tech-Stack

- **Python 3.11+** mit Poetry
- **Pydantic / pydantic-settings** – Konfiguration und Validierung
- **SQLAlchemy** – Datenbank-ORM (SQLite)
- **ldap3** – LDAP-Anbindung (pure Python, Windows-kompatibel)
- **cryptography** – Fernet-Verschlüsselung für Credentials
- **pypdf** – PDF lesen und zusammenfügen
- **reportlab** – Deckblatt-Generierung
- **PyMuPDF (fitz)** – Thumbnail-Rendering
- **openpyxl / xlsxwriter** – Excel-Export
- **Typer + Rich** – CLI mit farbiger Ausgabe

## Migration vom MATLAB-System

- `01_print_sw` / `01_print_farbig` → `02_Druckfertig/sw/` / `farbig/`
- `05_wrong/02_name_not_found` etc. → `04_Fehler/benutzer_nicht_gefunden/` etc.
- `02_original_Skripte` → `03_Originale/`
- Kein pdftk.exe mehr nötig – alles native Python
- Kein Excel COM mehr – direkte PDF-Generierung mit reportlab
- Kontakte.mat → LDAP oder CSV-Fallback

## Lizenz

GPLv3

## Autoren

- Original MATLAB-Version: Sebastian Müllner
- Python-Modernisierung: Johannes Müller
