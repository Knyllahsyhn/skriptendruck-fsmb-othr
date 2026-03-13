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
# Druck-Hilfsfunktion
# ---------------------------------------------------------------------------

def _try_print_order(order) -> bool:
    """Versucht den Auftrag an den konfigurierten Drucker zu senden.

    Fehler beim Drucken werden geloggt, führen aber NICHT zu einem
    Fehler-Status des Auftrags – der Auftrag bleibt 'processed'.

    Returns:
        True wenn der Druckauftrag erfolgreich gesendet wurde.
    """
    try:
        from ...services.printing_service import PrintingService

        printer = PrintingService()
        success = printer.print_order(order)
        if success:
            logger.info(
                f"Druckauftrag für Order #{order.order_id} erfolgreich gesendet "
                f"(Backend: {printer.backend_name})"
            )
        else:
            logger.warning(
                f"Druckauftrag für Order #{order.order_id} fehlgeschlagen "
                f"(Backend: {printer.backend_name})"
            )
        return success
    except Exception as exc:
        logger.warning(f"Druck-Fehler für Order #{order.order_id}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Pipeline-Verarbeitung (wird in einem Thread ausgeführt)
# ---------------------------------------------------------------------------

def _run_pipeline_for_order(order_record: OrderRecord, enable_printing: bool = None) -> dict:
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

        # ----- Drucken (optional, Dashboard-Toggle überschreibt .env) -----
        printed = False
        # enable_printing=None → Fallback auf settings.enable_printing
        # enable_printing=True/False → überschreibt .env-Einstellung
        should_print = enable_printing if enable_printing is not None else settings.enable_printing
        if order.status == OrderStatus.PROCESSED and should_print:
            printed = _try_print_order(order)

        if order.is_error:
            return {"success": False, "message": f"Verarbeitung fehlgeschlagen: {order.error_message}"}

        msg = (
            f"Auftrag #{order.order_id} erfolgreich verarbeitet "
            f"({order.page_count} Seiten, Status: {order.status.value})"
        )
        if printed:
            msg += " – Druckauftrag gesendet"
        elif should_print:
            msg += " – Druck fehlgeschlagen (Auftrag trotzdem abgeschlossen)"

        return {"success": True, "message": msg}
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

    Akzeptiert einen optionalen JSON-Body mit ``enable_printing`` (bool).
    Wenn gesetzt, überschreibt dieser Wert die .env-Einstellung
    ``ENABLE_PRINTING``. Wird vom Dashboard-Printing-Toggle gesendet.
    """
    user, error = _require_auth(request)
    if error:
        return error

    # Optionalen Body auslesen (enable_printing)
    enable_printing = None
    try:
        body = await request.json()
        if isinstance(body, dict) and "enable_printing" in body:
            enable_printing = bool(body["enable_printing"])
    except Exception:
        pass  # Kein JSON-Body → Fallback auf .env

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
        import functools
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            functools.partial(_run_pipeline_for_order, order_snapshot, enable_printing=enable_printing),
        )

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


@router.post("/orders/{order_id}/cancel")
async def cancel_order(request: Request, order_id: int):
    """Bricht einen Auftrag ab.
    
    Kann Aufträge im Status 'pending' oder 'processing' abbrechen.
    Setzt den Status auf 'cancelled' und speichert einen Timestamp.
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

            # Nur pending und processing können abgebrochen werden
            if order.status not in ("pending", "processing"):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": (
                            f"Auftrag im Status '{order.status}' kann nicht abgebrochen werden. "
                            f"Nur Aufträge mit Status 'pending' oder 'processing' können abgebrochen werden."
                        )
                    },
                )

            # Status auf cancelled setzen
            previous_status = order.status
            order.status = "cancelled"
            order.error_message = f"Abgebrochen von {user['username']} (vorheriger Status: {previous_status})"
            order.processed_at = datetime.now()
            session.commit()

            logger.info(f"Auftrag #{order_id} von {user['username']} abgebrochen (vorher: {previous_status})")
            return JSONResponse(content={
                "success": True, 
                "message": f"Auftrag #{order_id} wurde abgebrochen",
                "previous_status": previous_status
            })

    except Exception as e:
        logger.error(f"Fehler beim Abbrechen von Auftrag #{order_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/orders/{order_id}/status")
async def get_order_status(request: Request, order_id: int):
    """Gibt den aktuellen Status eines Auftrags zurück.
    
    Nützlich für Polling/Live-Updates während der Verarbeitung.
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

            return JSONResponse(content={
                "success": True,
                "order_id": order.order_id,
                "status": order.status,
                "filename": order.filename,
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "processed_at": order.processed_at.isoformat() if order.processed_at else None,
                "page_count": order.page_count,
                "total_price": float(order.total_price) if order.total_price else None,
                "error_message": order.error_message,
                "username": order.username,
                "first_name": order.first_name,
                "last_name": order.last_name,
            })

    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Status von Auftrag #{order_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/scan")
async def trigger_scan(request: Request):
    """Löst einen manuellen Scan des Auftragsordners aus.
    
    Gibt detaillierte Debugging-Informationen zurück:
    - base_path: Der konfigurierte BASE_PATH
    - orders_dir: Der vollständige Pfad zum Auftragsordner
    - dir_exists: Ob das Verzeichnis existiert
    - dir_readable: Ob das Verzeichnis lesbar ist
    - total_files: Anzahl aller Dateien im Ordner
    - pdf_files: Anzahl der PDF-Dateien
    - new_orders: Anzahl neu registrierter Aufträge
    - pdf_list: Liste der gefundenen PDF-Dateinamen (max. 20)
    """
    user, error = _require_auth(request)
    if error:
        return error

    try:
        from ..file_watcher import manual_scan

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, manual_scan)
        
        # Benutzerfreundliche Nachricht erstellen
        if result.get("error"):
            message = f"Fehler: {result['error']}"
        elif result.get("new_orders", 0) > 0:
            message = f"{result['new_orders']} neue Aufträge erkannt"
        elif result.get("pdf_files", 0) > 0:
            message = f"Keine neuen Aufträge ({result['pdf_files']} PDFs bereits bekannt)"
        else:
            message = "Keine PDF-Dateien im Auftragsordner gefunden"
        
        result["message"] = message
        return JSONResponse(content=result)
        
    except Exception as e:
        logger.error(f"Fehler beim manuellen Scan: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": str(e),
            "message": f"Interner Fehler: {e}"
        })


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


@router.post("/orders/start-all")
async def start_all_pending_orders(request: Request):
    """Startet die Pipeline für ALLE pending Aufträge nacheinander.

    Gibt für jeden Auftrag ein Ergebnis zurück (success/fail).
    Wenn ein Auftrag fehlschlägt, werden die anderen trotzdem verarbeitet.

    Akzeptiert einen optionalen JSON-Body mit ``enable_printing`` (bool).
    """
    user, error = _require_auth(request)
    if error:
        return error

    # Optionalen Body auslesen (enable_printing)
    enable_printing = None
    try:
        body = await request.json()
        if isinstance(body, dict) and "enable_printing" in body:
            enable_printing = bool(body["enable_printing"])
    except Exception:
        pass

    try:
        db = _get_db()
        with db.SessionLocal() as session:
            stmt = select(OrderRecord).where(OrderRecord.status == "pending").order_by(OrderRecord.created_at.asc())
            pending_orders = list(session.scalars(stmt))

            if not pending_orders:
                return JSONResponse(content={
                    "success": True,
                    "message": "Keine ausstehenden Aufträge vorhanden",
                    "results": [],
                    "total": 0,
                })

            # Set all to processing and collect snapshots
            snapshots = []
            for order in pending_orders:
                order.operator = user["username"]
                order.status = "processing"
                snapshots.append(OrderRecord(
                    order_id=order.order_id,
                    filename=order.filename,
                    original_filepath=order.original_filepath,
                    operator=order.operator,
                ))
            session.commit()

        # Process each order sequentially in a thread
        import functools
        loop = asyncio.get_running_loop()
        results = []
        for snap in snapshots:
            result = await loop.run_in_executor(
                None,
                functools.partial(_run_pipeline_for_order, snap, enable_printing=enable_printing),
            )
            results.append({
                "order_id": snap.order_id,
                "filename": snap.filename,
                **result,
            })

        success_count = sum(1 for r in results if r["success"])
        fail_count = len(results) - success_count
        logger.info(
            f"Bulk-Verarbeitung von {user['username']}: "
            f"{success_count} erfolgreich, {fail_count} fehlgeschlagen"
        )

        return JSONResponse(content={
            "success": True,
            "message": f"{success_count} von {len(results)} Aufträgen erfolgreich verarbeitet",
            "results": results,
            "total": len(results),
            "success_count": success_count,
            "fail_count": fail_count,
        })

    except Exception as e:
        logger.error(f"Fehler bei Bulk-Verarbeitung: {e}")
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


# ---------------------------------------------------------------------------
# Print Endpoint - Manuelles Drucken für verarbeitete Aufträge
# ---------------------------------------------------------------------------

@router.post("/orders/{order_id}/print")
async def print_order(request: Request, order_id: int):
    """Druckt einen verarbeiteten Auftrag aus dem 02_Druckfertig Ordner.
    
    Nur für Aufträge mit Status 'processed' verfügbar.
    Setzt den Status nach erfolgreichem Druck auf 'printed'.
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

            if order.status != "processed":
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": (
                            f"Auftrag im Status '{order.status}' kann nicht gedruckt werden. "
                            f"Nur Aufträge mit Status 'processed' können gedruckt werden."
                        )
                    },
                )

            # Druckfertige PDF finden
            merged_pdf_path = Path(order.merged_pdf_path) if order.merged_pdf_path else None
            
            if not merged_pdf_path or not merged_pdf_path.exists():
                # Versuche alternativen Pfad im 02_Druckfertig Ordner
                druckfertig_dir = settings.base_path / "02_Druckfertig"
                if druckfertig_dir.exists():
                    possible_files = list(druckfertig_dir.glob(f"*{order.order_id}*.pdf"))
                    if possible_files:
                        merged_pdf_path = possible_files[0]
                
                if not merged_pdf_path or not merged_pdf_path.exists():
                    return JSONResponse(
                        status_code=404,
                        content={"error": "Druckfertige PDF-Datei nicht gefunden"}
                    )

            # Drucken
            from ...services.printing_service import PrintingService
            from ...models import Order, ColorMode

            # Temporäres Order-Objekt für den PrintingService
            temp_order = Order(
                order_id=order.order_id,
                filename=order.filename,
                filepath=Path(order.original_filepath) if order.original_filepath else merged_pdf_path,
                file_size_bytes=merged_pdf_path.stat().st_size,
                merged_pdf_path=merged_pdf_path,
                color_mode=ColorMode(order.color_mode) if order.color_mode else ColorMode.SW,
            )

            printer = PrintingService()
            if not printer.is_available:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Druckdienst nicht verfügbar"}
                )

            success = printer.print_order(temp_order)
            
            if success:
                # Status auf printed setzen
                order.status = "printed"
                order.processed_at = datetime.now()
                session.commit()
                
                logger.info(f"Auftrag #{order_id} von {user['username']} gedruckt (Backend: {printer.backend_name})")
                return JSONResponse(content={
                    "success": True,
                    "message": f"Auftrag #{order_id} wurde zum Drucker gesendet"
                })
            else:
                return JSONResponse(
                    status_code=500,
                    content={"error": "Druckauftrag fehlgeschlagen"}
                )

    except Exception as e:
        logger.error(f"Fehler beim Drucken von Auftrag #{order_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ---------------------------------------------------------------------------
# Bulk Actions - Mehrfachauswahl
# ---------------------------------------------------------------------------

@router.post("/orders/bulk-delete")
async def bulk_delete_orders(request: Request):
    """Löscht mehrere Aufträge auf einmal.
    
    Erwartet JSON-Body mit 'order_ids': [1, 2, 3, ...]
    """
    user, error = _require_auth(request)
    if error:
        return error

    try:
        body = await request.json()
        order_ids = body.get("order_ids", [])
        
        if not order_ids:
            return JSONResponse(
                status_code=400,
                content={"error": "Keine Aufträge ausgewählt"}
            )

        db = _get_db()
        deleted_count = 0
        errors = []
        
        with db.SessionLocal() as session:
            for order_id in order_ids:
                stmt = select(OrderRecord).where(OrderRecord.order_id == order_id)
                order = session.scalar(stmt)
                
                if order:
                    session.delete(order)
                    deleted_count += 1
                else:
                    errors.append(f"Auftrag #{order_id} nicht gefunden")
            
            session.commit()

        logger.info(f"Bulk-Delete von {user['username']}: {deleted_count} Aufträge gelöscht")
        
        return JSONResponse(content={
            "success": True,
            "message": f"{deleted_count} Aufträge gelöscht",
            "deleted_count": deleted_count,
            "errors": errors if errors else None
        })

    except Exception as e:
        logger.error(f"Fehler bei Bulk-Delete: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/orders/bulk-print")
async def bulk_print_orders(request: Request):
    """Druckt mehrere verarbeitete Aufträge auf einmal.
    
    Erwartet JSON-Body mit 'order_ids': [1, 2, 3, ...]
    Nur Aufträge mit Status 'processed' werden gedruckt.
    """
    user, error = _require_auth(request)
    if error:
        return error

    try:
        body = await request.json()
        order_ids = body.get("order_ids", [])
        
        if not order_ids:
            return JSONResponse(
                status_code=400,
                content={"error": "Keine Aufträge ausgewählt"}
            )

        from ...services.printing_service import PrintingService
        from ...models import Order, ColorMode

        printer = PrintingService()
        if not printer.is_available:
            return JSONResponse(
                status_code=503,
                content={"error": "Druckdienst nicht verfügbar"}
            )

        db = _get_db()
        printed_count = 0
        skipped = []
        errors = []
        
        with db.SessionLocal() as session:
            for order_id in order_ids:
                stmt = select(OrderRecord).where(OrderRecord.order_id == order_id)
                order = session.scalar(stmt)
                
                if not order:
                    errors.append(f"Auftrag #{order_id} nicht gefunden")
                    continue
                
                if order.status != "processed":
                    skipped.append(f"#{order_id} ({order.status})")
                    continue
                
                # PDF finden
                merged_pdf_path = Path(order.merged_pdf_path) if order.merged_pdf_path else None
                if not merged_pdf_path or not merged_pdf_path.exists():
                    druckfertig_dir = settings.base_path / "02_Druckfertig"
                    if druckfertig_dir.exists():
                        possible_files = list(druckfertig_dir.glob(f"*{order.order_id}*.pdf"))
                        if possible_files:
                            merged_pdf_path = possible_files[0]
                
                if not merged_pdf_path or not merged_pdf_path.exists():
                    errors.append(f"#{order_id}: PDF nicht gefunden")
                    continue
                
                # Drucken
                temp_order = Order(
                    order_id=order.order_id,
                    filename=order.filename,
                    filepath=Path(order.original_filepath) if order.original_filepath else merged_pdf_path,
                    file_size_bytes=merged_pdf_path.stat().st_size,
                    merged_pdf_path=merged_pdf_path,
                    color_mode=ColorMode(order.color_mode) if order.color_mode else ColorMode.SW,
                )
                
                if printer.print_order(temp_order):
                    order.status = "printed"
                    order.processed_at = datetime.now()
                    printed_count += 1
                else:
                    errors.append(f"#{order_id}: Druck fehlgeschlagen")
            
            session.commit()

        logger.info(f"Bulk-Print von {user['username']}: {printed_count} Aufträge gedruckt")
        
        message_parts = [f"{printed_count} Aufträge gedruckt"]
        if skipped:
            message_parts.append(f"{len(skipped)} übersprungen (falscher Status)")
        if errors:
            message_parts.append(f"{len(errors)} Fehler")
        
        return JSONResponse(content={
            "success": True,
            "message": ", ".join(message_parts),
            "printed_count": printed_count,
            "skipped": skipped if skipped else None,
            "errors": errors if errors else None
        })

    except Exception as e:
        logger.error(f"Fehler bei Bulk-Print: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/orders/all-status")
async def get_all_orders_status(request: Request):
    """Gibt den Status aller Aufträge zurück (für Dashboard-Polling).
    
    Optimiert für schnelles Polling, gibt nur essentielle Daten zurück.
    """
    user, error = _require_auth(request)
    if error:
        return error

    try:
        db = _get_db()
        with db.SessionLocal() as session:
            stmt = select(OrderRecord).order_by(OrderRecord.created_at.desc()).limit(100)
            orders = session.scalars(stmt).all()
            
            orders_data = []
            counts = {"pending": 0, "processing": 0, "processed": 0, "printed": 0, "error": 0}
            
            for order in orders:
                status = order.status
                if status.startswith("error"):
                    counts["error"] += 1
                elif status in counts:
                    counts[status] += 1
                
                orders_data.append({
                    "order_id": order.order_id,
                    "status": order.status,
                    "filename": order.filename,
                    "page_count": order.page_count,
                    "total_price": float(order.total_price) if order.total_price else None,
                    "error_message": order.error_message,
                })
            
            return JSONResponse(content={
                "success": True,
                "orders": orders_data,
                "counts": counts
            })

    except Exception as e:
        logger.error(f"Fehler beim Abrufen aller Status: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
