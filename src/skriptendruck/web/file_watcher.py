"""File-Watcher Service für das Dashboard.

Überwacht den Aufträgeordner (01_Auftraege) auf neue PDF-Dateien und
trägt sie automatisch als 'pending' in die Datenbank ein.
Der Watcher druckt NICHT automatisch – das passiert nur bei manuellem
'Starten' über das Dashboard.
"""
import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Set

from sqlalchemy import select

from ..config import get_logger, settings
from ..database.models import Base, OrderRecord
from ..database.service import DatabaseService

logger = get_logger("web.file_watcher")

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

    return info


# ---------------------------------------------------------------------------
# Datenbankzugriff
# ---------------------------------------------------------------------------

def _get_db() -> DatabaseService:
    """Erzeugt eine DatabaseService-Instanz mit dem konfigurierten Pfad."""
    db_path = settings.database_path
    if not db_path.is_absolute():
        db_path = settings.base_path / db_path
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

    if _is_file_known(db, filename, filepath_str):
        return None

    meta = _parse_pdf_filename(filename)
    order_id = _get_next_order_id(db)

    try:
        file_size = pdf_path.stat().st_size
    except OSError:
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
                f"Neuer Auftrag registriert: #{record.order_id} – "
                f"{filename} (user={meta['username']})"
            )
            return record
    except Exception as exc:
        logger.error(f"Fehler beim Registrieren von {filename}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Scan-Funktion (ein einzelner Durchlauf)
# ---------------------------------------------------------------------------

def scan_orders_directory(orders_dir: Optional[Path] = None) -> int:
    """Scannt das Auftragsverzeichnis und registriert neue PDFs.

    Args:
        orders_dir: Pfad zum Auftragsordner (default: settings.base_path / '01_Auftraege')

    Returns:
        Anzahl neu registrierter Aufträge.
    """
    if orders_dir is None:
        orders_dir = settings.base_path / "01_Auftraege"

    if not orders_dir.exists():
        logger.debug(f"Auftragsverzeichnis nicht vorhanden: {orders_dir}")
        return 0

    db = _get_db()
    registered = 0

    for pdf_path in sorted(orders_dir.glob("*.pdf")):
        if pdf_path.is_file():
            rec = _register_file(db, pdf_path)
            if rec is not None:
                registered += 1

    if registered:
        logger.info(f"File-Watcher: {registered} neue Aufträge registriert")
    return registered


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
    logger.info(
        f"File-Watcher gestartet (Intervall: {poll_interval}s, "
        f"Ordner: {orders_dir or settings.base_path / '01_Auftraege'})"
    )
    while True:
        try:
            # Scan in einem Thread ausführen, um den Event-Loop nicht zu blockieren
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, scan_orders_directory, orders_dir)
        except asyncio.CancelledError:
            logger.info("File-Watcher wird beendet …")
            break
        except Exception as exc:
            logger.error(f"File-Watcher Fehler: {exc}")

        try:
            await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info("File-Watcher wird beendet …")
            break
