"""Verschlüsselte Credentials-Verwaltung.

Speichert sensible Daten (LDAP-Passwort etc.) verschlüsselt auf der Platte,
sodass sie nicht im Klartext in der .env Datei stehen müssen.

Verwendung:
    # Einmalig einrichten (als Admin):
    poetry run skriptendruck credentials setup

    # Programmatisch laden:
    from .credentials import load_credentials
    creds = load_credentials()
    password = creds.get("ldap_bind_password")
"""
import base64
import hashlib
import json
import platform
from pathlib import Path
from typing import Dict, Optional

from ..config import get_logger

logger = get_logger("credentials")

# Dateinamen
CREDENTIALS_FILE = ".credentials.enc"
KEY_FILE = ".credentials.key"


def _get_credentials_dir() -> Path:
    """Gibt das Verzeichnis für Credentials zurück (neben .env)."""
    return Path(".")


def _derive_key(passphrase: str) -> bytes:
    """Leitet einen Fernet-Schlüssel aus einer Passphrase ab."""
    # PBKDF2 mit festem Salt (maschinenbezogen)
    machine_id = platform.node().encode()
    key_bytes = hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode(),
        salt=b"skriptendruck_fsmb_" + machine_id,
        iterations=100_000,
    )
    # Fernet braucht 32 Bytes, base64-encoded
    return base64.urlsafe_b64encode(key_bytes[:32])


def _get_or_create_key() -> bytes:
    """
    Lädt oder erstellt den Verschlüsselungsschlüssel.
    
    Der Schlüssel wird aus einem zufällig generierten Token abgeleitet,
    das in .credentials.key gespeichert wird.
    """
    key_path = _get_credentials_dir() / KEY_FILE
    
    if key_path.exists():
        token = key_path.read_text(encoding="utf-8").strip()
    else:
        # Neuen zufälligen Token generieren
        import secrets
        token = secrets.token_hex(32)
        key_path.write_text(token, encoding="utf-8")
        logger.info(f"Neuer Schlüssel erstellt: {key_path}")
    
    return _derive_key(token)


def save_credentials(credentials: Dict[str, str]) -> Path:
    """
    Verschlüsselt und speichert Credentials.
    
    Args:
        credentials: Dict mit Key-Value Paaren (z.B. {"ldap_bind_password": "geheim"})
        
    Returns:
        Pfad zur verschlüsselten Datei
    """
    from cryptography.fernet import Fernet
    
    key = _get_or_create_key()
    f = Fernet(key)
    
    # JSON serialisieren und verschlüsseln
    data = json.dumps(credentials, ensure_ascii=False).encode("utf-8")
    encrypted = f.encrypt(data)
    
    cred_path = _get_credentials_dir() / CREDENTIALS_FILE
    cred_path.write_bytes(encrypted)
    
    logger.info(f"Credentials verschlüsselt gespeichert: {cred_path}")
    return cred_path


def load_credentials() -> Dict[str, str]:
    """
    Lädt und entschlüsselt die gespeicherten Credentials.
    
    Returns:
        Dict mit Credentials oder leeres Dict falls nicht vorhanden
    """
    cred_path = _get_credentials_dir() / CREDENTIALS_FILE
    key_path = _get_credentials_dir() / KEY_FILE
    
    if not cred_path.exists():
        logger.debug("Keine Credentials-Datei gefunden")
        return {}
    
    if not key_path.exists():
        logger.warning("Credentials-Datei ohne Schlüssel gefunden – kann nicht entschlüsseln")
        return {}
    
    try:
        from cryptography.fernet import Fernet, InvalidToken
        
        key = _get_or_create_key()
        f = Fernet(key)
        
        encrypted = cred_path.read_bytes()
        decrypted = f.decrypt(encrypted)
        
        credentials = json.loads(decrypted.decode("utf-8"))
        logger.debug(f"Credentials geladen: {len(credentials)} Einträge")
        return credentials
        
    except ImportError:
        logger.warning("cryptography nicht installiert – Credentials können nicht geladen werden")
        return {}
    except InvalidToken:
        logger.error(
            "Credentials konnten nicht entschlüsselt werden! "
            "Schlüssel passt nicht. Bitte 'skriptendruck credentials setup' erneut ausführen."
        )
        return {}
    except Exception as e:
        logger.error(f"Fehler beim Laden der Credentials: {e}")
        return {}


def has_credentials() -> bool:
    """Prüft ob verschlüsselte Credentials vorhanden sind."""
    cred_path = _get_credentials_dir() / CREDENTIALS_FILE
    key_path = _get_credentials_dir() / KEY_FILE
    return cred_path.exists() and key_path.exists()
