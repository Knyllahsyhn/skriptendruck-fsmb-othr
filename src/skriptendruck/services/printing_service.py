"""
Druck-Service mit PaperCut-Integration und SumatraPDF-Fallback.

Druckt PDFs entweder über ``pc-print`` (PaperCut NG CLI) oder über
SumatraPDF Silent-Print – je nach Konfiguration in der ``.env``-Datei.

Priorität:
1. **PaperCut (pc-print)** – wenn ``PC_PRINT_PATH`` gesetzt und Datei existiert
2. **SumatraPDF**          – Fallback, wenn PaperCut nicht verfügbar

Siehe ``docs/PAPERCUT_SETUP.md`` für die PaperCut-Einrichtung.
"""

import subprocess
from pathlib import Path
import logging

from ..config import settings
from ..models import ColorMode

logger = logging.getLogger("printing")


class PrintingService:
    """Service zum Senden von Druckaufträgen an einen konfigurierten Drucker."""

    def __init__(self):
        self._use_papercut: bool = False
        self._pc_print_path: Path | None = None
        self._detect_print_backend()

    # ------------------------------------------------------------------
    # Backend-Erkennung
    # ------------------------------------------------------------------

    def _detect_print_backend(self) -> None:
        """Erkennt, ob PaperCut (pc-print) oder SumatraPDF verwendet werden soll."""

        if settings.pc_print_path:
            pc_path = Path(settings.pc_print_path)
            if pc_path.exists():
                # Prüfe ob PAPERCUT_USER und PAPERCUT_ACCOUNT gesetzt sind
                if settings.papercut_user and settings.papercut_account:
                    self._use_papercut = True
                    self._pc_print_path = pc_path
                    logger.info(
                        f"PaperCut-Druck aktiviert: {pc_path} "
                        f"(User: {settings.papercut_user}, "
                        f"Account: {settings.papercut_account})"
                    )
                else:
                    logger.warning(
                        "PC_PRINT_PATH ist gesetzt, aber PAPERCUT_USER und/oder "
                        "PAPERCUT_ACCOUNT fehlen. Fallback auf SumatraPDF."
                    )
            else:
                logger.warning(
                    f"pc-print nicht gefunden unter: {pc_path} – "
                    f"Fallback auf SumatraPDF."
                )

        if not self._use_papercut:
            logger.info(
                "Druck-Backend: SumatraPDF "
                f"({settings.sumatra_pdf_path})"
            )

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def print_order(self, order) -> bool:
        """Druckt ein fertiges Order-Objekt.

        Wählt den Drucker basierend auf dem Farbmodus und delegiert an
        das erkannte Backend (PaperCut oder SumatraPDF).
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

        Verwendet PaperCut (pc-print) wenn verfügbar, sonst SumatraPDF.
        """
        if self._use_papercut:
            return self._print_via_papercut(pdf_path, printer_name)
        else:
            return self._print_via_sumatra(pdf_path, printer_name)

    # ------------------------------------------------------------------
    # PaperCut (pc-print)
    # ------------------------------------------------------------------

    def _print_via_papercut(self, pdf_path: Path, printer_name: str) -> bool:
        """Druckt über PaperCut pc-print CLI.

        Command:
            pc-print --user={PAPERCUT_USER} --account={PAPERCUT_ACCOUNT}
                     --printer={printer_name} {pdf_file}
        """
        args = [
            str(self._pc_print_path),
            f"--user={settings.papercut_user}",
            f"--account={settings.papercut_account}",
            f"--printer={printer_name}",
            str(pdf_path),
        ]

        logger.debug(f"PaperCut Druck-Kommando: {' '.join(args)}")

        try:
            result = subprocess.run(
                args,
                check=True,
                capture_output=True,
                timeout=60,
            )
            logger.info(
                f"[PaperCut] Druckauftrag an '{printer_name}' gesendet: "
                f"{pdf_path.name} (User: {settings.papercut_user}, "
                f"Account: {settings.papercut_account})"
            )
            if result.stdout:
                logger.debug(f"[PaperCut] stdout: {result.stdout.decode(errors='replace').strip()}")
            return True

        except subprocess.TimeoutExpired:
            logger.error(
                f"[PaperCut] Timeout beim Drucken von {pdf_path.name} "
                f"an '{printer_name}' (> 60s)"
            )
            return False

        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace").strip() if e.stderr else "Kein Fehlertext"
            stdout = e.stdout.decode(errors="replace").strip() if e.stdout else ""
            logger.error(
                f"[PaperCut] Fehler beim Drucken von {pdf_path.name}: "
                f"Return-Code {e.returncode} – {stderr}"
            )
            if stdout:
                logger.debug(f"[PaperCut] stdout: {stdout}")
            return False

        except FileNotFoundError:
            logger.error(
                f"[PaperCut] pc-print nicht gefunden: {self._pc_print_path} – "
                f"wurde die Datei gelöscht oder verschoben?"
            )
            return False

        except Exception as e:
            logger.error(f"[PaperCut] Unerwarteter Fehler beim Drucken: {e}")
            return False

    # ------------------------------------------------------------------
    # SumatraPDF (Fallback)
    # ------------------------------------------------------------------

    def _print_via_sumatra(self, pdf_path: Path, printer_name: str) -> bool:
        """Druckt über SumatraPDF Silent Print (Fallback-Methode)."""
        if not Path(settings.sumatra_pdf_path).exists():
            logger.error(
                f"SumatraPDF nicht gefunden unter: {settings.sumatra_pdf_path}"
            )
            return False

        args = [
            settings.sumatra_pdf_path,
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

        except Exception as e:
            logger.error(f"[SumatraPDF] Unerwarteter Fehler: {e}")
            return False

    # ------------------------------------------------------------------
    # Info-Methoden
    # ------------------------------------------------------------------

    @property
    def backend_name(self) -> str:
        """Gibt den Namen des aktiven Druck-Backends zurück."""
        return "PaperCut (pc-print)" if self._use_papercut else "SumatraPDF"

    @property
    def is_papercut_active(self) -> bool:
        """True wenn PaperCut als Druck-Backend verwendet wird."""
        return self._use_papercut
