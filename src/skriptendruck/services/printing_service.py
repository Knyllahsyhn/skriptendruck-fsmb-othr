import subprocess
from pathlib import Path
import logging
from ..config import settings
from ..models import ColorMode

logger = logging.getLogger("printing")

class PrintingService:
    def print_order(self, order) -> bool:
        """Druckt ein fertiges Order-Objekt."""
        if not order.merged_pdf_path or not order.merged_pdf_path.exists():
            logger.error(f"Keine druckfähige Datei für Order {order.order_id}")
            return False

        # Drucker wählen basierend auf Farbmodus
        printer = settings.printer_color if order.color_mode == ColorMode.COlOR else settings.printer_sw
        
        return self.send_to_printer(order.merged_pdf_path, printer)

    def send_to_printer(self, pdf_path: Path, printer_name: str) -> bool:
        if not Path(settings.sumatra_pdf_path).exists():
            logger.error(f"SumatraPDF nicht gefunden unter: {settings.sumatra_pdf_path}")
            return False

        # SumatraPDF Silent Print Befehl
        args = [
            settings.sumatra_pdf_path,
            "-print-to", printer_name,
            "-silent",
            str(pdf_path)
        ]

        try:
            subprocess.run(args, check=True, capture_output=True)
            logger.info(f"Druckauftrag an {printer_name} gesendet: {pdf_path.name}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Fehler beim Drucken: {e.stderr.decode()}")
            return False