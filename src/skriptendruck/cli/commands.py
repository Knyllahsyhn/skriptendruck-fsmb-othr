"""CLI-Befehle fÃ¼r das Skriptendruckprogramm."""
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
from ..services import FileOrganizer, PricingService, PrintingService
from ..services.excel_service import ExcelExportService


app = typer.Typer(
    name="skriptendruck",
    help="Modernisiertes Skriptendruckprogramm fÃ¼r die Fachschaft",
    add_completion=False,
)

console = Console()
logger = get_logger("cli")


@app.command()
def process(
    orders_dir: Optional[Path] = typer.Option(
        None, "--orders-dir", "-i",
        help="Verzeichnis mit Aufträgen (Standard: 01_Auftraege)"
    ),
    sequential: bool = typer.Option(
        False, "--sequential",
        help="Sequenzielle statt parallele Verarbeitung"
    ),
    no_organize: bool = typer.Option(
        False, "--no-organize",
        help="Dateien nicht in Ordnerstruktur verschieben"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Ausfhrliche Ausgabe"
    ),
    do_print: bool = typer.Option(
        False, "--print", "-p",
        help="Aufträge sofort drucken (überschreibt AUTO_PRINT)"
    ),
) -> None:
    """
    Verarbeitet Druckaufträge.

    Liest PDF-Dateien aus dem Auftragsverzeichnis, validiert Benutzer,
    berechnet Preise, erstellt Deckblätter und organisiert die Ausgabe
    in die Ordnerstruktur (02_Druckfertig, 04_Fehler, etc.).
    """
    # Logging einrichten (MUSS vor allem anderen kommen)
    log_level = "DEBUG" if not verbose else settings.log_level
    setup_logging(level=log_level, log_file=settings.log_file)

    settings.parallel_processing=sequential
    if do_print is not None:
        settings.auto_print = do_print

    # FileOrganizer initialisieren
    organizer = FileOrganizer()
    organizer.ensure_directory_structure()

    orders_dir = orders_dir or organizer.get_input_dir()

    console.print(f"\n[bold blue]Skriptendruck - Verarbeitung[/bold blue]")
    console.print(f"Aufträge:     {orders_dir}")
    console.print(f"Druckfertig:  {organizer.base_path / organizer.DIR_PRINT}")
    console.print(f"Originale:    {organizer.get_originals_dir()}")
    if settings.auto_print:
        console.print(f"[yellow]DRUCK-MODUS AKTIVIERT[/yellow] (Drucker: {settings.printer_sw} / {settings.printer_color})")
    console.print()

    pipeline = OrderPipeline(file_organizer=organizer)

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
            organize_files=no_organize,
            print_orders=do_print
        )
        progress.update(task, completed=len(orders))

    _display_summary(processed_orders, organizer)


@app.command()
def init(
    base_path: Optional[Path] = typer.Option(
        None, "--base-path", "-p",
        help="Basispfad für die Ordnerstruktur"
    ),
) -> None:
    """
    Initialisiert die Ordnerstruktur und Beispieldaten.
    """
    setup_logging(level=settings.log_level)
    console.print("\n[bold blue]Initialisiere Skriptendruck...[/bold blue]\n")

    organizer = FileOrganizer(base_path=base_path) if base_path else FileOrganizer()
    organizer.ensure_directory_structure()
    console.print(f"[green]âœ“[/green] Ordnerstruktur erstellt unter: {organizer.base_path}")

    pricing_service = PricingService()
    binding_path = Path("data/binding_sizes.json")
    if binding_path.exists():
        console.print(f"[yellow]Ãœberspringe: {binding_path} existiert bereits[/yellow]")
    else:
        pricing_service.export_default_binding_sizes_json(binding_path)
        console.print(f"[green]âœ“[/green] Erstellt: {binding_path}")

    blacklist_path = Path("data/blacklist.txt")
    if blacklist_path.exists():
        console.print(f"[yellow]Ãœberspringe: {blacklist_path} existiert bereits[/yellow]")
    else:
        blacklist_path.parent.mkdir(parents=True, exist_ok=True)
        with open(blacklist_path, "w", encoding="utf-8") as f:
            f.write("# Blockierte Benutzer (RZ-Kennungen)\n# Ein Username pro Zeile\n")
        console.print(f"[green]âœ“[/green] Erstellt: {blacklist_path}")

    users_csv_path = Path("data/users_fallback.csv")
    if users_csv_path.exists():
        console.print(f"[yellow]Ãœberspringe: {users_csv_path} existiert bereits[/yellow]")
    else:
        users_csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(users_csv_path, "w", encoding="utf-8") as f:
            f.write("# Format: username firstname lastname faculty\n# Beispiel:\n# mus43225 Sebastian MÃ¼llner M\n")
        console.print(f"[green]âœ“[/green] Erstellt: {users_csv_path}")

    # Ordnerstruktur anzeigen
    console.print(f"\n[bold]Ordnerstruktur:[/bold]")
    console.print(f"  {organizer.base_path}/")
    console.print(f"    â”œâ”€â”€ {organizer.DIR_INPUT}/")
    console.print(f"    â”œâ”€â”€ {organizer.DIR_PRINT}/")
    console.print(f"    â”‚   â”œâ”€â”€ {organizer.DIR_PRINT_SW}/")
    console.print(f"    â”‚   â”‚   â””â”€â”€ {organizer.DIR_PRINTED}/")
    console.print(f"    â”‚   â””â”€â”€ {organizer.DIR_PRINT_COLOR}/")
    console.print(f"    â”‚       â””â”€â”€ {organizer.DIR_PRINTED}/")
    console.print(f"    â”œâ”€â”€ {organizer.DIR_ORIGINALS}/")
    console.print(f"    â”œâ”€â”€ {organizer.DIR_ERRORS}/")
    console.print(f"    â”‚   â”œâ”€â”€ benutzer_nicht_gefunden/")
    console.print(f"    â”‚   â”œâ”€â”€ gesperrt/")
    console.print(f"    â”‚   â”œâ”€â”€ zu_wenig_seiten/")
    console.print(f"    â”‚   â”œâ”€â”€ zu_viele_seiten/")
    console.print(f"    â”‚   â”œâ”€â”€ passwortgeschuetzt/")
    console.print(f"    â”‚   â””â”€â”€ sonstige/")
    console.print(f"    â””â”€â”€ {organizer.DIR_MANUAL}/")
    console.print("\n[green]Initialisierung abgeschlossen![/green]")


@app.command()
def stats(
    orders_dir: Optional[Path] = typer.Option(
        None, "--orders-dir", "-i", help="Verzeichnis mit Aufträgen"
    ),
) -> None:
    """Zeigt Statistiken Ã¼ber vorhandene Aufträge."""
    setup_logging(level=settings.log_level)
    organizer = FileOrganizer()
    orders_dir = orders_dir or organizer.get_input_dir()

    pipeline = OrderPipeline()
    orders = pipeline.discover_orders(orders_dir)

    if not orders:
        console.print("[yellow]Keine Aufträge gefunden.[/yellow]")
        return

    table = Table(title=f"Statistik: {orders_dir}")
    table.add_column("Metrik", style="cyan")
    table.add_column("Wert", style="green")
    table.add_row("Anzahl Aufträge", str(len(orders)))
    total_size = sum(o.file_size_bytes for o in orders)
    table.add_row("GesamtgrÃ¶ÃŸe", f"{total_size / 1024 / 1024:.2f} MB")
    console.print()
    console.print(table)


@app.command()
def export_excel(
    output_dir: Optional[Path] = typer.Option(
        None, "--output-dir", "-o", help="Ausgabeverzeichnis fÃ¼r Excel-Dateien"
    ),
        days: int = typer.Option(30, "--days", "-d", help="Anzahl Tage rÃ¼ckwirkend"),
) -> None:
    """Exportiert Auftrags- und Abrechnungslisten nach Excel."""
    setup_logging(level=settings.log_level)
    console.print(f"\n[bold blue]Excel-Export[/bold blue]\n")

    output_dir = output_dir or settings.get_excel_export_directory()
    output_dir.mkdir(parents=True, exist_ok=True)

    db_service = DatabaseService()
    excel_service = ExcelExportService()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Exportiere Auftragsliste...", total=None)
        orders = db_service.get_orders_by_date_range(start_date, end_date)
        if orders:
            orders_path = output_dir / f"Auftragsliste_{end_date.strftime('%Y%m%d')}.xlsx"
            if excel_service.export_orders_list(orders, orders_path):
                console.print(f"[green]âœ“[/green] Auftragsliste: {orders_path}")
            else:
                console.print(f"[red]âœ—[/red] Fehler beim Export der Auftragsliste")
        else:
            console.print("[yellow]Keine Aufträge im Zeitraum gefunden[/yellow]")
        progress.update(task, completed=True)

        task = progress.add_task("Exportiere Abrechnungsliste...", total=None)
        billings = db_service.get_unpaid_billings()
        if billings:
            billings_path = output_dir / f"Abrechnungsliste_{end_date.strftime('%Y%m%d')}.xlsx"
            if excel_service.export_billing_list(billings, billings_path):
                console.print(f"[green]âœ“[/green] Abrechnungsliste: {billings_path}")
            else:
                console.print(f"[red]âœ—[/red] Fehler beim Export der Abrechnungsliste")
        else:
            console.print("[yellow]Keine offenen Abrechnungen[/yellow]")
        progress.update(task, completed=True)
    console.print()


@app.command()
def db_stats() -> None:
    """Zeigt Datenbank-Statistiken."""
    setup_logging(level=settings.log_level)
    console.print(f"\n[bold blue]Datenbank-Statistiken[/bold blue]\n")

    db_service = DatabaseService()
    db_stats_data = db_service.get_statistics()

    table = Table()
    table.add_column("Metrik", style="cyan")
    table.add_column("Wert", style="green")
    table.add_row("Gesamt Aufträge", str(db_stats_data["total_orders"]))
    table.add_row("Erfolgreich", str(db_stats_data["successful_orders"]))
    table.add_row("Fehler", str(db_stats_data["error_orders"]))
    table.add_row("Gesamtumsatz", f"{db_stats_data['total_revenue']:.2f} â‚¬")
    console.print(table)
    console.print()


@app.command()
def credentials(
    action: str = typer.Argument(
        "setup",
        help="Aktion: 'setup' zum Einrichten, 'check' zum Prüfen, 'delete' zum Löschen"
    ),
) -> None:
    """
    Verwaltet verschlüsselte LDAP-Zugangsdaten.

    Speichert LDAP-Passwort verschlüsselt, sodass es nicht im Klartext
    in der .env Datei stehen muss. Einmalig als Admin ausführen.
    """
    setup_logging(level=settings.log_level)

    from ..config.credentials import (
        CREDENTIALS_FILE, KEY_FILE, has_credentials,
        load_credentials, save_credentials,
    )

    if action == "check":
        if has_credentials():
            creds = load_credentials()
            if creds:
                console.print("[green]✓[/green] Credentials vorhanden und entschlüsselbar")
                for key in creds:
                    masked = creds[key][:3] + "***" if len(creds[key]) > 3 else "***"
                    console.print(f"  {key}: {masked}")
            else:
                console.print("[red]✗[/red] Credentials vorhanden aber nicht entschlüsselbar")
        else:
            console.print("[yellow]Keine Credentials eingerichtet[/yellow]")
            console.print("Einrichten mit: skriptendruck credentials setup")
        return

    if action == "delete":
        from pathlib import Path as P
        deleted = False
        for fname in [CREDENTIALS_FILE, KEY_FILE]:
            p = P(fname)
            if p.exists():
                p.unlink()
                console.print(f"[green]✓[/green] Gelöscht: {fname}")
                deleted = True
        if not deleted:
            console.print("[yellow]Keine Credentials-Dateien gefunden[/yellow]")
        return

    if action == "setup":
        console.print("\n[bold blue]LDAP-Credentials einrichten[/bold blue]\n")
        console.print(
            "Das Passwort wird verschlüsselt gespeichert und muss nicht\n"
            "in der .env Datei stehen.\n"
        )

        # LDAP Bind DN
        current_dn = settings.ldap_bind_dn or ""
        bind_dn = typer.prompt(
            "LDAP Bind DN (z.B. abc12345@hs-regensburg.de)",
            default=current_dn,
        )

        # Passwort (verdeckte Eingabe)
        password = typer.prompt("LDAP Passwort", hide_input=True)
        password_confirm = typer.prompt("Passwort bestätigen", hide_input=True)

        if password != password_confirm:
            console.print("[red]Passwörter stimmen nicht überein![/red]")
            raise typer.Exit(1)

        # Speichern
        creds = {
            "ldap_bind_dn": bind_dn,
            "ldap_bind_password": password,
        }
        cred_path = save_credentials(creds)

        console.print(f"\n[green]✓[/green] Credentials verschlüsselt gespeichert: {cred_path}")
        console.print(
            "\n[bold]Wichtig:[/bold] LDAP_BIND_PASSWORD aus der .env Datei entfernen!\n"
            "Die .env braucht nur noch LDAP_ENABLED=true und die Server-Einstellungen."
        )
        return

    console.print(f"[red]Unbekannte Aktion: {action}[/red]")
    console.print("Verfügbar: setup, check, delete")


def _display_summary(orders: list, organizer: FileOrganizer) -> None:
    """Zeigt Zusammenfassung der verarbeiteten Aufträge."""
    console.print("\n[bold blue]Zusammenfassung[/bold blue]\n")

    total = len(orders)
    success = sum(1 for o in orders if o.status == OrderStatus.PROCESSED)
    errors = total - success

    console.print(f"Gesamt: {total}")
    console.print(f"[green]Erfolgreich: {success}[/green]")
    if errors > 0:
        console.print(f"[red]Fehler: {errors}[/red]")
    console.print()

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
                    str(order.order_id), order.filename, user_str,
                    str(order.page_count or "?"), price_str, target,
                )
        console.print(success_table)
        console.print()

    if errors > 0:
        error_table = Table(title="Fehler")
        error_table.add_column("ID", style="cyan", width=6)
        error_table.add_column("Dateiname")
        error_table.add_column("Status", style="red")
        error_table.add_column("Nachricht")

        for order in orders:
            if order.is_error:
                error_table.add_row(
                    str(order.order_id), order.filename,
                    order.status.value, order.error_message or ""
                )
        console.print(error_table)
        console.print()


@app.callback()
def main() -> None:
    """Skriptendruck - Modernisiertes Druckauftrags-Verwaltungssystem."""
    pass
