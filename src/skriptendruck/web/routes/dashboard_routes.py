"""Dashboard-Routen (Hauptseiten)."""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from ..auth import get_current_user, require_login
from ...config import get_logger, settings
from ...database.service import DatabaseService
from ...models import OrderStatus

logger = get_logger("web.routes.dashboard")

router = APIRouter(tags=["dashboard"])


def _get_db() -> DatabaseService:
    """Gibt eine DatabaseService-Instanz zurück."""
    db_path = settings.database_path
    if not db_path.is_absolute():
        db_path = settings.base_path / db_path
    return DatabaseService(db_path=db_path)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Hauptseite / Dashboard-Übersicht mit 3-Spalten Kanban-Layout."""
    redirect = require_login(request)
    if redirect:
        return redirect
    
    user = get_current_user(request)
    
    try:
        db = _get_db()
        stats = db.get_statistics()
        
        with db.SessionLocal() as session:
            from ...database.models import OrderRecord
            from sqlalchemy import select, func, or_
            
            # Spalte 1: Ausstehende Aufträge (pending)
            stmt_pending = select(OrderRecord).where(
                OrderRecord.status == "pending"
            ).order_by(OrderRecord.created_at.asc())
            pending_orders_data = [_order_to_dict(o) for o in session.scalars(stmt_pending)]
            pending_count = len(pending_orders_data)
            
            # Spalte 2: In Verarbeitung (processing)
            stmt_processing = select(OrderRecord).where(
                OrderRecord.status == "processing"
            ).order_by(OrderRecord.created_at.asc())
            processing_orders_data = [_order_to_dict(o) for o in session.scalars(stmt_processing)]
            processing_count = len(processing_orders_data)
            
            # Spalte 3: Abgeschlossen (processed, printed, error_*, cancelled)
            # Zeige die letzten 20 abgeschlossenen Aufträge
            completed_statuses = [
                "processed", "printed", "validated", "cancelled",
                "error_user_not_found", "error_user_blocked", 
                "error_too_few_pages", "error_too_many_pages",
                "error_password_protected", "error_invalid_filename", "error_unknown"
            ]
            stmt_completed = select(OrderRecord).where(
                OrderRecord.status.in_(completed_statuses)
            ).order_by(OrderRecord.processed_at.desc().nullslast(), 
                      OrderRecord.created_at.desc()).limit(20)
            completed_orders_data = [_order_to_dict(o) for o in session.scalars(stmt_completed)]
            completed_count = len(completed_orders_data)
            
    except Exception as e:
        logger.error(f"Fehler beim Laden der Dashboard-Daten: {e}")
        stats = {"total_orders": 0, "successful_orders": 0, "error_orders": 0, "total_revenue": 0.0}
        pending_orders_data = []
        pending_count = 0
        processing_orders_data = []
        processing_count = 0
        completed_orders_data = []
        completed_count = 0
    
    templates = request.app.state.templates
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "stats": stats,
        # Spalte 1: Ausstehend
        "pending_orders": pending_orders_data,
        "pending_count": pending_count,
        # Spalte 2: In Verarbeitung
        "processing_orders": processing_orders_data,
        "processing_count": processing_count,
        # Spalte 3: Abgeschlossen
        "completed_orders": completed_orders_data,
        "completed_count": completed_count,
    })


@router.get("/orders", response_class=HTMLResponse)
async def orders_page(
    request: Request,
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
):
    """Auftragsübersicht."""
    redirect = require_login(request)
    if redirect:
        return redirect
    
    user = get_current_user(request)
    per_page = 25
    
    try:
        db = _get_db()
        with db.SessionLocal() as session:
            from ...database.models import OrderRecord
            from sqlalchemy import select, func
            
            # Base query
            base_stmt = select(OrderRecord)
            count_stmt = select(func.count(OrderRecord.id))
            
            if status:
                base_stmt = base_stmt.where(OrderRecord.status == status)
                count_stmt = count_stmt.where(OrderRecord.status == status)
            
            total = session.scalar(count_stmt) or 0
            total_pages = max(1, (total + per_page - 1) // per_page)
            
            stmt = base_stmt.order_by(OrderRecord.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
            orders = [_order_to_dict(o) for o in session.scalars(stmt)]
    except Exception as e:
        logger.error(f"Fehler beim Laden der Aufträge: {e}")
        orders = []
        total = 0
        total_pages = 1
    
    # Status-Optionen für Filter
    status_options = [
        ("pending", "Ausstehend"),
        ("processing", "In Verarbeitung"),
        ("validated", "Validiert"),
        ("processed", "Verarbeitet"),
        ("printed", "Gedruckt"),
        ("cancelled", "Abgebrochen"),
        ("error_user_not_found", "Fehler: Benutzer nicht gefunden"),
        ("error_user_blocked", "Fehler: Benutzer blockiert"),
        ("error_too_few_pages", "Fehler: Zu wenig Seiten"),
        ("error_too_many_pages", "Fehler: Zu viele Seiten"),
        ("error_password_protected", "Fehler: Passwortgeschützt"),
        ("error_invalid_filename", "Fehler: Ungültiger Dateiname"),
        ("error_unknown", "Fehler: Unbekannt"),
    ]
    
    templates = request.app.state.templates
    return templates.TemplateResponse("orders.html", {
        "request": request,
        "user": user,
        "orders": orders,
        "current_status": status,
        "status_options": status_options,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    })


@router.get("/statistics", response_class=HTMLResponse)
async def statistics_page(request: Request):
    """Statistik-Seite."""
    redirect = require_login(request)
    if redirect:
        return redirect
    
    user = get_current_user(request)
    
    try:
        db = _get_db()
        stats = db.get_statistics()
        
        # Erweiterte Statistiken
        with db.SessionLocal() as session:
            from ...database.models import OrderRecord, BillingRecord
            from sqlalchemy import select, func
            
            # Aufträge nach Status
            status_counts = {}
            status_rows = session.execute(
                select(OrderRecord.status, func.count(OrderRecord.id)).group_by(OrderRecord.status)
            ).all()
            for row_status, count in status_rows:
                status_counts[row_status] = count
            
            # Aufträge nach Fakultät
            faculty_counts = {}
            faculty_rows = session.execute(
                select(OrderRecord.faculty, func.count(OrderRecord.id))
                .where(OrderRecord.faculty.isnot(None))
                .group_by(OrderRecord.faculty)
            ).all()
            for fac, count in faculty_rows:
                faculty_counts[fac] = count
            
            # Umsatz nach Farbmodus
            color_stats = {}
            color_rows = session.execute(
                select(OrderRecord.color_mode, func.count(OrderRecord.id), func.sum(OrderRecord.total_price))
                .group_by(OrderRecord.color_mode)
            ).all()
            for cm, count, revenue in color_rows:
                color_stats[cm or "unbekannt"] = {"count": count, "revenue": round(revenue or 0, 2)}
            
            # Bindungstypen
            binding_stats = {}
            binding_rows = session.execute(
                select(OrderRecord.binding_type, func.count(OrderRecord.id))
                .group_by(OrderRecord.binding_type)
            ).all()
            for bt, count in binding_rows:
                binding_stats[bt or "ohne"] = count
            
            # Unbezahlte Abrechnungen
            unpaid_count = session.scalar(
                select(func.count(BillingRecord.id)).where(BillingRecord.is_paid == False)
            ) or 0
            unpaid_amount = session.scalar(
                select(func.sum(BillingRecord.remaining_amount)).where(BillingRecord.is_paid == False)
            ) or 0.0
    except Exception as e:
        logger.error(f"Fehler beim Laden der Statistiken: {e}")
        stats = {"total_orders": 0, "successful_orders": 0, "error_orders": 0, "total_revenue": 0.0}
        status_counts = {}
        faculty_counts = {}
        color_stats = {}
        binding_stats = {}
        unpaid_count = 0
        unpaid_amount = 0.0
    
    templates = request.app.state.templates
    return templates.TemplateResponse("statistics.html", {
        "request": request,
        "user": user,
        "stats": stats,
        "status_counts": status_counts,
        "faculty_counts": faculty_counts,
        "color_stats": color_stats,
        "binding_stats": binding_stats,
        "unpaid_count": unpaid_count,
        "unpaid_amount": round(unpaid_amount, 2),
    })


def _order_to_dict(order) -> dict:
    """Konvertiert ein OrderRecord-Objekt in ein Dictionary."""
    return {
        "id": order.id,
        "order_id": order.order_id,
        "filename": order.filename,
        "username": order.username,
        "first_name": order.first_name,
        "last_name": order.last_name,
        "faculty": order.faculty,
        "page_count": order.page_count,
        "color_mode": order.color_mode,
        "binding_type": order.binding_type,
        "total_price": order.total_price,
        "price_after_deposit": order.price_after_deposit,
        "status": order.status,
        "error_message": order.error_message,
        "created_at": order.created_at.strftime("%d.%m.%Y %H:%M") if order.created_at else "",
        "processed_at": order.processed_at.strftime("%d.%m.%Y %H:%M") if order.processed_at else "",
        "operator": order.operator,
        "merged_pdf_path": order.merged_pdf_path,
        "original_filepath": order.original_filepath,
    }
