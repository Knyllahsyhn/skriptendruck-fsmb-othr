"""REST-API Routen für AJAX-Aktionen (Aufträge starten, löschen, Excel-Export)."""
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy import select

from ..auth import get_current_user
from ...config import get_logger, settings
from ...database.models import OrderRecord, BillingRecord
from ...database.service import DatabaseService


def _get_excel_service():
    """Lazy-Import des ExcelExportService (vermeidet pypdf-Dependency beim Startup)."""
    from skriptendruck.services.excel_service import ExcelExportService
    return ExcelExportService()


logger = get_logger("web.routes.api")

router = APIRouter(tags=["api"])


def _get_db() -> DatabaseService:
    """Gibt eine DatabaseService-Instanz zurück."""
    db_path = settings.database_path
    if not db_path.is_absolute():
        db_path = settings.base_path / db_path
    return DatabaseService(db_path=db_path)


def _require_auth(request: Request) -> tuple:
    """Prüft Authentifizierung für API-Calls. Returns (user, error_response)."""
    user = get_current_user(request)
    if not user:
        return None, JSONResponse(
            status_code=401,
            content={"error": "Nicht authentifiziert"},
        )
    return user, None


# ---------------------------------------------------------------------------
# Pipeline-Verarbeitung (wird in einem Thread ausgeführt)
# ---------------------------------------------------------------------------

def _run_pipeline_for_order(order_record: OrderRecord) -> dict:
    """Führt die komplette Pipeline für einen einzelnen Auftrag aus.

    Liest den Dateipfad aus dem DB-Record, verarbeitet die PDF
    (Dateiname parsen, User validieren, PDF analysieren, Preis berechnen,
    Deckblatt erstellen, PDFs mergen, Dateien organisieren) und
    aktualisiert den DB-Status.

    Returns:
        dict mit 'success' (bool) und 'message' (str)
    """
    from ...processing.pipeline import OrderPipeline
    from ...services.file_organizer import FileOrganizer
    from ...models import OrderStatus

    filepath = Path(order_record.original_filepath) if order_record.original_filepath else None

    if filepath is None or not filepath.exists():
        return {
            "success": False,
            "message": f"Quelldatei nicht gefunden: {filepath}",
        }

    db = _get_db()
    organizer = FileOrganizer()
    organizer.ensure_directory_structure()

    pipeline = OrderPipeline(db_service=db, file_organizer=organizer)

    # Order-Objekt aus der Datei erzeugen
    from ...models import Order
    import os

    order = Order(
        order_id=order_record.order_id,
        filename=order_record.filename,
        filepath=filepath,
        file_size_bytes=filepath.stat().st_size,
        operator=order_record.operator or os.getenv("USER", os.getenv("USERNAME", "dashboard")),
    )

    # Pipeline-Verarbeitung (ein einzelner Auftrag)
    work_dir = Path(tempfile.mkdtemp(prefix="skriptendruck_web_"))
    try:
        pipeline.process_single_order(order, work_dir)

        # Dateien organisieren
        if order.status == OrderStatus.PROCESSED:
            organizer.organize_batch([order])

        # DB-Record aktualisieren
        with db.SessionLocal() as session:
            stmt = select(OrderRecord).where(OrderRecord.order_id == order.order_id)
            rec = session.scalar(stmt)
            if rec:
                rec.status = order.status.value
                rec.error_message = order.error_message
                rec.processed_at = datetime.now()
                rec.page_count = order.page_count
                rec.is_password_protected = order.is_password_protected
                if order.user:
                    rec.username = order.user.username
                    rec.first_name = order.user.first_name
                    rec.last_name = order.user.last_name
                    rec.faculty = order.user.faculty
                if order.color_mode:
                    rec.color_mode = order.color_mode.value
                if order.binding_type:
                    rec.binding_type = order.binding_type.value
                if order.price_calculation:
                    rec.price_per_page = order.price_calculation.price_per_page
                    rec.pages_price = order.price_calculation.pages_price
                    rec.binding_price = order.price_calculation.binding_price
                    rec.total_price = order.price_calculation.total_price
                    rec.price_after_deposit = order.price_calculation.price_after_deposit
                    rec.binding_size_mm = order.price_calculation.binding_size_mm
                if order.coversheet_path:
                    rec.coversheet_path = str(order.coversheet_path)
                if order.merged_pdf_path:
                    rec.merged_pdf_path = str(order.merged_pdf_path)
                session.commit()

        # Billing-Record erzeugen
        if order.status == OrderStatus.PROCESSED and order.user and order.price_calculation:
            try:
                db.create_billing_record(order)
            except Exception as exc:
                logger.warning(f"Billing-Record Fehler: {exc}")

        if order.is_error:
            return {"success": False, "message": f"Verarbeitung fehlgeschlagen: {order.error_message}"}

        return {
            "success": True,
            "message": (
                f"Auftrag #{order.order_id} erfolgreich verarbeitet "
                f"({order.page_count} Seiten, Status: {order.status.value})"
            ),
        }
    except Exception as exc:
        logger.error(f"Pipeline-Fehler für Order #{order_record.order_id}: {exc}")
        # Status auf Fehler setzen
        try:
            with db.SessionLocal() as session:
                stmt = select(OrderRecord).where(OrderRecord.order_id == order_record.order_id)
                rec = session.scalar(stmt)
                if rec:
                    rec.status = "error_unknown"
                    rec.error_message = str(exc)
                    rec.processed_at = datetime.now()
                    session.commit()
        except Exception:
            pass
        return {"success": False, "message": str(exc)}
    finally:
        # Temp-Verzeichnis aufräumen
        import shutil
        shutil.rmtree(str(work_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# API-Endpunkte
# ---------------------------------------------------------------------------

@router.post("/orders/{order_id}/start")
async def start_order(request: Request, order_id: int):
    """Startet die Pipeline-Verarbeitung für einen 'pending' Auftrag.

    Führt die vollständige Verarbeitung aus:
    Dateiname parsen → User validieren → PDF analysieren →
    Preis berechnen → Deckblatt → Merge → Dateien organisieren.
    """
    user, error = _require_auth(request)
    if error:
        return error

    try:
        db = _get_db()
        with db.SessionLocal() as session:
            stmt = select(OrderRecord).where(OrderRecord.order_id == order_id)
            order = session.scalar(stmt)

            if not order:
                return JSONResponse(status_code=404, content={"error": "Auftrag nicht gefunden"})

            if order.status not in ("pending",):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": (
                            f"Auftrag kann im Status '{order.status}' nicht gestartet werden. "
                            f"Nur Aufträge mit Status 'pending' können gestartet werden."
                        )
                    },
                )

            # Operator setzen
            order.operator = user["username"]
            order.status = "processing"
            session.commit()

            # Snapshot der benötigten Daten für die Thread-Ausführung
            order_snapshot = OrderRecord(
                order_id=order.order_id,
                filename=order.filename,
                original_filepath=order.original_filepath,
                operator=order.operator,
            )

        # Pipeline in einem Thread ausführen (blockiert nicht den Event-Loop)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_pipeline_for_order, order_snapshot)

        if result["success"]:
            logger.info(f"Auftrag #{order_id} von {user['username']} verarbeitet: {result['message']}")
            return JSONResponse(content={"success": True, "message": result["message"]})
        else:
            logger.warning(f"Auftrag #{order_id} fehlgeschlagen: {result['message']}")
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": result["message"]},
            )

    except Exception as e:
        logger.error(f"Fehler beim Starten von Auftrag #{order_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.delete("/orders/{order_id}")
async def delete_order(request: Request, order_id: int):
    """Löscht einen Auftrag."""
    user, error = _require_auth(request)
    if error:
        return error

    try:
        db = _get_db()
        with db.SessionLocal() as session:
            stmt = select(OrderRecord).where(OrderRecord.order_id == order_id)
            order = session.scalar(stmt)

            if not order:
                return JSONResponse(status_code=404, content={"error": "Auftrag nicht gefunden"})

            session.delete(order)
            session.commit()

            logger.info(f"Auftrag #{order_id} von {user['username']} gelöscht")
            return JSONResponse(content={"success": True, "message": f"Auftrag #{order_id} gelöscht"})

    except Exception as e:
        logger.error(f"Fehler beim Löschen von Auftrag #{order_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/scan")
async def trigger_scan(request: Request):
    """Löst einen manuellen Scan des Auftragsordners aus."""
    user, error = _require_auth(request)
    if error:
        return error

    try:
        from ..file_watcher import scan_orders_directory

        loop = asyncio.get_running_loop()
        count = await loop.run_in_executor(None, scan_orders_directory, None)
        return JSONResponse(content={
            "success": True,
            "message": f"{count} neue Aufträge erkannt" if count else "Keine neuen Aufträge",
            "new_orders": count,
        })
    except Exception as e:
        logger.error(f"Fehler beim manuellen Scan: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/export/orders")
async def export_orders_excel(request: Request):
    """Exportiert alle Aufträge als Excel-Datei."""
    user, error = _require_auth(request)
    if error:
        return error

    try:
        db = _get_db()
        with db.SessionLocal() as session:
            stmt = select(OrderRecord).order_by(OrderRecord.created_at.desc())
            orders = list(session.scalars(stmt))

            if not orders:
                return JSONResponse(status_code=404, content={"error": "Keine Aufträge vorhanden"})

            # Excel-Export
            excel_service = _get_excel_service()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Versuche das konfigurierte Export-Verzeichnis, Fallback auf temp
            try:
                export_dir = settings.get_excel_export_directory()
            except Exception:
                export_dir = Path(tempfile.mkdtemp())

            output_path = export_dir / f"Auftragsliste_{timestamp}.xlsx"

            success = excel_service.export_orders_list(orders, output_path)

            if success and output_path.exists():
                logger.info(f"Excel-Export erstellt: {output_path} (von {user['username']})")
                return FileResponse(
                    path=str(output_path),
                    filename=output_path.name,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                return JSONResponse(status_code=500, content={"error": "Excel-Export fehlgeschlagen"})

    except Exception as e:
        logger.error(f"Fehler beim Excel-Export: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/export/billing")
async def export_billing_excel(request: Request):
    """Exportiert alle Abrechnungen als Excel-Datei."""
    user, error = _require_auth(request)
    if error:
        return error

    try:
        db = _get_db()
        with db.SessionLocal() as session:
            stmt = select(BillingRecord).order_by(BillingRecord.billing_date.desc())
            billings = list(session.scalars(stmt))

            if not billings:
                return JSONResponse(status_code=404, content={"error": "Keine Abrechnungen vorhanden"})

            excel_service = _get_excel_service()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            try:
                export_dir = settings.get_excel_export_directory()
            except Exception:
                export_dir = Path(tempfile.mkdtemp())

            output_path = export_dir / f"Abrechnungsliste_{timestamp}.xlsx"

            success = excel_service.export_billing_list(billings, output_path)

            if success and output_path.exists():
                logger.info(f"Abrechnungs-Export erstellt: {output_path} (von {user['username']})")
                return FileResponse(
                    path=str(output_path),
                    filename=output_path.name,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                return JSONResponse(status_code=500, content={"error": "Excel-Export fehlgeschlagen"})

    except Exception as e:
        logger.error(f"Fehler beim Abrechnungs-Export: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/statistics")
async def get_statistics(request: Request):
    """Gibt Statistiken als JSON zurück."""
    user, error = _require_auth(request)
    if error:
        return error

    try:
        db = _get_db()
        stats = db.get_statistics()
        return JSONResponse(content=stats)
    except Exception as e:
        logger.error(f"Fehler beim Laden der Statistiken: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
