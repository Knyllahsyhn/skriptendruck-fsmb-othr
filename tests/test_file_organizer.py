"""Tests für den FileOrganizer."""
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from skriptendruck.models import ColorMode, Order, OrderStatus
from skriptendruck.services.file_organizer import FileOrganizer


class TestFileOrganizer:
    """Tests für den FileOrganizer."""

    def setup_method(self, tmp_path_factory=None) -> None:
        """Setup für jeden Test."""
        self.organizer = FileOrganizer()

    def test_directory_names(self) -> None:
        """Test: Ordnernamen entsprechen der Konvention."""
        assert self.organizer.DIR_INPUT == "01_Auftraege"
        assert self.organizer.DIR_PRINT == "02_Druckfertig"
        assert self.organizer.DIR_PRINT_SW == "sw"
        assert self.organizer.DIR_PRINT_COLOR == "farbig"
        assert self.organizer.DIR_PRINTED == "gedruckt"
        assert self.organizer.DIR_ORIGINALS == "03_Originale"
        assert self.organizer.DIR_ERRORS == "04_Fehler"
        assert self.organizer.DIR_MANUAL == "05_Manuell"

    def test_get_print_dir_sw(self) -> None:
        """Test: Druckfertig-Pfad für Schwarz-Weiß."""
        path = self.organizer.get_print_dir(ColorMode.BLACK_WHITE)
        assert path.name == "sw"
        assert path.parent.name == "02_Druckfertig"

    def test_get_print_dir_color(self) -> None:
        """Test: Druckfertig-Pfad für Farbe."""
        path = self.organizer.get_print_dir(ColorMode.COLOR)
        assert path.name == "farbig"
        assert path.parent.name == "02_Druckfertig"

    def test_get_error_dir_mapping(self) -> None:
        """Test: Fehler-Ordner werden korrekt zugeordnet."""
        assert self.organizer.get_error_dir(OrderStatus.ERROR_USER_NOT_FOUND).name == "benutzer_nicht_gefunden"
        assert self.organizer.get_error_dir(OrderStatus.ERROR_USER_BLOCKED).name == "gesperrt"
        assert self.organizer.get_error_dir(OrderStatus.ERROR_TOO_FEW_PAGES).name == "zu_wenig_seiten"
        assert self.organizer.get_error_dir(OrderStatus.ERROR_TOO_MANY_PAGES).name == "zu_viele_seiten"
        assert self.organizer.get_error_dir(OrderStatus.ERROR_PASSWORD_PROTECTED).name == "passwortgeschuetzt"
        assert self.organizer.get_error_dir(OrderStatus.ERROR_UNKNOWN).name == "sonstige"
        assert self.organizer.get_error_dir(OrderStatus.ERROR_INVALID_FILENAME).name == "sonstige"

    def test_get_originals_batch_dir_format(self) -> None:
        """Test: Batch-Ordner hat korrektes Zeitstempel-Format."""
        ts = datetime(2026, 1, 16, 12, 38)
        batch_dir = self.organizer.get_originals_batch_dir(ts)

        assert batch_dir.name == "2026-01-16_12-38"
        assert batch_dir.parent.name == "03_Originale"

    def test_ensure_directory_structure(self, tmp_path: Path) -> None:
        """Test: Ordnerstruktur wird korrekt erstellt."""
        organizer = FileOrganizer(base_path=tmp_path)
        organizer.ensure_directory_structure()

        # Prüfe alle erwarteten Ordner
        assert (tmp_path / "01_Auftraege").is_dir()
        assert (tmp_path / "02_Druckfertig" / "sw").is_dir()
        assert (tmp_path / "02_Druckfertig" / "sw" / "gedruckt").is_dir()
        assert (tmp_path / "02_Druckfertig" / "farbig").is_dir()
        assert (tmp_path / "02_Druckfertig" / "farbig" / "gedruckt").is_dir()
        assert (tmp_path / "03_Originale").is_dir()
        assert (tmp_path / "04_Fehler" / "benutzer_nicht_gefunden").is_dir()
        assert (tmp_path / "04_Fehler" / "gesperrt").is_dir()
        assert (tmp_path / "04_Fehler" / "zu_wenig_seiten").is_dir()
        assert (tmp_path / "04_Fehler" / "zu_viele_seiten").is_dir()
        assert (tmp_path / "04_Fehler" / "passwortgeschuetzt").is_dir()
        assert (tmp_path / "04_Fehler" / "sonstige").is_dir()
        assert (tmp_path / "05_Manuell").is_dir()

    def test_move_successful_order(self, tmp_path: Path) -> None:
        """Test: Erfolgreicher Auftrag wird in sw/ oder farbig/ verschoben."""
        organizer = FileOrganizer(base_path=tmp_path)
        organizer.ensure_directory_structure()

        # Fake merged PDF erstellen
        merged_pdf = tmp_path / "work" / "0001_test.pdf"
        merged_pdf.parent.mkdir(parents=True, exist_ok=True)
        merged_pdf.write_text("fake pdf")

        order = Order(
            order_id=1,
            filename="test_sw_mb_001.pdf",
            filepath=tmp_path / "01_Auftraege" / "test_sw_mb_001.pdf",
            file_size_bytes=100,
            color_mode=ColorMode.BLACK_WHITE,
            status=OrderStatus.PROCESSED,
        )
        order.merged_pdf_path = merged_pdf

        result = organizer.move_successful_order(order)

        assert result is not None
        assert result.parent.name == "sw"
        assert result.exists()
        assert not merged_pdf.exists()  # Original verschoben

    def test_move_failed_order(self, tmp_path: Path) -> None:
        """Test: Fehlerhafter Auftrag wird in Fehler-Ordner kopiert."""
        organizer = FileOrganizer(base_path=tmp_path)
        organizer.ensure_directory_structure()

        # Fake Input-PDF erstellen
        input_pdf = tmp_path / "01_Auftraege" / "bad_file.pdf"
        input_pdf.write_text("fake pdf")

        order = Order(
            order_id=2,
            filename="bad_file.pdf",
            filepath=input_pdf,
            file_size_bytes=100,
            status=OrderStatus.ERROR_USER_NOT_FOUND,
            error_message="Benutzer nicht gefunden",
        )

        result = organizer.move_failed_order(order)

        assert result is not None
        assert result.parent.name == "benutzer_nicht_gefunden"
        assert result.exists()
        assert input_pdf.exists()  # Original bleibt (wird nur kopiert)

    def test_backup_original(self, tmp_path: Path) -> None:
        """Test: Original wird in Backup-Ordner kopiert."""
        organizer = FileOrganizer(base_path=tmp_path)

        # Fake Input-PDF erstellen
        input_pdf = tmp_path / "01_Auftraege" / "test.pdf"
        input_pdf.parent.mkdir(parents=True, exist_ok=True)
        input_pdf.write_text("fake pdf")

        order = Order(
            order_id=1,
            filename="test.pdf",
            filepath=input_pdf,
            file_size_bytes=100,
        )

        batch_dir = tmp_path / "03_Originale" / "2026-01-16_12-38"
        result = organizer.backup_original(order, batch_dir)

        assert result is not None
        assert result.exists()
        assert result.parent.name == "2026-01-16_12-38"

    def test_cleanup_input(self, tmp_path: Path) -> None:
        """Test: Input-Datei wird nach Verarbeitung gelöscht."""
        organizer = FileOrganizer(base_path=tmp_path)

        input_pdf = tmp_path / "test.pdf"
        input_pdf.write_text("fake pdf")

        order = Order(
            order_id=1,
            filename="test.pdf",
            filepath=input_pdf,
            file_size_bytes=100,
        )

        assert organizer.cleanup_input(order)
        assert not input_pdf.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
