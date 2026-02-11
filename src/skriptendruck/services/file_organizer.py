"""Service für Dateiverwaltung und Ordnerstruktur.

Verwaltet die Ordnerstruktur analog zum Original-MATLAB-System (moveDocs.m),
verschiebt verarbeitete PDFs in die richtigen Zielordner und erstellt
Backups der Originaldateien.
"""
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import get_logger, settings
from ..models import ColorMode, Order, OrderStatus

logger = get_logger("file_organizer")


class FileOrganizer:
    """
    Organisiert die Ordnerstruktur für Druckaufträge.
    
    Struktur:
        01_Auftraege/                    ← Input
        02_Druckfertig/
           sw/                           ← SW-Jobs mit Deckblatt
              gedruckt/                  ← Erledigte SW-Jobs
           farbig/                       ← Farb-Jobs mit Deckblatt
              gedruckt/                  ← Erledigte Farb-Jobs
        03_Originale/                    ← Backup mit Zeitstempel
           2026-01-16_12-38/
        04_Fehler/
           benutzer_nicht_gefunden/
           zu_viele_seiten/
           zu_wenig_seiten/
           passwortgeschuetzt/
           gesperrt/
           sonstige/
        05_Manuell/                      ← Manuelle Aufträge
    """

    # Ordnernamen
    DIR_INPUT = "01_Auftraege"
    DIR_PRINT = "02_Druckfertig"
    DIR_PRINT_SW = "sw"
    DIR_PRINT_COLOR = "farbig"
    DIR_PRINTED = "gedruckt"
    DIR_ORIGINALS = "03_Originale"
    DIR_ERRORS = "04_Fehler"
    DIR_MANUAL = "05_Manuell"

    # Fehler-Unterordner mit Mapping auf OrderStatus
    ERROR_DIRS = {
        OrderStatus.ERROR_USER_NOT_FOUND: "benutzer_nicht_gefunden",
        OrderStatus.ERROR_USER_BLOCKED: "gesperrt",
        OrderStatus.ERROR_TOO_FEW_PAGES: "zu_wenig_seiten",
        OrderStatus.ERROR_TOO_MANY_PAGES: "zu_viele_seiten",
        OrderStatus.ERROR_PASSWORD_PROTECTED: "passwortgeschuetzt",
        OrderStatus.ERROR_INVALID_FILENAME: "sonstige",
        OrderStatus.ERROR_UNKNOWN: "sonstige",
    }

    def __init__(self, base_path: Optional[Path] = None) -> None:
        """
        Initialisiert den FileOrganizer.
        
        Args:
            base_path: Basispfad für die Ordnerstruktur (Standard: settings.base_path)
        """
        self.base_path = base_path or settings.base_path

    def ensure_directory_structure(self) -> None:
        """
        Stellt sicher, dass die komplette Ordnerstruktur existiert.
        Erstellt fehlende Ordner automatisch (wie checkFoldersDocs.m).
        """
        directories = [
            # Input
            self.get_input_dir(),
            # Druckfertig
            self.get_print_dir(ColorMode.BLACK_WHITE),
            self.get_print_dir(ColorMode.BLACK_WHITE) / self.DIR_PRINTED,
            self.get_print_dir(ColorMode.COLOR),
            self.get_print_dir(ColorMode.COLOR) / self.DIR_PRINTED,
            # Originale
            self.get_originals_dir(),
            # Fehler-Unterordner
            *(self.get_error_dir(status) for status in self.ERROR_DIRS),
            # Manuell
            self.get_manual_dir(),
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Verzeichnis sichergestellt: {directory}")

        logger.info("Ordnerstruktur verifiziert")

    def get_input_dir(self) -> Path:
        """Gibt den Eingabe-Ordner zurück."""
        return self.base_path / self.DIR_INPUT

    def get_print_dir(self, color_mode: ColorMode) -> Path:
        """Gibt den Druckfertig-Ordner für den jeweiligen Farbmodus zurück."""
        subdir = self.DIR_PRINT_COLOR if color_mode == ColorMode.COLOR else self.DIR_PRINT_SW
        return self.base_path / self.DIR_PRINT / subdir

    def get_originals_dir(self) -> Path:
        """Gibt den Originale-Basisordner zurück."""
        return self.base_path / self.DIR_ORIGINALS

    def get_originals_batch_dir(self, timestamp: Optional[datetime] = None) -> Path:
        """
        Gibt den Originale-Ordner für den aktuellen Batch zurück.
        Format: 03_Originale/2026-01-16_12-38/
        """
        ts = timestamp or datetime.now()
        batch_name = ts.strftime("%Y-%m-%d_%H-%M")
        return self.get_originals_dir() / batch_name

    def get_error_dir(self, status: OrderStatus) -> Path:
        """Gibt den Fehler-Unterordner für einen bestimmten Status zurück."""
        subdir = self.ERROR_DIRS.get(status, "sonstige")
        return self.base_path / self.DIR_ERRORS / subdir

    def get_manual_dir(self) -> Path:
        """Gibt den Manuell-Ordner zurück."""
        return self.base_path / self.DIR_MANUAL

    def move_successful_order(self, order: Order) -> Optional[Path]:
        """
        Verschiebt einen erfolgreich verarbeiteten Auftrag (merged PDF)
        in den passenden Druckfertig-Ordner.
        
        Args:
            order: Verarbeiteter Auftrag
            
        Returns:
            Neuer Pfad der Datei oder None bei Fehler
        """
        if not order.merged_pdf_path or not order.merged_pdf_path.exists():
            logger.error(f"Order #{order.order_id}: Kein merged PDF vorhanden")
            return None

        try:
            color_mode = order.color_mode or ColorMode.BLACK_WHITE
            target_dir = self.get_print_dir(color_mode)
            target_dir.mkdir(parents=True, exist_ok=True)

            # Dateiname: OrderID_Originalname.pdf
            target_name = f"{order.order_id:04d}_{order.filename}"
            target_path = target_dir / target_name

            shutil.move(str(order.merged_pdf_path), str(target_path))
            logger.info(f"Order #{order.order_id} → {target_path}")
            return target_path

        except Exception as e:
            logger.error(f"Fehler beim Verschieben von Order #{order.order_id}: {e}")
            return None

    def move_failed_order(self, order: Order) -> Optional[Path]:
        """
        Verschiebt einen fehlerhaften Auftrag in den passenden Fehler-Ordner.
        
        Args:
            order: Fehlerhafter Auftrag
            
        Returns:
            Neuer Pfad der Datei oder None bei Fehler
        """
        if not order.filepath or not order.filepath.exists():
            logger.warning(f"Order #{order.order_id}: Quelldatei nicht mehr vorhanden")
            return None

        try:
            target_dir = self.get_error_dir(order.status)
            target_dir.mkdir(parents=True, exist_ok=True)

            target_name = f"{order.order_id:04d}_{order.filename}"
            target_path = target_dir / target_name

            shutil.copy2(str(order.filepath), str(target_path))
            logger.info(f"Order #{order.order_id} (Fehler) → {target_path}")
            return target_path

        except Exception as e:
            logger.error(f"Fehler beim Verschieben von Order #{order.order_id}: {e}")
            return None

    def backup_original(self, order: Order, batch_dir: Path) -> Optional[Path]:
        """
        Erstellt ein Backup der Originaldatei im Backup-Ordner.
        
        Args:
            order: Auftrag
            batch_dir: Ziel-Batch-Ordner (mit Zeitstempel)
            
        Returns:
            Pfad der Backup-Datei oder None bei Fehler
        """
        if not order.filepath or not order.filepath.exists():
            return None

        try:
            batch_dir.mkdir(parents=True, exist_ok=True)
            target_path = batch_dir / order.filename

            shutil.copy2(str(order.filepath), str(target_path))
            logger.debug(f"Backup: {order.filename} → {batch_dir.name}/")
            return target_path

        except Exception as e:
            logger.error(f"Fehler beim Backup von {order.filename}: {e}")
            return None

    def cleanup_input(self, order: Order) -> bool:
        """
        Entfernt die Originaldatei aus dem Eingabe-Ordner nach erfolgreicher
        Verarbeitung und Backup.
        
        Args:
            order: Verarbeiteter Auftrag
            
        Returns:
            True bei Erfolg
        """
        if not order.filepath or not order.filepath.exists():
            return True  # Bereits entfernt

        try:
            order.filepath.unlink()
            logger.debug(f"Eingabedatei entfernt: {order.filename}")
            return True
        except Exception as e:
            logger.error(f"Fehler beim Entfernen von {order.filename}: {e}")
            return False

    def organize_order(self, order: Order, batch_dir: Path) -> None:
        """
        Organisiert einen einzelnen Auftrag komplett:
        1. Backup des Originals
        2. Verschieben in Zielordner (Druckfertig oder Fehler)
        3. Aufräumen des Eingabe-Ordners
        
        Args:
            order: Verarbeiteter Auftrag
            batch_dir: Batch-Ordner für Originale-Backup
        """
        # 1. Backup des Originals
        self.backup_original(order, batch_dir)

        # 2. In Zielordner verschieben
        if order.status == OrderStatus.PROCESSED:
            new_path = self.move_successful_order(order)
            if new_path:
                order.merged_pdf_path = new_path
        elif order.is_error:
            self.move_failed_order(order)

        # 3. Original aus Eingabe entfernen
        self.cleanup_input(order)

    def organize_batch(self, orders: list[Order]) -> None:
        """
        Organisiert einen kompletten Batch von Aufträgen.
        
        Args:
            orders: Liste verarbeiteter Aufträge
        """
        if not orders:
            return

        # Ordnerstruktur sicherstellen
        self.ensure_directory_structure()

        # Batch-Ordner für Originale erstellen
        batch_dir = self.get_originals_batch_dir()

        for order in orders:
            try:
                self.organize_order(order, batch_dir)
            except Exception as e:
                logger.error(f"Fehler beim Organisieren von Order #{order.order_id}: {e}")

        # Deckblatt-Einzeldateien aufräumen (werden nicht mehr gebraucht)
        for order in orders:
            if order.coversheet_path and order.coversheet_path.exists():
                try:
                    order.coversheet_path.unlink()
                except Exception:
                    pass

        logger.info(f"Batch organisiert: {len(orders)} Aufträge")
