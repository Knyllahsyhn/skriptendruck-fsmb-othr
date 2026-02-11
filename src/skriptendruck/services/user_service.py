"""Service für Benutzerverwaltung mit LDAP und CSV-Fallback."""
import csv
from pathlib import Path
from typing import Dict, List, Optional, Set

from ..config import get_logger, settings
from ..models import User

logger = get_logger("user_service")


class UserService:
    """
    Service für Benutzerverwaltung.
    Unterstützt LDAP-Abfragen und CSV-Fallback.
    """
    
    def __init__(self) -> None:
        """Initialisiert den UserService."""
        self._users_cache: Dict[str, User] = {}
        self._blacklist: Set[str] = set()
        self._csv_loaded = False
        
        # Blacklist laden
        self._load_blacklist()
        
        # CSV Fallback laden wenn LDAP deaktiviert
        if not settings.ldap_enabled:
            logger.info("LDAP deaktiviert, verwende CSV-Fallback")
            self._load_users_from_csv()
    
    def get_user(self, username: str) -> Optional[User]:
        """
        Sucht einen Benutzer anhand des Usernames (RZ-Kennung).
        
        Args:
            username: RZ-Kennung (z.B. 'mus43225')
            
        Returns:
            User-Objekt oder None wenn nicht gefunden
        """
        username = username.lower()
        
        # Cache prüfen
        if username in self._users_cache:
            logger.debug(f"User {username} from cache")
            return self._users_cache[username]
        
        # LDAP Abfrage versuchen
        if settings.ldap_enabled:
            user = self._query_ldap(username)
            if user:
                # Blacklist prüfen
                user.is_blocked = username in self._blacklist
                self._users_cache[username] = user
                return user
        
        # CSV Fallback
        if username in self._users_cache:
            return self._users_cache[username]
        
        logger.warning(f"User {username} not found")
        return None
    
    def get_user_by_name(self, first_name: str, last_name: str) -> Optional[User]:
        """
        Sucht einen Benutzer anhand des Namens.
        
        Args:
            first_name: Vorname
            last_name: Nachname
            
        Returns:
            User-Objekt oder None wenn nicht gefunden
        """
        first_name = first_name.lower()
        last_name = last_name.lower()
        
        # Durchsuche Cache
        for user in self._users_cache.values():
            if (user.first_name.lower() == first_name and 
                user.last_name.lower() == last_name):
                return user
        
        # Bei LDAP: erweiterte Suche möglich
        if settings.ldap_enabled:
            # TODO: LDAP-Suche nach Namen implementieren
            pass
        
        return None

    @staticmethod
    def _ensure_ldap_filter_parens(filter_str: str) -> str:
        """
        Stellt sicher, dass ein LDAP-Filter in Klammern steht.
        Active Directory erfordert Filter im Format (attribut=wert).
        
        Args:
            filter_str: Filter-String, z.B. 'samAccountName=abc12345'
            
        Returns:
            Filter mit Klammern, z.B. '(samAccountName=abc12345)'
        """
        filter_str = filter_str.strip()
        if not filter_str.startswith("("):
            filter_str = f"({filter_str})"
        return filter_str
    
    def _query_ldap(self, username: str) -> Optional[User]:
        """
        Führt eine LDAP-Abfrage durch (Windows-kompatibel mit ldap3).
        Angepasst für HS Regensburg Active Directory.
        
        Args:
            username: RZ-Kennung (z.B. 'abc12345')
            
        Returns:
            User-Objekt oder None
        """
        try:
            from ldap3 import Server, Connection, ALL, Tls, SUBTREE
            import ssl
            
            if not settings.ldap_server or not settings.ldap_base_dn:
                logger.error("LDAP nicht konfiguriert")
                return None
            
            # TLS/SSL Konfiguration für LDAPS
            tls_configuration = None
            if settings.ldap_use_ssl:
                try:
                    tls_configuration = Tls(
                        validate=ssl.CERT_REQUIRED,
                        version=ssl.PROTOCOL_TLSv1_2,
                    )
                except Exception as tls_err:
                    logger.warning(f"TLS strikt fehlgeschlagen: {tls_err}, Fallback CERT_NONE")
                    tls_configuration = Tls(validate=ssl.CERT_NONE)
            
            # LDAP Server initialisieren
            server = Server(
                settings.ldap_server,
                port=settings.ldap_port,
                use_ssl=settings.ldap_use_ssl,
                tls=tls_configuration,
                get_info=ALL,
                connect_timeout=10,
            )

            # Verbindung aufbauen (ohne SAFE_SYNC – wie im Test-Skript)
            if settings.ldap_bind_dn and settings.ldap_bind_password:
                conn = Connection(
                    server,
                    user=settings.ldap_bind_dn,
                    password=settings.ldap_bind_password,
                    auto_bind=True,
                    raise_exceptions=True,
                )
            else:
                conn = Connection(server, auto_bind=True, raise_exceptions=True)

            # Search-Filter bauen und Klammern sicherstellen
            raw_filter = settings.ldap_search_filter.format(username=username)
            search_filter = self._ensure_ldap_filter_parens(raw_filter)

            logger.debug(f"LDAP search: base={settings.ldap_base_dn}, filter={search_filter}")
            
            # Attribute die wir benötigen
            attributes = [
                "givenName",      # Vorname
                "sn",             # Nachname (surname)
                "mail",           # E-Mail
                "department",     # Abteilung/Fakultät
                "samAccountName", # Username
            ]
            
            conn.search(
                search_base=settings.ldap_base_dn,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=attributes,
            )
            
            if conn.entries:
                entry = conn.entries[0]
                
                # Attribute extrahieren (ldap3 gibt direkt Strings zurück)
                first_name = str(entry.givenName.value) if hasattr(entry, 'givenName') else ""
                last_name = str(entry.sn.value) if hasattr(entry, 'sn') else ""
                email = str(entry.mail.value) if hasattr(entry, 'mail') else ""
                department = str(entry.department.value) if hasattr(entry, 'department') else ""
                
                # Bei Listen den ersten Wert nehmen
                if isinstance(first_name, list):
                    first_name = first_name[0] if first_name else ""
                if isinstance(last_name, list):
                    last_name = last_name[0] if last_name else ""
                if isinstance(email, list):
                    email = email[0] if email else ""
                if isinstance(department, list):
                    department = department[0] if department else ""
                
                # Fakultät aus Department extrahieren
                faculty_code = self._get_faculty_code(department)
                
                user = User(
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    faculty=faculty_code,
                    email=email if email else None,
                )
                
                logger.info(f"User {username} found via LDAP: {user.full_name}")
                conn.unbind()
                return user

            logger.info(f"LDAP: Kein Ergebnis für {username}")
            conn.unbind()
            
        except ImportError:
            logger.error("ldap3 nicht installiert - bitte 'poetry install' ausführen")
        except Exception as e:
            logger.error(f"LDAP-Fehler für {username}: {e}")
        
        return None
    
    def _load_users_from_csv(self) -> None:
        """Lädt Benutzer aus CSV-Datei (Fallback)."""
        csv_path = settings.users_csv_path
        
        if not csv_path.exists():
            logger.warning(f"CSV-Datei nicht gefunden: {csv_path}")
            return
        
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                # Format: username firstname lastname faculty
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    
                    parts = line.split()
                    if len(parts) >= 4:
                        username = parts[0].lower()
                        first_name = parts[1]
                        last_name = parts[2]
                        faculty = parts[3]
                        
                        user = User(
                            username=username,
                            first_name=first_name,
                            last_name=last_name,
                            faculty=faculty,
                            is_blocked=username in self._blacklist,
                        )
                        
                        self._users_cache[username] = user
            
            logger.info(f"Loaded {len(self._users_cache)} users from CSV")
            self._csv_loaded = True
            
        except Exception as e:
            logger.error(f"Fehler beim Laden der CSV: {e}")
    
    def _load_blacklist(self) -> None:
        """Lädt die Blacklist."""
        blacklist_path = settings.blacklist_path
        
        if not blacklist_path.exists():
            logger.info(f"Keine Blacklist gefunden: {blacklist_path}")
            return
        
        try:
            with open(blacklist_path, "r", encoding="utf-8") as f:
                for line in f:
                    username = line.strip().lower()
                    if username and not username.startswith("#"):
                        self._blacklist.add(username)
            
            logger.info(f"Loaded {len(self._blacklist)} blocked users")
            
        except Exception as e:
            logger.error(f"Fehler beim Laden der Blacklist: {e}")
    
    def is_blocked(self, username: str) -> bool:
        """
        Prüft ob ein Benutzer auf der Blacklist steht.
        
        Args:
            username: RZ-Kennung
            
        Returns:
            True wenn blockiert
        """
        return username.lower() in self._blacklist
    
    def _get_faculty_code(self, faculty_name: str) -> str:
        """
        Wandelt einen Fakultätsnamen in einen Code um.
        
        Args:
            faculty_name: Fakultätsname (z.B. "Maschinenbau")
            
        Returns:
            Fakultätscode (z.B. "M")
        """
        # Mapping von Fakultätsnamen zu Codes
        faculty_map = {
            "maschinenbau": "M",
            "elektrotechnik": "E",
            "informatik": "I",
            "bauingenieurwesen": "B",
            "architektur": "A",
            "betriebswirtschaft": "BW",
            # Weitere Fakultäten hinzufügen
        }
        
        faculty_lower = faculty_name.lower()
        for key, code in faculty_map.items():
            if key in faculty_lower:
                return code
        
        # Default: Ersten Buchstaben nehmen
        return faculty_name[0].upper() if faculty_name else "?"
