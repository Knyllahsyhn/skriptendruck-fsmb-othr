"""Tests für den PricingService."""
import pytest

from skriptendruck.models import BindingType, ColorMode
from skriptendruck.services import PricingService


class TestPricingService:
    """Tests für den PricingService."""
    
    def setup_method(self) -> None:
        """Setup für jeden Test."""
        self.service = PricingService()
    
    def test_calculate_price_black_white_no_binding(self) -> None:
        """Test: Preisberechnung Schwarz-Weiß ohne Bindung."""
        calc = self.service.calculate_price(
            pages=100,
            color_mode=ColorMode.BLACK_WHITE,
            binding_type=BindingType.NONE,
        )
        
        assert calc.pages == 100
        assert calc.pages_price == 4.0  # 100 * 0.04
        assert calc.binding_price == 0.0
        assert calc.total_price == 4.0
    
    def test_calculate_price_color_with_binding(self) -> None:
        """Test: Preisberechnung Farbe mit Bindung."""
        calc = self.service.calculate_price(
            pages=200,
            color_mode=ColorMode.COLOR,
            binding_type=BindingType.SMALL,
        )
        
        assert calc.pages == 200
        assert calc.pages_price == 20.0  # 200 * 0.10
        assert calc.binding_price == 1.0  # Kleine Bindung
        assert calc.total_price == 21.0
    
    def test_calculate_price_with_folder(self) -> None:
        """Test: Preisberechnung mit Schnellhefter."""
        calc = self.service.calculate_price(
            pages=50,
            color_mode=ColorMode.BLACK_WHITE,
            binding_type=BindingType.FOLDER,
        )
        
        assert calc.binding_price == 0.5  # Schnellhefter
        assert calc.total_price == 2.5  # 50*0.04 + 0.5
    
    def test_price_after_deposit(self) -> None:
        """Test: Preis nach Abzug der Anzahlung."""
        calc = self.service.calculate_price(
            pages=100,
            color_mode=ColorMode.BLACK_WHITE,
            binding_type=BindingType.SMALL,
        )
        
        # Total: 4.0 (Seiten) + 1.0 (Bindung) = 5.0
        # Nach Anzahlung: 5.0 - 1.0 = 4.0
        assert calc.total_price == 5.0
        assert calc.price_after_deposit == 4.0
    
    def test_validate_page_count_too_few(self) -> None:
        """Test: Validierung - zu wenig Seiten."""
        is_valid, error = self.service.validate_page_count(0, BindingType.NONE)
        
        assert not is_valid
        assert "wenig" in error.lower()

    def test_validate_page_count_too_many_for_binding(self) -> None:
        """Test: Validierung - zu viele Seiten für Bindung (max 660)."""
        is_valid, error = self.service.validate_page_count(700, BindingType.SMALL)
        
        assert not is_valid
        assert "viele" in error.lower() or "max" in error.lower()

    def test_validate_page_count_at_max(self) -> None:
        """Test: Validierung - genau an der Obergrenze (660 Seiten)."""
        is_valid, error = self.service.validate_page_count(660, BindingType.SMALL)

        assert is_valid
        assert error is None
    
    def test_validate_page_count_valid(self) -> None:
        """Test: Validierung - gültige Seitenzahl."""
        is_valid, error = self.service.validate_page_count(200, BindingType.SMALL)
        
        assert is_valid
        assert error is None
    
    def test_formatted_prices(self) -> None:
        """Test: Formatierte Preise haben deutsches Format."""
        calc = self.service.calculate_price(
            pages=100,
            color_mode=ColorMode.BLACK_WHITE,
            binding_type=BindingType.SMALL,
        )
        
        # Deutsches Format mit Komma
        assert "," in calc.total_price_formatted
        assert "€" in calc.total_price_formatted

    def test_large_binding_price(self) -> None:
        """Test: Große Bindung ab 301 Seiten kostet 1,50€."""
        calc = self.service.calculate_price(
            pages=350,
            color_mode=ColorMode.BLACK_WHITE,
            binding_type=BindingType.SMALL,  # Wird auf LARGE hochgestuft
        )

        assert calc.binding_type == BindingType.LARGE
        assert calc.binding_price == 1.50

    def test_small_binding_at_boundary(self) -> None:
        """Test: Kleine Bindung bei genau 300 Seiten."""
        calc = self.service.calculate_price(
            pages=300,
            color_mode=ColorMode.BLACK_WHITE,
            binding_type=BindingType.SMALL,
        )

        assert calc.binding_type == BindingType.SMALL
        assert calc.binding_price == 1.00

    def test_binding_size_mm_is_float(self) -> None:
        """Test: Bindungsgröße in mm ist ein Float (z.B. 6.9, 14.3)."""
        calc = self.service.calculate_price(
            pages=50,
            color_mode=ColorMode.BLACK_WHITE,
            binding_type=BindingType.SMALL,
        )

        assert calc.binding_size_mm is not None
        assert isinstance(calc.binding_size_mm, float)

    def test_binding_size_lookup_various_pages(self) -> None:
        """Test: Korrekte Bindungsgröße für verschiedene Seitenzahlen."""
        test_cases = [
            (50, 6.9),  # 1-80 Seiten
            (90, 8.0),  # 81-100
            (110, 9.5),  # 101-120
            (140, 11.0),  # 121-150
            (170, 12.7),  # 151-180
            (200, 14.3),  # 181-210
            (230, 16.0),  # 211-240
            (270, 19.0),  # 241-300
            (330, 22.0),  # 301-360
            (400, 25.4),  # 361-420
            (450, 28.5),  # 421-480
            (520, 32.0),  # 481-540
            (600, 38.0),  # 541-660
        ]

        for pages, expected_mm in test_cases:
            binding = self.service.get_binding_size_for_pages(pages)
            assert binding is not None, f"No binding found for {pages} pages"
            assert binding.size_mm == expected_mm, (
                f"Expected {expected_mm}mm for {pages} pages, got {binding.size_mm}mm"
            )

    def test_no_binding_for_excess_pages(self) -> None:
        """Test: Keine Bindungsgröße für >660 Seiten."""
        binding = self.service.get_binding_size_for_pages(700)
        assert binding is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
