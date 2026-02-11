"""Logging-Konfiguration für das Skriptendruckprogramm."""
import logging
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

# Flag um doppelte Handler zu vermeiden
_logging_configured = False


def setup_logging(
    level: str = "INFO",
    log_file: Optional[Path] = None,
    use_rich: bool = True,
) -> logging.Logger:
    """
    Konfiguriert das Logging mit optionaler Datei-Ausgabe und Rich-Formatierung.
    
    Args:
        level: Logging Level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optionaler Pfad zur Log-Datei
        use_rich: Rich Handler für schöne Console-Ausgabe verwenden
        
    Returns:
        Konfigurierter Logger
    """
    global _logging_configured

    log_level = getattr(logging, level.upper(), logging.INFO)

    # === Skriptendruck Logger ===
    logger = logging.getLogger("skriptendruck")

    # ALLE vorhandenen Handler entfernen (verhindert Duplikate)
    logger.handlers.clear()

    # Level setzen
    logger.setLevel(log_level)

    # Propagation AUS - wir wollen NICHT an den Root-Logger weiterleiten
    logger.propagate = False

    # Formatter für Datei
    file_formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Console Handler
    if use_rich:
        console = Console(stderr=True)
        console_handler = RichHandler(
            console=console,
            rich_tracebacks=True,
            tracebacks_show_locals=True,
            show_time=False,
            level=log_level,  # Level direkt im Constructor setzen
        )
    else:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(file_formatter)

    console_handler.setLevel(log_level)
    logger.addHandler(console_handler)
    
    # File Handler (optional)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG)  # Immer alle Details in Datei
        logger.addHandler(file_handler)

    # === Root Logger absichern ===
    # Falls irgendein Code den Root-Logger nutzt, soll der auch nicht
    # DEBUG-Messages auf die Console werfen
    root = logging.getLogger()
    if not root.handlers:
        # NullHandler verhindert "No handlers found" Warnung
        root.addHandler(logging.NullHandler())
    root.setLevel(logging.WARNING)
    
    _logging_configured = True
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Gibt einen Logger für ein spezifisches Modul zurück.
    
    Args:
        name: Modulname (z.B. 'user_service')
        
    Returns:
        Logger mit Name 'skriptendruck.<name>'
    """
    global _logging_configured

    # Beim allerersten Aufruf: Default-Logging einrichten
    if not _logging_configured:
        setup_logging(level="INFO")
    
    return logging.getLogger(f"skriptendruck.{name}")
