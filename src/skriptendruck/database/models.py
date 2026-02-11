"""SQLAlchemy Datenbank-Modelle für Auftrags- und Abrechnungsverwaltung."""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Basis-Klasse für alle Datenbank-Modelle."""
    pass


class OrderRecord(Base):
    """Datenbank-Modell für einen Druckauftrag."""
    
    __tablename__ = "orders"
    
    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Order-Identifikation
    order_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Benutzer-Informationen
    username: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    faculty: Mapped[Optional[str]] = mapped_column(String(10))
    
    # PDF-Informationen
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    is_password_protected: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Auftragsdaten
    color_mode: Mapped[Optional[str]] = mapped_column(String(20))  # 'sw' oder 'color'
    binding_type: Mapped[Optional[str]] = mapped_column(String(20))  # 'none', 'small', 'large', 'folder'
    binding_size_mm: Mapped[Optional[float]] = mapped_column(Float)
    
    # Preise
    price_per_page: Mapped[Optional[float]] = mapped_column(Float)
    pages_price: Mapped[Optional[float]] = mapped_column(Float)
    binding_price: Mapped[Optional[float]] = mapped_column(Float)
    total_price: Mapped[Optional[float]] = mapped_column(Float)
    price_after_deposit: Mapped[Optional[float]] = mapped_column(Float)
    
    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    
    # Metadaten
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    operator: Mapped[Optional[str]] = mapped_column(String(100))
    
    # Dateipfade (relativ oder absolut)
    original_filepath: Mapped[Optional[str]] = mapped_column(String(500))
    coversheet_path: Mapped[Optional[str]] = mapped_column(String(500))
    merged_pdf_path: Mapped[Optional[str]] = mapped_column(String(500))
    
    def __repr__(self) -> str:
        return f"<OrderRecord(id={self.id}, order_id={self.order_id}, username={self.username}, status={self.status})>"


class BillingRecord(Base):
    """Datenbank-Modell für Abrechnungsdaten (historisch/Export)."""
    
    __tablename__ = "billing"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Verknüpfung zum Auftrag
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    
    # Abrechnungsinformationen
    billing_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    username: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    
    # Finanzielle Details
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    paid_deposit: Mapped[float] = mapped_column(Float, default=1.0)
    remaining_amount: Mapped[float] = mapped_column(Float, nullable=False)
    
    # Status
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Zusatzinformationen
    notes: Mapped[Optional[str]] = mapped_column(Text)
    
    def __repr__(self) -> str:
        return f"<BillingRecord(id={self.id}, order_id={self.order_id}, username={self.username}, paid={self.is_paid})>"
