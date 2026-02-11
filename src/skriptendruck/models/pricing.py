"""Datenmodelle für Preisberechnung und Bindungen."""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


class ColorMode(str, Enum):
    """Farbmodus für den Druck."""
    BLACK_WHITE = "sw"
    COLOR = "color"


class BindingType(str, Enum):
    """Typ der Bindung."""
    NONE = "none"  # Ohne Bindung
    SMALL = "small"  # Kleine Ringbindung
    LARGE = "large"  # Große Ringbindung
    FOLDER = "folder"  # Schnellhefter


class BindingSize(BaseModel):
    """Ringbindungsgröße basierend auf Seitenzahl."""
    
    min_pages: int = Field(..., description="Minimale Seitenzahl")
    max_pages: int = Field(..., description="Maximale Seitenzahl")
    size_mm: float = Field(..., description="Ringbindungsgröße in mm")
    binding_type: BindingType = Field(..., description="Typ der Bindung")
    # Optionale Zusatzinfos aus der Tabelle
    diameter_inch: Optional[str] = Field(default=None, description="Durchmesser in Zoll")
    min_sheets: Optional[int] = Field(default=None, description="Minimale Blätterzahl")
    max_sheets: Optional[int] = Field(default=None, description="Maximale Blätterzahl")
    
    def supports_pages(self, pages: int) -> bool:
        """Prüft ob diese Bindungsgröße für die Seitenzahl passt."""
        return self.min_pages <= pages <= self.max_pages


class PriceCalculation(BaseModel):
    """Repräsentiert eine Preisberechnung."""
    
    pages: int = Field(..., gt=0, description="Anzahl Seiten")
    color_mode: ColorMode = Field(..., description="Farbmodus")
    binding_type: BindingType = Field(..., description="Bindungstyp")
    
    price_per_page: float = Field(..., description="Preis pro Seite")
    binding_price: float = Field(default=0.0, description="Bindungspreis")
    binding_size_mm: Optional[float] = Field(
        default=None,
        description="Ringbindungsgröße in mm (nur bei Ringbindung)"
    )
    
    @computed_field
    @property
    def pages_price(self) -> float:
        """Berechnet den Preis für die Seiten."""
        return round(self.pages * self.price_per_page, 2)
    
    @computed_field
    @property
    def total_price(self) -> float:
        """Berechnet den Gesamtpreis."""
        return round(self.pages_price + self.binding_price, 2)
    
    @computed_field
    @property
    def price_after_deposit(self) -> float:
        """Preis nach Abzug der 1€ Anzahlung."""
        return round(max(0, self.total_price - 1.0), 2)
    
    def format_price(self, price: float) -> str:
        """Formatiert einen Preis als String."""
        return f"{price:.2f} €".replace(".", ",")
    
    @property
    def total_price_formatted(self) -> str:
        """Formatierter Gesamtpreis."""
        return self.format_price(self.total_price)
    
    @property
    def pages_price_formatted(self) -> str:
        """Formatierter Seitenpreis."""
        return self.format_price(self.pages_price)
    
    @property
    def binding_price_formatted(self) -> str:
        """Formatierter Bindungspreis."""
        return self.format_price(self.binding_price)
    
    @property
    def price_after_deposit_formatted(self) -> str:
        """Formatierter Preis nach Anzahlung."""
        return self.format_price(self.price_after_deposit)
