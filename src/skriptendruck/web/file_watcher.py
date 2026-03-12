"""File-Watcher Service für das Dashboard.

Überwacht den Aufträgeordner (01_Auftraege) auf neue PDF-Dateien und
trägt sie automatisch als 'pending' in die Datenbank ein.
Der Watcher druckt NICHT automatisch – das passiert nur bei manuellem
'Starten' über das Dashboard.

Der überwachte Pfad wird wie folgt bestimmt:
1. ``FILE_WATCHER_DIR`` aus der ``.env`` (falls gesetzt)
2. Sonst: ``{BASE_PATH}/01_Auftraege``

``BASE_PATH`` kann ein lokaler Pfad, ein gemapptes Netzlaufwerk
(``Z:\\skriptendruck``) oder ein UNC-Pfad
(``\\\\server\\share\\skriptendruck``) sein.
"""
import asyncio
import os
import re
import traceback
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Optional, Set, List

from sqlalchemy import select

from ..config import get_logger, settings
from ..database.models import Base, OrderRecord
from ..database.service import DatabaseService

logger = get_logger("web.file_watcher")


# ---------------------------------------------------------------------------
# Hilfsfunktion: robuste Pfad-Erstellung (UNC + Netzlaufwerk-kompatibel)
# ---------------------------------------------------------------------------

def _resolve_orders_dir(orders_dir: Optional[Path] = None) -> Path:
    """Ermittelt das Auftragsverzeichnis als :class:`Path`.

    Unterstützt lokale Pfade, gemappte Laufwerke (``Z:\\...``) und
    UNC-Pfade (``\\\\server\\share\\...``).  Auf Windows wird
    :class:`pathlib.WindowsPath` automatisch UNC-Pfade korrekt handhaben;
    auf Linux/macOS wird der rohe Pfad-String beibehalten.
    """
    logger.info("=" * 60)
    logger.info("_resolve_orders_dir() aufgerufen")
    
    if orders_dir is not None:
        logger.info(f"  -> Übergebener orders_dir: {orders_dir}")
        return orders_dir

    # BASE_PATH aus Settings laden
    base = settings.base_path
    logger.info(f"  -> settings.base_path geladen: {base}")
    logger.info(f"  -> Typ von base_path: {type(base)}")
    
    # Auftragsordner konstruieren
    orders_path = Path(os.path.join(str(base), "01_Auftraege"))
    logger.info(f"  -> Konstruierter Auftragsordner: {orders_path}")
    logger.info("=" * 60)
    
    return orders_path


def _check_directory_access(directory: Path) -> dict:
    """Prüft Zugriff auf ein Verzeichnis und gibt detaillierte Infos zurück."""
    result = {
        "path": str(directory),
        "exists": False,
        "is_dir": False,
        "readable": False,
        "files_count": 0,
        "pdf_count": 0,
        "error": None,
        "pdf_files": []
    }
    
    try:
        # Existenz prüfen
        result["exists"] = directory.exists()
        logger.info(f"  Verzeichnis existiert: {result['exists']}")
        
        if not result["exists"]:
            result["error"] = f"Verzeichnis existiert nicht: {directory}"
            return result
        
        # Ist es ein Verzeichnis?
        result["is_dir"] = directory.is_dir()
        logger.info(f"  Ist Verzeichnis: {result['is_dir']}")
        
        if not result["is_dir"]:
            result["error"] = f"Pfad ist kein Verzeichnis: {directory}"
            return result
        
        # Lesezugriff prüfen
        try:
            files = list(directory.iterdir())
            result["readable"] = True
            result["files_count"] = len(files)
            logger.info(f"  Lesezugriff: OK ({len(files)} Einträge)")
        except PermissionError as e:
            result["error"] = f"Keine Leseberechtigung: {e}"
            logger.error(f"  Lesezugriff: FEHLER - {e}")
            return result
        
        # PDF-Dateien zählen
        pdf_files = [f for f in files if f.suffix.lower() == '.pdf' and f.is_file()]
        result["pdf_count"] = len(pdf_files)
        result["pdf_files"] = [f.name for f in pdf_files]
        logger.info(f"  PDF-Dateien gefunden: {len(pdf_files)}")
        
        if pdf_files:
            for pdf in pdf_files[:10]:  # Maximal 10 anzeigen
                logger.info(f"    - {pdf.name}")
            if len(pdf_files) > 10:
                logger.info(f"    ... und {len(pdf_files) - 10} weitere")
        
    except Exception as e:
        result["error"] = f"Unerwarteter Fehler: {e}"
        logger.error(f"  Fehler beim Prüfen: {e}")
        logger.error(traceback.format_exc())
    
    return result


# ---------------------------------------------------------------------------
# Dateiname-Parsing (leichtgewichtig, ohne schwere Pipeline-Abhängigkeiten)
# ---------------------------------------------------------------------------

# Typisches Schema: <username>_<Name>_<farbmodus>_<bindung>[_<nr>].pdf
# Beispiel:  mus43225_Mueller_Sebastian_sw_ringbindung.pdf
_COLOR_KEYWORDS = {
    "sw": "sw", "bw": "sw", "schwarzweiss": "sw", "schwarzweiß": "sw",
    "farbig": "color", "farbe": "color", "color": "color", "colour": "color",
}

_BINDING_KEYWORDS = {
    "ringbindung": "small", "ring": "small", "bindung": "small",
    "grossebindung": "large", "grosseringbindung": "large",
    "großebindung": "large", "großeringbindung": "large",
    "schnellhefter": "folder", "hefter": "folder", "folder": "folder",
    "keine": "none", "none": "none", "ohne": "none",
}


def _parse_pdf_filename(filename: str) -> dict:
    """Extrahiert Metadaten aus dem PDF-Dateinamen.

    Returns dict with keys:
        username, first_name, last_name, color_mode, binding_type
    (Alle können None sein, wenn nicht erkennbar.)
    """
    stem = Path(filename).stem
    parts = re.split(r"[_\- ]+", stem)

    info: dict = {
        "username": None,
        "first_name": None,
        "last_name": None,
        "color_mode": None,
        "binding_type": None,
    }

    remaining: list[str] = []
    for part in parts:
        low = part.lower()
        if low in _COLOR_KEYWORDS and info["color_mode"] is None:
            info["color_mode"] = _COLOR_KEYWORDS[low]
        elif low in _BINDING_KEYWORDS and info["binding_type"] is None:
            info["binding_type"] = _BINDING_KEYWORDS[low]
        else:
            remaining.append(part)

    # Erstes Token ist üblicherweise die RZ-Kennung (z.B. mus43225)
    if remaining:
        candidate = remaining[0]
        # RZ-Kennungen bestehen aus 3 Buchstaben + Ziffern
        if re.match(r"^[a-zA-Z]{2,4}\d{3,6}$", candidate):
            info["username"] = candidate.lower()
            remaining = remaining[1:]

    # Nachname / Vorname aus den restlichen Teilen
    name_parts = [p for p in remaining if not p.isdigit()]
    if len(name_parts) >= 2:
        info["last_name"] = name_parts[0]
        info["first_name"] = name_parts[1]
    elif len(name_parts) == 1:
        info["last_name"] = name_parts[0]

    logger.debug(f"  Dateiname geparst: {filename} -> {info}")
    return info


# ---------------------------------------------------------------------------
# Datenbankzugriff
# ---------------------------------------------------------------------------

def _get_db() -> DatabaseService:
    """Erzeugt eine DatabaseService-Instanz mit dem konfigurierten Pfad."""
    db_path = settings.database_path
    logger.debug(f"_get_db() - database_path: {db_path}")
    if not db_path.is_absolute():
        db_path = settings.base_path / db_path
        logger.debug(f"_get_db() - relativer Pfad aufgelöst zu: {db_path}")
    return DatabaseService(db_path=db_path)


def _get_next_order_id(db: DatabaseService) -> int:
    """Ermittelt die nächste freie Order-ID."""
    try:
        with db.SessionLocal() as session:
            max_id = session.query(OrderRecord.order_id).order_by(
                OrderRecord.order_id.desc()
            ).limit(1).scalar()
            return (max_id or 0) + 1
    except Exception:
        return 1


def _is_file_known(db: DatabaseService, filename: str, filepath_str: str) -> bool:
    """Prüft ob eine Datei bereits in der DB existiert (Duplikat-Check)."""
    with db.SessionLocal() as session:
        stmt = select(OrderRecord).where(
            (OrderRecord.filename == filename)
            & (OrderRecord.original_filepath == filepath_str)
        )
        return session.scalar(stmt) is not None


def _register_file(db: DatabaseService, pdf_path: Path) -> Optional[OrderRecord]:
    """Registriert eine neue PDF-Datei als 'pending' Auftrag in der DB.

    Returns:
        Das erzeugte OrderRecord oder None bei Fehler/Duplikat.
    """
    filename = pdf_path.name
    filepath_str = str(pdf_path)
    
    logger.debug(f"_register_file() - Verarbeite: {filename}")

    if _is_file_known(db, filename, filepath_str):
        logger.debug(f"  -> Datei bereits bekannt, überspringe: {filename}")
        return None

    meta = _parse_pdf_filename(filename)
    order_id = _get_next_order_id(db)

    try:
        file_size = pdf_path.stat().st_size
        logger.debug(f"  -> Dateigröße: {file_size} Bytes")
    except OSError as e:
        logger.warning(f"  -> Konnte Dateigröße nicht ermitteln: {e}")
        file_size = 0

    record = OrderRecord(
        order_id=order_id,
        filename=filename,
        username=meta["username"],
        first_name=meta["first_name"],
        last_name=meta["last_name"],
        color_mode=meta["color_mode"],
        binding_type=meta["binding_type"],
        status="pending",
        created_at=datetime.now(),
        original_filepath=filepath_str,
        operator=os.getenv("USER", os.getenv("USERNAME", "dashboard")),
    )

    try:
        with db.SessionLocal() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            logger.info(
                f"✓ Neuer Auftrag registriert: #{record.order_id} – "
                f"{filename} (user={meta['username']}, color={meta['color_mode']}, binding={meta['binding_type']})"
            )
            return record
    except Exception as exc:
        logger.error(f"✗ Fehler beim Registrieren von {filename}: {exc}")
        logger.error(traceback.format_exc())
        return None


# ---------------------------------------------------------------------------
# Scan-Funktion (ein einzelner Durchlauf)
# ---------------------------------------------------------------------------

def scan_orders_directory(orders_dir: Optional[Path] = None) -> int:
    """Scannt das Auftragsverzeichnis und registriert neue PDFs.

    Args:
        orders_dir: Pfad zum Auftragsordner.
            Falls ``None``, wird ``{BASE_PATH}/01_Auftraege`` verwendet.
            Unterstützt lokale Pfade, gemappte Netzlaufwerke und UNC-Pfade.

    Returns:
        Anzahl neu registrierter Aufträge.
    """
    logger.info("-" * 60)
    logger.info("scan_orders_directory() gestartet")
    
    # Pfad auflösen
    orders_dir = _resolve_orders_dir(orders_dir)
    
    # Verzeichniszugriff prüfen
    logger.info("Prüfe Verzeichniszugriff...")
    access_info = _check_directory_access(orders_dir)
    
    if access_info["error"]:
        logger.error(f"FEHLER: {access_info['error']}")
        logger.error("-" * 60)
        return 0
    
    if not access_info["exists"]:
        logger.warning(f"Auftragsverzeichnis nicht vorhanden: {orders_dir}")
        logger.warning("Bitte prüfen Sie:")
        logger.warning(f"  1. Ist BASE_PATH in .env korrekt gesetzt? (aktuell: {settings.base_path})")
        logger.warning(f"  2. Existiert der Ordner '01_Auftraege' unter {settings.base_path}?")
        logger.warning(f"  3. Hat der Service-User Zugriff auf das Netzlaufwerk?")
        logger.warning("-" * 60)
        return 0

    if access_info["pdf_count"] == 0:
        logger.info(f"Keine PDF-Dateien im Ordner gefunden: {orders_dir}")
        logger.info("-" * 60)
        return 0

    # Datenbank initialisieren
    logger.info("Initialisiere Datenbankverbindung...")
    try:
        db = _get_db()
        logger.info("  -> Datenbankverbindung OK")
    except Exception as e:
        logger.error(f"Datenbankfehler: {e}")
        logger.error(traceback.format_exc())
        return 0

    # PDFs verarbeiten
    registered = 0
    logger.info(f"Verarbeite {access_info['pdf_count']} PDF-Dateien...")
    
    try:
        for pdf_path in sorted(orders_dir.glob("*.pdf")):
            if pdf_path.is_file():
                rec = _register_file(db, pdf_path)
                if rec is not None:
                    registered += 1
    except Exception as e:
        logger.error(f"Fehler beim Durchsuchen des Ordners: {e}")
        logger.error(traceback.format_exc())

    if registered:
        logger.info(f"✓ File-Watcher: {registered} neue Aufträge registriert")
    else:
        logger.info("Keine neuen Aufträge (alle Dateien bereits bekannt)")
    
    logger.info("-" * 60)
    return registered


# ---------------------------------------------------------------------------
# Manueller Scan (API-Aufruf)
# ---------------------------------------------------------------------------

def manual_scan() -> dict:
    """Führt einen manuellen Scan durch und gibt detaillierte Infos zurück.
    
    Diese Funktion wird vom API-Endpoint /api/scan aufgerufen.
    """
    logger.info("=" * 60)
    logger.info("MANUELLER SCAN GESTARTET")
    logger.info("=" * 60)
    
    result = {
        "success": False,
        "base_path": str(settings.base_path),
        "orders_dir": None,
        "dir_exists": False,
        "dir_readable": False,
        "total_files": 0,
        "pdf_files": 0,
        "new_orders": 0,
        "error": None,
        "pdf_list": []
    }
    
    try:
        # Pfad auflösen
        orders_dir = _resolve_orders_dir()
        result["orders_dir"] = str(orders_dir)
        
        # Zugriff prüfen
        access_info = _check_directory_access(orders_dir)
        result["dir_exists"] = access_info["exists"]
        result["dir_readable"] = access_info["readable"]
        result["total_files"] = access_info["files_count"]
        result["pdf_files"] = access_info["pdf_count"]
        result["pdf_list"] = access_info["pdf_files"][:20]  # Max 20 anzeigen
        
        if access_info["error"]:
            result["error"] = access_info["error"]
            logger.error(f"Scan-Fehler: {access_info['error']}")
            return result
        
        # Scan durchführen
        result["new_orders"] = scan_orders_directory(orders_dir)
        result["success"] = True
        
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Unerwarteter Fehler beim Scan: {e}")
        logger.error(traceback.format_exc())
    
    logger.info(f"Scan-Ergebnis: {result}")
    logger.info("=" * 60)
    return result


# ---------------------------------------------------------------------------
# Async Background-Loop
# ---------------------------------------------------------------------------

async def watch_orders_loop(
    poll_interval: float = 10.0,
    orders_dir: Optional[Path] = None,
) -> None:
    """Endlos-Loop der periodisch den Auftragsordner scannt.

    Wird als asyncio-Task im Dashboard-Hintergrund gestartet.

    Args:
        poll_interval: Sekunden zwischen zwei Scans.
        orders_dir: Pfad zum Auftragsordner (optional, sonst default).
    """
    resolved_dir = _resolve_orders_dir(orders_dir)
    
    logger.info("=" * 60)
    logger.info("FILE-WATCHER BACKGROUND TASK GESTARTET")
    logger.info("=" * 60)
    logger.info(f"  Poll-Intervall: {poll_interval} Sekunden")
    logger.info(f"  BASE_PATH: {settings.base_path}")
    logger.info(f"  Auftragsordner: {resolved_dir}")
    logger.info(f"  Datenbank: {settings.database_path}")
    logger.info("=" * 60)
    
    # Initialer Zugriffs-Check
    logger.info("Initialer Verzeichnis-Check...")
    access_info = _check_directory_access(resolved_dir)
    if access_info["error"]:
        logger.error(f"WARNUNG: {access_info['error']}")
        logger.error("Der File-Watcher wird trotzdem gestartet und prüft periodisch.")
    
    scan_count = 0
    while True:
        scan_count += 1
        try:
            logger.debug(f"Scan #{scan_count} gestartet...")
            # Scan in einem Thread ausführen, um den Event-Loop nicht zu blockieren
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, scan_orders_directory, orders_dir)
        except asyncio.CancelledError:
            logger.info("File-Watcher wird beendet …")
            break
        except Exception as exc:
            logger.error(f"File-Watcher Fehler bei Scan #{scan_count}: {exc}")
            logger.error(traceback.format_exc())

        try:
            await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info("File-Watcher wird beendet …")
            break
