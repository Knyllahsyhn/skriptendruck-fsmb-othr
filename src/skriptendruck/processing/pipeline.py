"""Verarbeitungs-Pipeline für Druckaufträge."""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

from ..config import get_logger, settings
from ..database.service import DatabaseService
from ..models import BindingType, Order, OrderStatus
from ..services import FilenameParser, PdfService, PricingService, UserService
from ..services.file_organizer import FileOrganizer

logger = get_logger("pipeline")


class OrderPipeline:
    """Pipeline zur Verarbeitung von Druckaufträgen."""

    def __init__(
            self,
            db_service: Optional[DatabaseService] = None,
            file_organizer: Optional[FileOrganizer] = None,
    ) -> None:
        """Initialisiert die Pipeline."""
        self.filename_parser = FilenameParser()
        self.user_service = UserService()
        self.pdf_service = PdfService()
        self.pricing_service = PricingService()
        
        # Datenbank-Service (optional)
        self.db_service = db_service or DatabaseService()

        # FileOrganizer für Ordnerstruktur
        self.file_organizer = file_organizer or FileOrganizer()
        
        self._next_order_id = self._get_next_order_id()
    
    def _get_next_order_id(self) -> int:
        """
        Ermittelt die nächste verfügbare Order-ID aus der Datenbank.
        
        Returns:
            Nächste Order-ID
        """
        try:
            stats = self.db_service.get_statistics()
            return stats.get("total_orders", 0) + 1
        except Exception:
            return 1
    
    def discover_orders(self, orders_dir: Path) -> List[Order]:
        """
        Sucht nach PDF-Dateien im Auftragsverzeichnis.
        
        Args:
            orders_dir: Verzeichnis mit Aufträgen
            
        Returns:
            Liste von Order-Objekten
        """
        if not orders_dir.exists():
            logger.error(f"Auftragsverzeichnis nicht gefunden: {orders_dir}")
            return []
        
        orders = []
        pdf_files = list(orders_dir.glob("*.pdf"))
        
        logger.info(f"Gefunden: {len(pdf_files)} PDF-Dateien")
        
        for pdf_path in pdf_files:
            try:
                order = Order(
                    order_id=self._next_order_id,
                    filename=pdf_path.name,
                    filepath=pdf_path,
                    file_size_bytes=pdf_path.stat().st_size,
                    operator=os.getenv("USER", os.getenv("USERNAME", "unknown")),
                )
                
                self._next_order_id += 1
                orders.append(order)
                
            except Exception as e:
                logger.error(f"Fehler beim Erstellen des Orders für {pdf_path}: {e}")
        
        return orders
    
    def process_orders(
        self,
        orders: List[Order],
            output_dir: Optional[Path] = None,
        save_to_db: bool = True,
            organize_files: bool = True,
    ) -> List[Order]:
        """
        Verarbeitet eine Liste von Aufträgen.
        
        Args:
            orders: Liste der zu verarbeitenden Aufträge
            output_dir: Temporäres Arbeitsverzeichnis für Zwischendateien
            save_to_db: In Datenbank speichern
            organize_files: Dateien in Ordnerstruktur organisieren
            
        Returns:
            Liste der verarbeiteten Aufträge
        """
        # Temporäres Arbeitsverzeichnis für Deckblätter und Merge
        if output_dir is None:
            work_dir = Path(tempfile.mkdtemp(prefix="skriptendruck_"))
        else:
            work_dir = output_dir
            work_dir.mkdir(parents=True, exist_ok=True)
        
        if settings.parallel_processing and len(orders) > 1:
            processed = self._process_parallel(orders, work_dir)
        else:
            processed = self._process_sequential(orders, work_dir)

        # Dateien in Ordnerstruktur organisieren
        if organize_files:
            try:
                self.file_organizer.organize_batch(processed)
                logger.info("Dateien in Ordnerstruktur organisiert")
            except Exception as e:
                logger.error(f"Fehler beim Organisieren der Dateien: {e}")
        
        # In Datenbank speichern
        if save_to_db:
            try:
                self.db_service.save_orders_batch(processed)
                
                # Abrechnungsdatensätze für erfolgreiche Aufträge erstellen
                for order in processed:
                    if order.status == OrderStatus.PROCESSED:
                        self.db_service.create_billing_record(order)
                
                logger.info(f"{len(processed)} Aufträge in Datenbank gespeichert")
            except Exception as e:
                logger.error(f"Fehler beim Speichern in Datenbank: {e}")
        
        return processed
    
    def _process_sequential(
        self,
        orders: List[Order],
        output_dir: Path,
    ) -> List[Order]:
        """Verarbeitet Aufträge sequenziell."""
        logger.info(f"Verarbeite {len(orders)} Aufträge sequenziell")
        
        processed = []
        for order in orders:
            self.process_single_order(order, output_dir)
            processed.append(order)
        
        return processed
    
    def _process_parallel(
        self,
        orders: List[Order],
        output_dir: Path,
    ) -> List[Order]:
        """Verarbeitet Aufträge parallel."""
        logger.info(
            f"Verarbeite {len(orders)} Aufträge parallel "
            f"(max {settings.max_workers} Worker)"
        )
        
        processed = []
        
        with ThreadPoolExecutor(max_workers=settings.max_workers) as executor:
            futures = {
                executor.submit(self.process_single_order, order, output_dir): order
                for order in orders
            }
            
            for future in as_completed(futures):
                order = futures[future]
                try:
                    future.result()
                    processed.append(order)
                except Exception as e:
                    logger.error(f"Fehler bei Order {order.order_id}: {e}")
                    order.set_error(OrderStatus.ERROR_UNKNOWN, str(e))
                    processed.append(order)
        
        return processed
    
    def process_single_order(self, order: Order, output_dir: Path) -> None:
        """
        Verarbeitet einen einzelnen Auftrag.
        
        Args:
            order: Zu verarbeitender Auftrag
            output_dir: Arbeitsverzeichnis für Zwischendateien
        """
        logger.info(f"Verarbeite Order #{order.order_id}: {order.filename}")
        
        # 1. Dateinamen parsen
        self._parse_filename(order)
        
        # 2. Benutzer validieren
        if order.is_valid:
            self._validate_user(order)
        
        # 3. PDF analysieren
        if order.is_valid:
            self._analyze_pdf(order)
        
        # 4. Preis berechnen
        if order.is_valid:
            self._calculate_price(order)
        
        # 5. Deckblatt erstellen
        if order.is_valid:
            self._create_coversheet(order, output_dir)
        
        # 6. PDFs zusammenfügen
        if order.is_valid:
            self._merge_documents(order, output_dir)
        
        # Status aktualisieren
        if order.is_valid:
            order.status = OrderStatus.PROCESSED
            logger.info(f"Order #{order.order_id} erfolgreich verarbeitet")
        else:
            logger.warning(f"Order #{order.order_id} mit Fehler: {order.status.value}")
    
    def _parse_filename(self, order: Order) -> None:
        """Parst den Dateinamen."""
        try:
            username, name, color, binding, seq = self.filename_parser.parse(
                order.filename
            )
            
            order.parsed_username = username
            order.parsed_name = name
            order.color_mode = color
            order.binding_type = binding
            order.sequence_number = seq
            
            if not username and not name:
                order.set_error(
                    OrderStatus.ERROR_INVALID_FILENAME,
                    "Konnte Benutzername/Name nicht extrahieren"
                )
            
        except Exception as e:
            logger.error(f"Fehler beim Parsen des Dateinamens: {e}")
            order.set_error(OrderStatus.ERROR_INVALID_FILENAME, str(e))
    
    def _validate_user(self, order: Order) -> None:
        """Validiert den Benutzer."""
        try:
            user = None
            
            # Zuerst mit RZ-Kennung versuchen
            if order.parsed_username:
                user = self.user_service.get_user(order.parsed_username)
            
            # Fallback: Mit Namen versuchen (nur wenn kein Username vorhanden)
            if not user and order.parsed_name:
                # TODO: Bessere Namen-Suche implementieren
                logger.warning(f"User nicht gefunden: {order.parsed_name}")
            
            if not user:
                order.set_error(
                    OrderStatus.ERROR_USER_NOT_FOUND,
                    f"Benutzer nicht gefunden: {order.parsed_username or order.parsed_name}"
                )
                return
            
            # Blacklist prüfen
            if user.is_blocked:
                order.set_error(
                    OrderStatus.ERROR_USER_BLOCKED,
                    f"Benutzer ist blockiert: {user.username}"
                )
                return
            
            order.user = user
            order.status = OrderStatus.VALIDATED
            logger.info(f"Benutzer validiert: {user}")
            
        except Exception as e:
            logger.error(f"Fehler bei Benutzervalidierung: {e}")
            order.set_error(OrderStatus.ERROR_UNKNOWN, str(e))
    
    def _analyze_pdf(self, order: Order) -> None:
        """Analysiert das PDF."""
        try:
            page_count, is_protected = self.pdf_service.get_page_count(order.filepath)
            
            if is_protected:
                order.set_error(
                    OrderStatus.ERROR_PASSWORD_PROTECTED,
                    "PDF ist passwortgeschützt"
                )
                return
            
            if page_count is None:
                order.set_error(
                    OrderStatus.ERROR_UNKNOWN,
                    "Konnte Seitenzahl nicht ermitteln"
                )
                return
            
            order.page_count = page_count
            order.is_password_protected = is_protected
            
            # Seitenzahl validieren
            is_valid, error_msg = self.pricing_service.validate_page_count(
                page_count,
                order.binding_type or BindingType.NONE
            )
            
            if not is_valid:
                if "wenig" in error_msg.lower():
                    order.set_error(OrderStatus.ERROR_TOO_FEW_PAGES, error_msg)
                else:
                    order.set_error(OrderStatus.ERROR_TOO_MANY_PAGES, error_msg)
            
        except Exception as e:
            logger.error(f"Fehler bei PDF-Analyse: {e}")
            order.set_error(OrderStatus.ERROR_UNKNOWN, str(e))
    
    def _calculate_price(self, order: Order) -> None:
        """Berechnet den Preis."""
        try:
            if not order.page_count or not order.color_mode or not order.binding_type:
                raise ValueError("Fehlende Informationen für Preisberechnung")
            
            price_calc = self.pricing_service.calculate_price(
                pages=order.page_count,
                color_mode=order.color_mode,
                binding_type=order.binding_type,
            )
            
            order.price_calculation = price_calc
            logger.info(f"Preis berechnet: {price_calc.total_price_formatted}")
            
        except Exception as e:
            logger.error(f"Fehler bei Preisberechnung: {e}")
            order.set_error(OrderStatus.ERROR_UNKNOWN, str(e))
    
    def _create_coversheet(self, order: Order, output_dir: Path) -> None:
        """Erstellt das Deckblatt."""
        try:
            coversheet_path = output_dir / f"{order.order_id:04d}_coversheet.pdf"
            
            if self.pdf_service.create_coversheet(order, coversheet_path):
                order.coversheet_path = coversheet_path
            else:
                order.set_error(OrderStatus.ERROR_UNKNOWN, "Deckblatt konnte nicht erstellt werden")
            
        except Exception as e:
            logger.error(f"Fehler beim Erstellen des Deckblatts: {e}")
            order.set_error(OrderStatus.ERROR_UNKNOWN, str(e))
    
    def _merge_documents(self, order: Order, output_dir: Path) -> None:
        """Fügt Deckblatt und Dokument zusammen."""
        try:
            if not order.coversheet_path:
                raise ValueError("Kein Deckblatt vorhanden")
            
            merged_path = output_dir / f"{order.order_id:04d}_{order.filename}"
            
            if self.pdf_service.merge_pdfs(
                coversheet_path=order.coversheet_path,
                document_path=order.filepath,
                output_path=merged_path,
                    add_empty_page=True,  # Leere Seite wie im Original (pdftk)
            ):
                order.merged_pdf_path = merged_path
            else:
                order.set_error(OrderStatus.ERROR_UNKNOWN, "PDFs konnten nicht zusammengefügt werden")
            
        except Exception as e:
            logger.error(f"Fehler beim Zusammenfügen der PDFs: {e}")
            order.set_error(OrderStatus.ERROR_UNKNOWN, str(e))
