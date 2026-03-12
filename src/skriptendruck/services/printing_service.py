"""
Druck-Service mit SumatraPDF Silent-Print.

Druckt PDFs über SumatraPDF im Silent-Modus. PaperCut ordnet
die Druckaufträge automatisch dem Service-Account zu, unter dem
das Dashboard läuft (z.B. ``skriptendruck-service``).

**Druckablauf:**
1. Dashboard läuft als Windows-Service unter ``skriptendruck-service``
2. SumatraPDF sendet Druckauftrag an Drucker
3. PaperCut erkennt den User automatisch und verbucht den Auftrag

Siehe ``docs/WINDOWS_SERVICE_SETUP.md`` für die Service-Einrichtung.
"""

import subprocess
from pathlib import Path
import logging

from ..config import settings
from ..models import ColorMode

logger = logging.getLogger("printing")


class PrintingService:
    """Service zum Senden von Druckaufträgen an einen konfigurierten Drucker.
    
    Verwendet SumatraPDF für Silent-Print. PaperCut ordnet die Aufträge
    automatisch dem User zu, unter dem der Service läuft.
    """

    def __init__(self):
        self._sumatra_path: Path | None = None
        self._validate_sumatra()

    # ------------------------------------------------------------------
    # Initialisierung
    # ------------------------------------------------------------------

    def _validate_sumatra(self) -> None:
        """Validiert, ob SumatraPDF verfügbar ist."""
        sumatra = Path(settings.sumatra_pdf_path)
        
        if sumatra.exists():
            self._sumatra_path = sumatra
            logger.info(f"Druck-Backend: SumatraPDF ({sumatra})")
        else:
            logger.warning(
                f"SumatraPDF nicht gefunden unter: {sumatra} – "
                f"Drucken wird nicht funktionieren!"
            )

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def print_order(self, order) -> bool:
        """Druckt ein fertiges Order-Objekt.

        Wählt den Drucker basierend auf dem Farbmodus und sendet
        das PDF über SumatraPDF.
        """
        if not order.merged_pdf_path or not order.merged_pdf_path.exists():
            logger.error(f"Keine druckfähige Datei für Order {order.order_id}")
            return False

        # Drucker wählen basierend auf Farbmodus
        printer = (
            settings.printer_color
            if order.color_mode == ColorMode.COLOR
            else settings.printer_sw
        )

        return self.send_to_printer(order.merged_pdf_path, printer)

    def send_to_printer(self, pdf_path: Path, printer_name: str) -> bool:
        """Sendet eine PDF-Datei an den angegebenen Drucker.

        Verwendet SumatraPDF für Silent-Print. PaperCut ordnet den
        Druckauftrag automatisch dem Service-Account zu.
        """
        if not self._sumatra_path:
            logger.error("SumatraPDF nicht verfügbar – Drucken nicht möglich!")
            return False

        return self._print_via_sumatra(pdf_path, printer_name)

    # ------------------------------------------------------------------
    # SumatraPDF Silent-Print
    # ------------------------------------------------------------------

    def _print_via_sumatra(self, pdf_path: Path, printer_name: str) -> bool:
        """Druckt über SumatraPDF Silent Print."""
        args = [
            str(self._sumatra_path),
            "-print-to", printer_name,
            "-silent",
            str(pdf_path),
        ]

        logger.debug(f"SumatraPDF Druck-Kommando: {' '.join(args)}")

        try:
            subprocess.run(args, check=True, capture_output=True, timeout=60)
            logger.info(
                f"[SumatraPDF] Druckauftrag an '{printer_name}' gesendet: "
                f"{pdf_path.name}"
            )
            return True

        except subprocess.TimeoutExpired:
            logger.error(
                f"[SumatraPDF] Timeout beim Drucken von {pdf_path.name} "
                f"an '{printer_name}' (> 60s)"
            )
            return False

        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace").strip() if e.stderr else "Kein Fehlertext"
            logger.error(f"[SumatraPDF] Fehler beim Drucken: {stderr}")
            return False

        except FileNotFoundError:
            logger.error(
                f"[SumatraPDF] Executable nicht gefunden: {self._sumatra_path}"
            )
            return False

        except Exception as e:
            logger.error(f"[SumatraPDF] Unerwarteter Fehler: {e}")
            return False

    # ------------------------------------------------------------------
    # Info-Methoden
    # ------------------------------------------------------------------

    @property
    def backend_name(self) -> str:
        """Gibt den Namen des aktiven Druck-Backends zurück."""
        return "SumatraPDF"

    @property
    def is_available(self) -> bool:
        """True wenn SumatraPDF verfügbar ist."""
        return self._sumatra_path is not None
