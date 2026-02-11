"""Service für PDF-Verarbeitung mit pypdf."""
import io
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from ..config import get_logger
from ..models import Order

logger = get_logger("pdf_service")


class PdfService:
    """Service für PDF-Verarbeitung."""
    
    def get_page_count(self, pdf_path: Path) -> Tuple[Optional[int], bool]:
        """
        Ermittelt die Seitenzahl eines PDFs.
        
        Args:
            pdf_path: Pfad zur PDF-Datei
            
        Returns:
            Tuple (page_count, is_password_protected)
        """
        try:
            reader = PdfReader(pdf_path)
            
            # Passwortschutz prüfen
            if reader.is_encrypted:
                logger.warning(f"PDF ist passwortgeschützt: {pdf_path}")
                return None, True
            
            page_count = len(reader.pages)
            logger.debug(f"PDF hat {page_count} Seiten: {pdf_path}")
            return page_count, False
            
        except Exception as e:
            logger.error(f"Fehler beim Lesen des PDFs {pdf_path}: {e}")
            return None, False

    def _render_page_thumbnail(self, pdf_path: Path, page_index: int = 0) -> Optional[str]:
        """
        Rendert eine einzelne PDF-Seite als Bild-Datei (PNG) für die Thumbnail-Vorschau.
        
        Nutzt pypdf um die Seite als eigenständiges PDF zu extrahieren,
        dann pymupdf (fitz) zum Rendern als Bild. Fallback: None.
        
        Args:
            pdf_path: Pfad zur PDF-Datei
            page_index: Seitenindex (0 = erste Seite)
            
        Returns:
            Pfad zur temporären PNG-Datei oder None
        """
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(str(pdf_path))
            if len(doc) == 0:
                doc.close()
                return None

            page = doc[page_index]

            # Render mit 1.5x Zoom für gute Qualität bei Thumbnail-Größe
            mat = fitz.Matrix(1.5, 1.5)
            pix = page.get_pixmap(matrix=mat)

            # Temporäre PNG-Datei erstellen
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            pix.save(tmp.name)

            doc.close()
            logger.debug(f"Thumbnail erstellt: {tmp.name}")
            return tmp.name

        except ImportError:
            logger.debug("PyMuPDF (fitz) nicht verfügbar – Thumbnail wird übersprungen")
            return None
        except Exception as e:
            logger.warning(f"Thumbnail-Rendering fehlgeschlagen: {e}")
            return None
    
    def create_coversheet(
        self,
        order: Order,
        output_path: Path,
    ) -> bool:
        """
        Erstellt ein Deckblatt für einen Auftrag.
        Enthält eine Thumbnail-Vorschau der ersten Dokumentseite.
        
        Args:
            order: Auftrags-Objekt
            output_path: Pfad für das Deckblatt
            
        Returns:
            True bei Erfolg
        """
        thumbnail_path = None
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Thumbnail der ersten Seite rendern
            if order.filepath and order.filepath.exists():
                thumbnail_path = self._render_page_thumbnail(order.filepath)
            
            # Canvas erstellen
            c = canvas.Canvas(str(output_path), pagesize=A4)
            width, height = A4

            # --- Header ---
            c.setFont("Helvetica-Bold", 18)
            c.drawString(50, height - 50, "Fachschaft - Skriptendruck")
            c.line(50, height - 60, width - 50, height - 60)

            # --- Auftragsinformationen ---
            y = height - 90
            line_height = 18
            label_x = 50
            value_x = 200

            def draw_field(label: str, value: str, bold_value: bool = False) -> None:
                nonlocal y
                c.setFont("Helvetica-Bold", 11)
                c.drawString(label_x, y, label)
                c.setFont("Helvetica-Bold" if bold_value else "Helvetica", 11)
                c.drawString(value_x, y, value)
                y -= line_height

            draw_field("Auftrags-ID:", str(order.order_id))
            draw_field("Datum:", order.created_at.strftime("%d.%m.%Y %H:%M"))
            draw_field("Dateiname:", order.filename)

            y -= 6  # Abstand

            # --- Benutzer ---
            if order.user:
                draw_field("RZ-Kennung:", order.user.username)
                draw_field("Name:", order.user.full_name)
                draw_field("Fakultät:", order.user.faculty)
                y -= 6

            # --- PDF-Informationen ---
            if order.page_count:
                draw_field("Seitenzahl:", str(order.page_count))

            # --- Preisberechnung ---
            if order.price_calculation:
                calc = order.price_calculation
                
                color_text = "Farbe" if calc.color_mode.value == "color" else "Schwarz-Weiß"
                draw_field("Druck:", f"{color_text} ({calc.pages_price_formatted})")
                
                if calc.binding_type.value == "none":
                    binding_text = "Ohne Bindung"
                elif calc.binding_type.value == "folder":
                    binding_text = f"Schnellhefter ({calc.binding_price_formatted})"
                else:
                    size_label = f" – {calc.binding_size_mm} mm" if calc.binding_size_mm else ""
                    binding_text = f"Ringbindung ({calc.binding_price_formatted}){size_label}"

                draw_field("Bindung:", binding_text)

                y -= 6

                # Gesamtpreis hervorgehoben
                c.setFont("Helvetica-Bold", 13)
                c.drawString(label_x, y, "Gesamtpreis:")
                c.drawString(value_x, y, calc.total_price_formatted)
                y -= line_height
                
                c.setFont("Helvetica", 10)
                c.drawString(label_x, y, "Nach Abzug 1 € Anzahlung:")
                c.setFont("Helvetica-Bold", 11)
                c.drawString(value_x, y, calc.price_after_deposit_formatted)
                y -= line_height

            # --- Fehlerhinweis ---
            if order.status.value == "error_invalid_filename":
                y -= 10
                c.setFillColorRGB(0.8, 0, 0)
                c.setFont("Helvetica-Bold", 10)
                c.drawString(label_x, y, "ACHTUNG: Dateiname nicht korrekt!")
                y -= line_height
                c.setFont("Helvetica", 9)
                c.drawString(label_x, y, "Bitte nächstes Mal richtig benennen:")
                y -= line_height
                c.drawString(label_x, y, "RZ-Kennung_sw/farbig_mb/ob/sh_001.pdf")
                c.setFillColorRGB(0, 0, 0)

            # --- Thumbnail-Vorschau der ersten Seite ---
            if thumbnail_path:
                try:
                    # Vorschau-Bereich: untere Hälfte der Seite, zentriert
                    preview_label_y = y - 20
                    c.setFont("Helvetica-Bold", 10)
                    c.setFillColorRGB(0.3, 0.3, 0.3)
                    c.drawString(label_x, preview_label_y, "Vorschau erste Seite:")
                    c.setFillColorRGB(0, 0, 0)

                    # Bildgröße berechnen – max 200pt breit, max verfügbare Höhe
                    img = ImageReader(thumbnail_path)
                    img_w, img_h = img.getSize()

                    max_thumb_w = 220
                    max_thumb_h = preview_label_y - 70  # Platz bis Footer lassen

                    scale = min(max_thumb_w / img_w, max_thumb_h / img_h, 1.0)
                    thumb_w = img_w * scale
                    thumb_h = img_h * scale

                    thumb_x = label_x
                    thumb_y = preview_label_y - thumb_h - 10

                    # Rahmen zeichnen
                    c.setStrokeColorRGB(0.7, 0.7, 0.7)
                    c.setLineWidth(0.5)
                    c.rect(thumb_x - 2, thumb_y - 2, thumb_w + 4, thumb_h + 4)

                    # Bild zeichnen
                    c.drawImage(
                        thumbnail_path,
                        thumb_x, thumb_y,
                        width=thumb_w, height=thumb_h,
                        preserveAspectRatio=True,
                    )

                except Exception as e:
                    logger.warning(f"Thumbnail konnte nicht ins Deckblatt eingefügt werden: {e}")

            # --- Footer ---
            c.setFillColorRGB(0, 0, 0)
            c.setFont("Helvetica", 8)
            c.drawString(50, 40, "Fachschaft Maschinenbau – Hochschule Regensburg")
            c.drawRightString(width - 50, 40, f"Auftrag #{order.order_id}")
            
            c.save()
            
            logger.info(f"Deckblatt erstellt: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Fehler beim Erstellen des Deckblatts: {e}")
            return False
        finally:
            # Temporäre Thumbnail-Datei aufräumen
            if thumbnail_path:
                try:
                    Path(thumbnail_path).unlink(missing_ok=True)
                except Exception:
                    pass
    
    def merge_pdfs(
        self,
        coversheet_path: Path,
        document_path: Path,
        output_path: Path,
        add_empty_page: bool = False,
    ) -> bool:
        """
        Fügt Deckblatt und Dokument zusammen.
        
        Args:
            coversheet_path: Pfad zum Deckblatt
            document_path: Pfad zum Dokument
            output_path: Pfad für die Ausgabedatei
            add_empty_page: Leere Seite zwischen Deckblatt und Dokument einfügen
            
        Returns:
            True bei Erfolg
        """
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            writer = PdfWriter()
            
            # Deckblatt hinzufügen
            coversheet_reader = PdfReader(coversheet_path)
            for page in coversheet_reader.pages:
                writer.add_page(page)
            
            # Optional: Leere Seite
            if add_empty_page:
                writer.add_blank_page(width=A4[0], height=A4[1])
            
            # Dokument hinzufügen
            document_reader = PdfReader(document_path)
            for page in document_reader.pages:
                writer.add_page(page)
            
            # Speichern
            with open(output_path, "wb") as f:
                writer.write(f)
            
            logger.info(f"PDFs zusammengefügt: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Fehler beim Zusammenfügen der PDFs: {e}")
            return False
