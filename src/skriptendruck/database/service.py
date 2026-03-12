"""Datenbank-Service für SQLAlchemy-Operationen."""
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_logger, settings
from ..models import Order, OrderStatus
from .models import Base, BillingRecord, OrderRecord

logger = get_logger("database")


class DatabaseService:
    """Service für Datenbank-Operationen.

    Verwendet ein Singleton-Pattern pro db_path, sodass für denselben
    Datenbankpfad immer dieselbe Engine/Session-Factory verwendet wird.
    ``Base.metadata.create_all`` wird nur einmal pro Pfad ausgeführt.
    """

    _instances: Dict[str, "DatabaseService"] = {}
    _lock = threading.Lock()

    @staticmethod
    def _resolve_db_path(db_path: Optional[Path]) -> Path:
        """
        Ermittelt den absoluten Datenbankpfad.
        
        - Wenn db_path explizit angegeben wird, wird dieser verwendet
        - Sonst wird settings.database_path verwendet (standardmäßig absolut)
        - Bei relativem Pfad wird das Projekt-Root als Basis verwendet
        """
        from ..config.settings import PROJECT_ROOT
        
        if db_path is None:
            db_path = settings.database_path
        
        # Sicherstellen, dass der Pfad absolut ist
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        
        return db_path

    def __new__(cls, db_path: Optional[Path] = None) -> "DatabaseService":
        resolved_path = cls._resolve_db_path(db_path)

        key = str(resolved_path)
        with cls._lock:
            if key not in cls._instances:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instances[key] = instance
            return cls._instances[key]

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """
        Initialisiert den DatabaseService.

        Args:
            db_path: Pfad zur SQLite-Datenbank (optional)
        """
        if getattr(self, "_initialized", False):
            return

        self.db_path = self._resolve_db_path(db_path)
        
        # Sicherstellen, dass das Verzeichnis existiert
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            echo=False,
            pool_pre_ping=True,
        )
        self.SessionLocal = sessionmaker(bind=self.engine)

        # Tabellen erstellen falls nicht vorhanden – nur einmal
        Base.metadata.create_all(self.engine)
        logger.info(f"Datenbank initialisiert: {self.db_path}")
        self._initialized = True
    
    def save_order(self, order: Order) -> OrderRecord:
        """
        Speichert einen Auftrag in der Datenbank.
        
        Args:
            order: Order-Objekt
            
        Returns:
            OrderRecord aus der Datenbank
        """
        with self.SessionLocal() as session:
            # OrderRecord aus Order-Objekt erstellen
            record = OrderRecord(
                order_id=order.order_id,
                filename=order.filename,
                username=order.user.username if order.user else order.parsed_username,
                first_name=order.user.first_name if order.user else None,
                last_name=order.user.last_name if order.user else None,
                faculty=order.user.faculty if order.user else None,
                page_count=order.page_count,
                is_password_protected=order.is_password_protected,
                color_mode=order.color_mode.value if order.color_mode else None,
                binding_type=order.binding_type.value if order.binding_type else None,
                binding_size_mm=(
                    order.price_calculation.binding_size_mm 
                    if order.price_calculation else None
                ),
                price_per_page=(
                    order.price_calculation.price_per_page 
                    if order.price_calculation else None
                ),
                pages_price=(
                    order.price_calculation.pages_price 
                    if order.price_calculation else None
                ),
                binding_price=(
                    order.price_calculation.binding_price 
                    if order.price_calculation else None
                ),
                total_price=(
                    order.price_calculation.total_price 
                    if order.price_calculation else None
                ),
                price_after_deposit=(
                    order.price_calculation.price_after_deposit 
                    if order.price_calculation else None
                ),
                status=order.status.value,
                error_message=order.error_message,
                created_at=order.created_at,
                processed_at=order.processed_at,
                operator=order.operator,
                original_filepath=str(order.filepath) if order.filepath else None,
                coversheet_path=str(order.coversheet_path) if order.coversheet_path else None,
                merged_pdf_path=str(order.merged_pdf_path) if order.merged_pdf_path else None,
            )
            
            session.add(record)
            session.commit()
            session.refresh(record)
            
            logger.info(f"Order #{order.order_id} gespeichert in Datenbank")
            return record
    
    def save_orders_batch(self, orders: List[Order]) -> List[OrderRecord]:
        """
        Speichert mehrere Aufträge auf einmal.
        
        Args:
            orders: Liste von Order-Objekten
            
        Returns:
            Liste von OrderRecords
        """
        records = []
        for order in orders:
            try:
                record = self.save_order(order)
                records.append(record)
            except Exception as e:
                logger.error(f"Fehler beim Speichern von Order #{order.order_id}: {e}")
        
        return records
    
    def get_order_by_id(self, order_id: int) -> Optional[OrderRecord]:
        """
        Lädt einen Auftrag anhand der Order-ID.
        
        Args:
            order_id: Order-ID
            
        Returns:
            OrderRecord oder None
        """
        with self.SessionLocal() as session:
            stmt = select(OrderRecord).where(OrderRecord.order_id == order_id)
            return session.scalar(stmt)
    
    def get_orders_by_username(self, username: str) -> List[OrderRecord]:
        """
        Lädt alle Aufträge eines Benutzers.
        
        Args:
            username: RZ-Kennung
            
        Returns:
            Liste von OrderRecords
        """
        with self.SessionLocal() as session:
            stmt = select(OrderRecord).where(OrderRecord.username == username)
            return list(session.scalars(stmt))
    
    def get_orders_by_status(self, status: OrderStatus) -> List[OrderRecord]:
        """
        Lädt alle Aufträge mit einem bestimmten Status.
        
        Args:
            status: OrderStatus
            
        Returns:
            Liste von OrderRecords
        """
        with self.SessionLocal() as session:
            stmt = select(OrderRecord).where(OrderRecord.status == status.value)
            return list(session.scalars(stmt))
    
    def get_orders_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> List[OrderRecord]:
        """
        Lädt Aufträge in einem Datumsbereich.
        
        Args:
            start_date: Start-Datum
            end_date: End-Datum
            
        Returns:
            Liste von OrderRecords
        """
        with self.SessionLocal() as session:
            stmt = select(OrderRecord).where(
                OrderRecord.created_at >= start_date,
                OrderRecord.created_at <= end_date,
            )
            return list(session.scalars(stmt))
    
    def create_billing_record(self, order: Order) -> Optional[BillingRecord]:
        """
        Erstellt einen Abrechnungsdatensatz für einen erfolgreichen Auftrag.
        
        Args:
            order: Order-Objekt
            
        Returns:
            BillingRecord oder None
        """
        if not order.user or not order.price_calculation:
            logger.warning(f"Kann keine Abrechnung für Order #{order.order_id} erstellen")
            return None
        
        with self.SessionLocal() as session:
            billing = BillingRecord(
                order_id=order.order_id,
                username=order.user.username,
                full_name=order.user.full_name,
                total_amount=order.price_calculation.total_price,
                paid_deposit=1.0,
                remaining_amount=order.price_calculation.price_after_deposit,
                is_paid=False,
            )
            
            session.add(billing)
            session.commit()
            session.refresh(billing)
            
            logger.info(f"Abrechnungsdatensatz für Order #{order.order_id} erstellt")
            return billing
    
    def mark_billing_as_paid(self, billing_id: int) -> bool:
        """
        Markiert eine Abrechnung als bezahlt.
        
        Args:
            billing_id: ID des Abrechnungsdatensatzes
            
        Returns:
            True bei Erfolg
        """
        with self.SessionLocal() as session:
            stmt = select(BillingRecord).where(BillingRecord.id == billing_id)
            billing = session.scalar(stmt)
            
            if billing:
                billing.is_paid = True
                billing.paid_at = datetime.now()
                session.commit()
                logger.info(f"Abrechnung #{billing_id} als bezahlt markiert")
                return True
            
            return False
    
    def get_unpaid_billings(self) -> List[BillingRecord]:
        """
        Lädt alle unbezahlten Abrechnungen.
        
        Returns:
            Liste von BillingRecords
        """
        with self.SessionLocal() as session:
            stmt = select(BillingRecord).where(BillingRecord.is_paid == False)
            return list(session.scalars(stmt))
    
    def get_statistics(self) -> dict:
        """
        Berechnet Statistiken über alle Aufträge.
        
        Returns:
            Dictionary mit Statistiken
        """
        with self.SessionLocal() as session:
            total_orders = session.query(OrderRecord).count()
            successful_orders = session.query(OrderRecord).filter(
                OrderRecord.status == OrderStatus.PROCESSED.value
            ).count()
            
            total_revenue = session.query(OrderRecord).filter(
                OrderRecord.status == OrderStatus.PROCESSED.value
            ).with_entities(
                OrderRecord.total_price
            ).all()
            
            revenue_sum = sum(r[0] for r in total_revenue if r[0] is not None)
            
            return {
                "total_orders": total_orders,
                "successful_orders": successful_orders,
                "error_orders": total_orders - successful_orders,
                "total_revenue": round(revenue_sum, 2),
            }
