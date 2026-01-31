# Skriptendruck 2.0

Modernisiertes Druckauftrags-Verwaltungssystem für die Fachschaft. Eine Python-basierte Neuentwicklung des ursprünglichen MATLAB-Systems mit LDAP-Integration, automatischer Preisberechnung und Deckblatterstellung.

## 🎯 Features

- ✅ **Pythonic & Modern**: Vollständig in Python 3.11+ mit Type Hints
- ✅ **Windows-kompatibel**: ldap3 statt python-ldap (keine C-Compiler nötig!)
- ✅ **LDAP Integration**: On-the-fly Benutzervalidierung über Hochschul-LDAP
- ✅ **SQLite Datenbank**: Persistente Speicherung aller Aufträge und Abrechnungen
- ✅ **Excel-Export**: Erstellt Auftrags- und Abrechnungslisten mit einem Befehl
- ✅ **Intelligente Preisberechnung**: Mit Ringbindungsgrößen-Tabelle
- ✅ **Modulare Architektur**: Saubere Trennung in Services, Models, Processing
- ✅ **Parallele Verarbeitung**: Schnellere Batch-Verarbeitung möglich
- ✅ **Rich CLI**: Moderne Kommandozeilen-Oberfläche mit Progress-Bars
- ✅ **Robustes Error-Handling**: Mit strukturiertem Logging
- ✅ **Gut getestet**: Unit Tests mit pytest

## 📋 Voraussetzungen

- Python 3.11 oder höher
- Poetry (für Dependency Management)

## 🚀 Installation

### 1. Repository klonen

```bash
git clone <your-repo-url>
cd skriptendruck
```

### 2. Dependencies installieren

```bash
poetry install
```

### 3. Initiale Konfiguration

```bash
# Beispieldaten und Config erstellen
poetry run skriptendruck init-data

# .env Datei anpassen
cp .env.example .env
# Editiere .env mit deinen Pfaden und LDAP-Konfiguration
```

### 4. Ringbindungsgrößen-Tabelle anpassen

Bearbeite `data/binding_sizes.json` mit den korrekten Werten für eure Ringbindungen.

## 📖 Verwendung

### Hauptbefehl: Aufträge verarbeiten

```bash
poetry run skriptendruck process
```

#### Optionen:

```bash
# Eigenes Auftragsverzeichnis
poetry run skriptendruck process --orders-dir /pfad/zu/auftraegen

# Eigenes Ausgabeverzeichnis
poetry run skriptendruck process --output-dir /pfad/zu/ausgabe

# Sequenzielle statt parallele Verarbeitung
poetry run skriptendruck process --sequential

# Ausführliche Ausgabe (Debug)
poetry run skriptendruck process --verbose
```

### Statistiken anzeigen

```bash
# Datenbank-Statistiken
poetry run skriptendruck db-stats

# Dateisystem-Statistiken
poetry run skriptendruck stats
```

### Excel-Export erstellen

```bash
# Letzte 30 Tage
poetry run skriptendruck export-excel

# Eigener Zeitraum (z.B. letzte 60 Tage)
poetry run skriptendruck export-excel --days 60

# Eigenes Ausgabeverzeichnis
poetry run skriptendruck export-excel --output-dir /pfad/zu/export
```

### Hilfe

```bash
poetry run skriptendruck --help
poetry run skriptendruck process --help
```

## 🏗️ Projektstruktur

```
skriptendruck/
├── src/skriptendruck/
│   ├── config/          # Konfiguration & Logging
│   ├── models/          # Datenmodelle (User, Order, Pricing)
│   ├── services/        # Business Logic
│   │   ├── filename_parser.py    # Dateinamen-Parsing
│   │   ├── user_service.py       # LDAP & User-Verwaltung
│   │   ├── pricing_service.py    # Preisberechnung
│   │   └── pdf_service.py        # PDF-Verarbeitung
│   ├── processing/      # Verarbeitungs-Pipeline
│   └── cli/             # CLI-Commands
├── tests/               # Unit Tests
├── data/                # Daten (Bindungsgrößen, Blacklist, etc.)
└── docs/                # Dokumentation
```

## ⚙️ Konfiguration

### .env Datei

Die wichtigsten Konfigurationsoptionen:

```env
# Basis-Pfade
BASE_PATH=H:/stud/fsmb/03_Dienste/01_Skriptendruck
ORDERS_PATH=01_Auftraege
OUTPUT_PATH=output

# LDAP
LDAP_ENABLED=true
LDAP_SERVER=ldap://ldap.hs-regensburg.de
LDAP_BASE_DN=ou=people,dc=hs-regensburg,dc=de

# Preise
PRICE_SW=0.04
PRICE_COLOR=0.10
PRICE_BINDING_SMALL=1.00
PRICE_BINDING_LARGE=1.50
PRICE_FOLDER=0.50

# Performance
PARALLEL_PROCESSING=true
MAX_WORKERS=4
```

### CSV-Fallback (wenn LDAP nicht verfügbar)

Erstelle `data/users_fallback.csv`:

```csv
# Format: username firstname lastname faculty
mus43225 Sebastian Müllner M
abc12345 Max Mustermann I
```

### Blacklist

Erstelle `data/blacklist.txt`:

```
# Blockierte Benutzer (ein Username pro Zeile)
blocked_user1
blocked_user2
```

## 📝 Dateinamen-Format

Erwartetes Format für PDF-Dateien:

```
<username>_<farbmodus>_<bindung>_<nummer>.pdf
```

**Beispiele:**
- `mus43225_sw_mb_001.pdf` - Schwarz-Weiß mit Bindung
- `abc12345_farbig_ob_001.pdf` - Farbe ohne Bindung
- `def67890_sw_sh_001.pdf` - Schwarz-Weiß mit Schnellhefter

**Variationen werden erkannt:**
- Farbmodus: `sw`, `schwarzweiß`, `farbig`, `farbe`
- Mit Bindung: `mb`, `mitBindung`, `binden`
- Ohne Bindung: `ob`, `ohneBindung`, `ungebunden`
- Schnellhefter: `sh`, `Schnellhefter`

## 🧪 Tests

```bash
# Alle Tests ausführen
poetry run pytest

# Mit Coverage
poetry run pytest --cov

# Einzelne Testdatei
poetry run pytest tests/test_filename_parser.py -v
```

## 🔧 Development

### Code-Qualität

```bash
# Formatierung mit black
poetry run black src tests

# Linting mit ruff
poetry run ruff check src tests

# Type-Checking mit mypy
poetry run mypy src
```

### Development-Installation

```bash
poetry install --with dev
```

## 📊 Performance-Verbesserungen vs. Original

- ✅ **Parallele Verarbeitung**: Mehrere PDFs gleichzeitig
- ✅ **Kein Excel-COM**: Direkte PDF-Generierung mit reportlab
- ✅ **Effizientes LDAP**: On-demand statt vorab alle Kontakte laden
- ✅ **Caching**: User-Cache für wiederholte Abfragen

## 🎯 Roadmap / Nächste Schritte

- [ ] Excel-Export für Abrechnungs- und Auftragsliste
- [ ] Web-GUI (Flask/FastAPI)
- [ ] Automatische Verarbeitung (Watchdog für Verzeichnis)
- [ ] E-Mail Benachrichtigungen
- [ ] Datenbank statt CSV/Excel
- [ ] REST API für Integrationen

## 🐛 Fehlersuche

### LDAP-Probleme

```bash
# LDAP deaktivieren und CSV verwenden
LDAP_ENABLED=false poetry run skriptendruck process
```

### Verbose-Modus für Debug-Infos

```bash
poetry run skriptendruck process --verbose
```

### Logdatei erstellen

```env
# In .env
LOG_FILE=skriptendruck.log
```

## 📄 Migration vom alten System

Siehe [docs/migration_notes.md](docs/migration_notes.md) für Details zur Migration.

## 🤝 Contributing

1. Fork das Repository
2. Erstelle einen Feature-Branch (`git checkout -b feature/amazing-feature`)
3. Commit deine Änderungen (`git commit -m 'Add amazing feature'`)
4. Push zum Branch (`git push origin feature/amazing-feature`)
5. Öffne einen Pull Request

## 📝 Lizenz

GPLV3

## 👥 Autoren

- Original MATLAB Version: Sebastian Müllner
- Python Modernisierung: Johannes Müller

## 🙏 Danksagungen

- Fachschaft Maschinenbau
- Hochschule Regensburg
