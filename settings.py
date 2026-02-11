"""
Konfigurationsmanagement mit Pydantic Settings.
Unterstützt .env Dateien und Umgebungsvariablen.
Sensible Daten (Passwörter) werden aus verschlüsselter .credentials.enc geladen.
"""
from pathlib import Path
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Zentrale Konfiguration für das Skriptendruckprogramm."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # Pfade
    base_path: Path = Field(
        default=Path("H:/stud/fsmb/03_Dienste/01_Skriptendruck"),
        description="Basispfad für Ordnerstruktur (01_Auftraege, 02_Druckfertig, etc.)"
    )
    
    # LDAP Konfiguration
    ldap_enabled: bool = Field(default=False, description="LDAP Authentifizierung aktiviert")
    ldap_server: Optional[str] = Field(default=None, description="LDAP Server (ohne ldaps://)")
    ldap_port: int = Field(default=636, description="LDAP Port (636 für LDAPS)")
    ldap_use_ssl: bool = Field(default=True, description="SSL/TLS verwenden")
    ldap_base_dn: Optional[str] = Field(
        default=None,
        description="LDAP Base DN, z.B. 'dc=hs-regensburg,dc=de'"
    )
    ldap_bind_dn: Optional[str] = Field(
        default=None, 
        description="LDAP Bind DN (z.B. 'abc12345@hs-regensburg.de')"
    )
    ldap_bind_password: Optional[str] = Field(default=None, description="LDAP Bind Password")
    ldap_search_filter: str = Field(
        default="samAccountName={username}",
        description="LDAP Search Filter Template"
    )
    
    # Fallback Dateien
    users_csv_path: Path = Field(
        default=Path("data/users_fallback.csv"),
        description="Fallback CSV für Benutzerdaten"
    )
    blacklist_path: Path = Field(
        default=Path("data/blacklist.txt"),
        description="Blacklist Datei"
    )
    
    # Preise (in Euro)
    price_sw: float = Field(default=0.04, description="Seitenpreis Schwarz-Weiß")
    price_color: float = Field(default=0.10, description="Seitenpreis Farbe")
    price_binding_small: float = Field(default=1.00, description="Ringbindung klein")
    price_binding_large: float = Field(default=1.50, description="Ringbindung groß")
    price_folder: float = Field(default=0.50, description="Schnellhefter")
    
    # Seitengrenzen
    min_pages: int = Field(default=1, description="Minimale Seitenzahl")
    max_pages_small_binding: int = Field(default=300, description="Max Seiten kleine Bindung")
    max_pages_large_binding: int = Field(default=660, description="Max Seiten große Bindung")
    
    # Bindungsgrößen Tabelle
    binding_sizes_path: Path = Field(
        default=Path("data/binding_sizes.json"),
        description="JSON mit Ringbindungsgrößen-Tabelle"
    )
    
    # Excel Export
    excel_export_path: Path = Field(
        default=Path("H:/stud/fsmb/03_Dienste/01_Skriptendruck/Export"),
        description="Verzeichnis für Excel-Exporte (Abrechnungs-/Auftragslisten)"
    )
    
    # Datenbank
    database_path: Path = Field(
        default=Path("skriptendruck.db"),
        description="Pfad zur SQLite-Datenbank"
    )
    use_database: bool = Field(
        default=True,
        description="Datenbank-Speicherung aktivieren"
    )
    
    # Verarbeitungs-Optionen
    parallel_processing: bool = Field(
        default=True,
        description="Parallele Verarbeitung aktivieren"
    )
    max_workers: int = Field(
        default=4,
        description="Maximale Anzahl paralleler Worker"
    )
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging Level")
    log_file: Optional[Path] = Field(default=None, description="Logdatei (optional)")
    
    @model_validator(mode="after")
    def _load_encrypted_credentials(self) -> "Settings":
        """Lädt verschlüsselte Credentials und füllt fehlende Felder."""
        # Nur laden wenn Passwort nicht bereits gesetzt (z.B. via .env oder Umgebung)
        if self.ldap_bind_password:
            return self
        
        try:
            from ..config.credentials import load_credentials
            creds = load_credentials()
            
            if creds.get("ldap_bind_password"):
                self.ldap_bind_password = creds["ldap_bind_password"]
            if creds.get("ldap_bind_dn") and not self.ldap_bind_dn:
                self.ldap_bind_dn = creds["ldap_bind_dn"]
                
        except Exception:
            pass  # Kein Fehler wenn Credentials nicht verfügbar
        
        return self
    
    def get_excel_export_directory(self) -> Path:
        """Gibt das Excel-Export-Verzeichnis zurück, erstellt es bei Bedarf."""
        self.excel_export_path.mkdir(parents=True, exist_ok=True)
        return self.excel_export_path


# Globale Settings-Instanz
settings = Settings()
