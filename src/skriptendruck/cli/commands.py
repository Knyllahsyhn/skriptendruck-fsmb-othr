"""CLI-Befehle für das Skriptendruckprogramm."""
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from ..config import get_logger, settings, setup_logging
from ..database.service import DatabaseService
from ..models import OrderStatus
from ..processing.pipeline import OrderPipeline
from ..services import FileOrganizer, PricingService
from ..services.excel_service import ExcelExportService

app = typer.Typer(
    name="skriptendruck",
    help="Modernisiertes Skriptendruckprogramm für die Fachschaft",
    add_completion=False,
)

console = Console()
logger = get_logger("cli")


@app.command()
def process(
    orders_dir: Optional[Path] = typer.Option(
        None,
        "--orders-dir",
        "-i",
        help="Verzeichnis mit Aufträgen (Standard: aus Settings)"
    ),
    sequential: bool = typer.Option(
        False,
        "--sequential",
        help="Sequenzielle statt parallele Verarbeitung"
    ),
        no_organize: bool = typer.Option(
            False,
            "--no-organize",
            help="Dateien nicht in Ordnerstruktur verschieben"
        ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Ausführliche Ausgabe"
    ),
) -> None:
    """
    Verarbeitet Druckaufträge.

    Liest PDF-Dateien aus dem Auftragsverzeichnis, validiert Benutzer,
    berechnet Preise, erstellt Deckblätter und organisiert die Ausgabe
    in die Ordnerstruktur (02_Druckfertig, 04_Fehler, etc.).
    """
    # Logging einrichten
    log_level = "DEBUG" if verbose else settings.log_level
    setup_logging(level=log_level, log_file=settings.log_file)

    # Parallel-Option
    settings.parallel_processing = not sequential

    # FileOrganizer initialisieren und Ordnerstruktur sicherstellen
    organizer = FileOrganizer()
    organizer.ensure_directory_structure()

    # Verzeichnisse
    orders_dir = orders_dir or organizer.get_input_dir()

    console.print(f"\n[bold blue]Skriptendruck - Verarbeitung[/bold blue]")
    console.print(f"Aufträge:     {orders_dir}")
    console.print(f"Druckfertig:  {organizer.base_path / organizer.DIR_PRINT}")
    console.print(f"Originale:    {organizer.get_originals_dir()}")
    console.print()

    # Pipeline initialisieren
    pipeline = OrderPipeline(file_organizer=organizer)

    # Aufträge finden
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Suche nach Aufträgen...", total=None)
        orders = pipeline.discover_orders(orders_dir)
        progress.update(task, completed=True)

    if not orders:
        console.print("[yellow]Keine Aufträge gefunden.[/yellow]")
        return

    console.print(f"[green]Gefunden: {len(orders)} Aufträge[/green]\n")

    # Aufträge verarbeiten
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"Verarbeite {len(orders)} Aufträge...",
            total=len(orders)
        )

        processed_orders = pipeline.process_orders(
            orders,
            organize_files=not no_organize,
        )
        progress.update(task, completed=len(orders))

    # Zusammenfassung
    _display_summary(processed_orders, organizer)


@app.command()
def init(
        base_path: Optional[Path] = typer.Option(
            None,
            "--base-path",
            "-p",
            help="Basispfad für die Ordnerstruktur"
        ),
) -> None:
    """
    Initialisiert die Ordnerstruktur und Beispieldaten.

    Erstellt:
    - Komplette Ordnerstruktur (01_Auftraege bis 05_Manuell)
    - Beispiel-Ringbindungsgrößen (binding_sizes.json)
    - Beispiel-Blacklist und CSV
    - Beispiel-.env-Datei
    """
    console.print("\n[bold blue]Initialisiere Skriptendruck...[/bold blue]\n")

    # FileOrganizer
    organizer = FileOrganizer(base_path=base_path) if base_path else FileOrganizer()
    organizer.ensure_directory_structure()
    console.print(f"[green]✓[/green] Ordnerstruktur erstellt unter: {organizer.base_path}")

    # Binding Sizes JSON
    pricing_service = PricingService()
    binding_path = Path("data/binding_sizes.json")

    if binding_path.exists():
        console.print(f"[yellow]Überspringe: {binding_path} existiert bereits[/yellow]")
    else:
        pricing_service.export_default_binding_sizes_json(binding_path)
        console.print(f"[green]✓[/green] Erstellt: {binding_path}")

    # Blacklist
    blacklist_path = Path("data/blacklist.txt")
    if blacklist_path.exists():
        console.print(f"[yellow]Überspringe: {blacklist_path} existiert bereits[/yellow]")
    else:
        blacklist_path.parent.mkdir(parents=True, exist_ok=True)
        with open(blacklist_path, "w", encoding="utf-8") as f:
            f.write("# Blockierte Benutzer (RZ-Kennungen)\n")
            f.write("# Ein Username pro Zeile\n")
        console.print(f"[green]✓[/green] Erstellt: {blacklist_path}")

    # Users CSV (Fallback)
    users_csv_path = Path("data/users_fallback.csv")
    if users_csv_path.exists():
        console.print(f"[yellow]Überspringe: {users_csv_path} existiert bereits[/yellow]")
    else:
        users_csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(users_csv_path, "w", encoding="utf-8") as f:
            f.write("# Format: username firstname lastname faculty\n")
            f.write("# Beispiel:\n")
            f.write("# mus43225 Sebastian Müllner M\n")
        console.print(f"[green]✓[/green] Erstellt: {users_csv_path}")

    # .env Beispiel
    env_example_path = Path(".env.example")
    if not env_example_path.exists():
        with open(env_example_path, "w", encoding="utf-8") as f:
            f.write("# Basis-Konfiguration\n")
            f.write("BASE_PATH=H:/stud/fsmb/03_Dienste/01_Skriptendruck\n")
            f.write("ORDERS_PATH=01_Auftraege\n")
            f.write("OUTPUT_PATH=output\n\n")
            f.write("# LDAP Konfiguration\n")
            f.write("LDAP_ENABLED=false\n")
            f.write("#LDAP_SERVER=adldap.hs-regensburg.de\n")
            f.write("#LDAP_BASE_DN=dc=hs-regensburg,dc=de\n\n")
            f.write("# Logging\n")
            f.write("LOG_LEVEL=INFO\n")
            f.write("#LOG_FILE=skriptendruck.log\n")
        console.print(f"[green]✓[/green] Erstellt: {env_example_path}")

    # Ordnerstruktur anzeigen
    console.print("\n[bold]Ordnerstruktur:[/bold]")
    console.print(f"  {organizer.base_path}/")
    console.print(f"    ├── {organizer.DIR_INPUT}/")
    console.print(f"    ├── {organizer.DIR_PRINT}/")
    console.print(f"    │   ├── {organizer.DIR_PRINT_SW}/")
    console.print(f"    │   │   └── {organizer.DIR_PRINTED}/")
    console.print(f"    │   └── {organizer.DIR_PRINT_COLOR}/")
    console.print(f"    │       └── {organizer.DIR_PRINTED}/")
    console.print(f"    ├── {organizer.DIR_ORIGINALS}/")
    console.print(f"    ├── {organizer.DIR_ERRORS}/")
    console.print(f"    │   ├── benutzer_nicht_gefunden/")
    console.print(f"    │   ├── gesperrt/")
    console.print(f"    │   ├── zu_wenig_seiten/")
    console.print(f"    │   ├── zu_viele_seiten/")
    console.print(f"    │   ├── passwortgeschuetzt/")
    console.print(f"    │   └── sonstige/")
    console.print(f"    └── {organizer.DIR_MANUAL}/")

    console.print("\n[green]Initialisierung abgeschlossen![/green]")


@app.command()
def stats(
    orders_dir: Optional[Path] = typer.Option(
        None,
        "--orders-dir",
        "-i",
        help="Verzeichnis mit Aufträgen"
    ),
) -> None:
    """
    Zeigt Statistiken über vorhandene Aufträge.
    """
    organizer = FileOrganizer()
    orders_dir = orders_dir or organizer.get_input_dir()

    pipeline = OrderPipeline()
    orders = pipeline.discover_orders(orders_dir)

    if not orders:
        console.print("[yellow]Keine Aufträge gefunden.[/yellow]")
        return

    # Einfache Statistik
    table = Table(title=f"Statistik: {orders_dir}")
    table.add_column("Metrik", style="cyan")
    table.add_column("Wert", style="green")

    table.add_row("Anzahl Aufträge", str(len(orders)))

    total_size = sum(o.file_size_bytes for o in orders)
    table.add_row("Gesamtgröße", f"{total_size / 1024 / 1024:.2f} MB")

    console.print()
    console.print(table)


@app.command()
def export_excel(
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Ausgabeverzeichnis für Excel-Dateien"
    ),
    days: int = typer.Option(
        30,
        "--days",
        "-d",
        help="Anzahl Tage rückwirkend"
    ),
) -> None:
    """
    Exportiert Auftrags- und Abrechnungslisten nach Excel.

    Erstellt zwei Excel-Dateien:
    - Auftragsliste.xlsx: Alle Aufträge
    - Abrechnungsliste.xlsx: Offene Abrechnungen
    """
    console.print(f"\n[bold blue]Excel-Export[/bold blue]\n")

    output_dir = output_dir or settings.get_output_directory()
    output_dir.mkdir(parents=True, exist_ok=True)

    db_service = DatabaseService()
    excel_service = ExcelExportService()

    # Zeitraum berechnen
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        # Aufträge exportieren
        task = progress.add_task("Exportiere Auftragsliste...", total=None)
        orders = db_service.get_orders_by_date_range(start_date, end_date)

        if orders:
            orders_path = output_dir / f"Auftragsliste_{end_date.strftime('%Y%m%d')}.xlsx"
            if excel_service.export_orders_list(orders, orders_path):
                console.print(f"[green]✓[/green] Auftragsliste: {orders_path}")
            else:
                console.print(f"[red]✗[/red] Fehler beim Export der Auftragsliste")
        else:
            console.print("[yellow]Keine Aufträge im Zeitraum gefunden[/yellow]")

        progress.update(task, completed=True)

        # Abrechnungen exportieren
        task = progress.add_task("Exportiere Abrechnungsliste...", total=None)
        billings = db_service.get_unpaid_billings()

        if billings:
            billings_path = output_dir / f"Abrechnungsliste_{end_date.strftime('%Y%m%d')}.xlsx"
            if excel_service.export_billing_list(billings, billings_path):
                console.print(f"[green]✓[/green] Abrechnungsliste: {billings_path}")
            else:
                console.print(f"[red]✗[/red] Fehler beim Export der Abrechnungsliste")
        else:
            console.print("[yellow]Keine offenen Abrechnungen[/yellow]")

        progress.update(task, completed=True)

    console.print()


@app.command()
def db_stats() -> None:
    """
    Zeigt Datenbank-Statistiken.
    """
    console.print(f"\n[bold blue]Datenbank-Statistiken[/bold blue]\n")

    db_service = DatabaseService()
    stats = db_service.get_statistics()

    table = Table()
    table.add_column("Metrik", style="cyan")
    table.add_column("Wert", style="green")

    table.add_row("Gesamt Aufträge", str(stats["total_orders"]))
    table.add_row("Erfolgreich", str(stats["successful_orders"]))
    table.add_row("Fehler", str(stats["error_orders"]))
    table.add_row("Gesamtumsatz", f"{stats['total_revenue']:.2f} €")

    console.print(table)
    console.print()


def _display_summary(orders: list, organizer: FileOrganizer) -> None:
    """Zeigt Zusammenfassung der verarbeiteten Aufträge."""
    console.print("\n[bold blue]Zusammenfassung[/bold blue]\n")

    # Statistik
    total = len(orders)
    success = sum(1 for o in orders if o.status == OrderStatus.PROCESSED)
    errors = total - success

    console.print(f"Gesamt: {total}")
    console.print(f"[green]Erfolgreich: {success}[/green]")
    if errors > 0:
        console.print(f"[red]Fehler: {errors}[/red]")
    console.print()

    # Erfolgreiche Aufträge
    if success > 0:
        success_table = Table(title="Verarbeitete Aufträge")
        success_table.add_column("ID", style="cyan", width=6)
        success_table.add_column("Dateiname")
        success_table.add_column("Benutzer")
        success_table.add_column("Seiten", justify="right")
        success_table.add_column("Preis", justify="right", style="green")
        success_table.add_column("Ziel")

        for order in orders:
            if order.status == OrderStatus.PROCESSED:
                user_str = order.user.full_name if order.user else "?"
                price_str = order.price_calculation.total_price_formatted if order.price_calculation else "?"
                target = "sw/" if order.color_mode and order.color_mode.value == "sw" else "farbig/"
                success_table.add_row(
                    str(order.order_id),
                    order.filename,
                    user_str,
                    str(order.page_count or "?"),
                    price_str,
                    target,
                )

        console.print(success_table)
        console.print()

    # Fehler-Details
    if errors > 0:
        error_table = Table(title="Fehler")
        error_table.add_column("ID", style="cyan", width=6)
        error_table.add_column("Dateiname")
        error_table.add_column("Status", style="red")
        error_table.add_column("Nachricht")

        for order in orders:
            if order.is_error:
                error_table.add_row(
                    str(order.order_id),
                    order.filename,
                    order.status.value,
                    order.error_message or ""
                )

        console.print(error_table)
        console.print()


@app.callback()
def main() -> None:
    """Skriptendruck - Modernisiertes Druckauftrags-Verwaltungssystem."""
    pass
