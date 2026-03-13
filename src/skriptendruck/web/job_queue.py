"""
Asynchrone Job-Queue für die Druckauftragverarbeitung.

Features:
- asyncio.Queue für FIFO Job-Management
- Konfigurierbare Anzahl gleichzeitiger Worker
- Status-Tracking (queued, processing, completed, error)
- Queue-Position für wartende Aufträge
- Graceful Shutdown mit laufenden Jobs
"""
import asyncio
import functools
import os
import tempfile
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Any
from collections import OrderedDict

from ..config import get_logger, settings
from ..database.service import DatabaseService
from ..database.models import OrderRecord

logger = get_logger("web.job_queue")


class JobStatus(str, Enum):
    """Status eines Jobs in der Queue."""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class PrintJob:
    """Ein Druckauftrag in der Queue."""
    order_id: int
    filename: str
    original_filepath: str
    operator: str
    enable_printing: bool = False
    
    # Status-Tracking
    status: JobStatus = JobStatus.QUEUED
    queue_position: int = 0
    queued_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Ergebnis
    result_message: str = ""
    error_message: str = ""


class JobQueue:
    """
    Singleton Job-Queue für asynchrone Druckauftragsverarbeitung.
    
    Verwendet asyncio.Queue für FIFO-Verarbeitung und 
    Background-Worker für parallele Ausführung.
    """
    
    _instance: Optional["JobQueue"] = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        """Singleton Pattern - nur eine Queue-Instanz."""
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instance = instance
        return cls._instance
    
    def __init__(self):
        """Initialisiert die Queue (nur einmal)."""
        if self._initialized:
            return
            
        # Konfiguration aus Umgebungsvariablen
        self.max_concurrent_jobs = int(os.environ.get("MAX_CONCURRENT_JOBS", "2"))
        self.poll_interval = float(os.environ.get("QUEUE_POLL_INTERVAL", "1.0"))
        
        # Asyncio Queue
        self._queue: asyncio.Queue = asyncio.Queue()
        
        # Jobs-Registry (order_id -> PrintJob)
        self._jobs: OrderedDict[int, PrintJob] = OrderedDict()
        
        # Worker-Management
        self._workers: list[asyncio.Task] = []
        self._running = False
        self._active_jobs = 0
        self._semaphore: Optional[asyncio.Semaphore] = None
        
        # Statistiken
        self._total_processed = 0
        self._total_errors = 0
        
        self._initialized = True
        logger.info(
            f"JobQueue initialisiert: max_concurrent_jobs={self.max_concurrent_jobs}, "
            f"poll_interval={self.poll_interval}s"
        )
    
    async def start_workers(self, num_workers: int = None):
        """Startet die Background-Worker."""
        if self._running:
            return
            
        num_workers = num_workers or self.max_concurrent_jobs
        self._semaphore = asyncio.Semaphore(num_workers)
        self._running = True
        
        # Worker-Tasks erstellen
        for i in range(num_workers):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)
        
        logger.info(f"{num_workers} Queue-Worker gestartet")
    
    async def stop_workers(self, wait_for_completion: bool = True):
        """Stoppt alle Worker.
        
        Args:
            wait_for_completion: Wenn True, warten bis aktive Jobs fertig sind.
        """
        self._running = False
        
        if wait_for_completion and self._active_jobs > 0:
            logger.info(f"Warte auf {self._active_jobs} aktive Jobs...")
            # Warten bis Queue leer und alle Jobs fertig
            while self._active_jobs > 0:
                await asyncio.sleep(0.5)
        
        # Worker canceln
        for worker in self._workers:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
        
        self._workers.clear()
        logger.info("Alle Queue-Worker gestoppt")
    
    async def _worker_loop(self, worker_id: int):
        """Worker-Loop, der Jobs aus der Queue nimmt und verarbeitet."""
        logger.debug(f"Worker {worker_id} gestartet")
        
        while self._running:
            try:
                # Auf nächsten Job warten (mit Timeout für Shutdown-Check)
                try:
                    job = await asyncio.wait_for(
                        self._queue.get(), 
                        timeout=self.poll_interval
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Job verarbeiten mit Semaphore für Rate Limiting
                async with self._semaphore:
                    self._active_jobs += 1
                    try:
                        await self._process_job(job, worker_id)
                    finally:
                        self._active_jobs -= 1
                        self._queue.task_done()
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} Fehler: {e}")
        
        logger.debug(f"Worker {worker_id} beendet")
    
    async def _process_job(self, job: PrintJob, worker_id: int):
        """Verarbeitet einen einzelnen Job."""
        logger.info(f"Worker {worker_id}: Starte Job #{job.order_id} ({job.filename})")
        
        job.status = JobStatus.PROCESSING
        job.started_at = datetime.now()
        
        # DB-Status auf "processing" setzen
        await self._update_db_status(job.order_id, "processing")
        
        try:
            # Pipeline in Thread-Pool ausführen
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                functools.partial(
                    _run_pipeline_for_job,
                    job.order_id,
                    job.filename,
                    job.original_filepath,
                    job.operator,
                    job.enable_printing
                )
            )
            
            if result["success"]:
                job.status = JobStatus.COMPLETED
                job.result_message = result["message"]
                self._total_processed += 1
                logger.info(f"Worker {worker_id}: Job #{job.order_id} erfolgreich")
            else:
                job.status = JobStatus.ERROR
                job.error_message = result["message"]
                self._total_errors += 1
                logger.warning(f"Worker {worker_id}: Job #{job.order_id} fehlgeschlagen: {result['message']}")
                
        except Exception as e:
            job.status = JobStatus.ERROR
            job.error_message = str(e)
            self._total_errors += 1
            logger.error(f"Worker {worker_id}: Job #{job.order_id} Exception: {e}")
            await self._update_db_status(job.order_id, "error_unknown", str(e))
        
        job.completed_at = datetime.now()
        
        # Queue-Positionen aktualisieren
        self._update_queue_positions()
    
    async def _update_db_status(
        self, 
        order_id: int, 
        status: str, 
        error_message: str = None
    ):
        """Aktualisiert den Status in der Datenbank."""
        try:
            from sqlalchemy import select
            db = self._get_db()
            with db.SessionLocal() as session:
                stmt = select(OrderRecord).where(OrderRecord.order_id == order_id)
                rec = session.scalar(stmt)
                if rec:
                    rec.status = status
                    if error_message:
                        rec.error_message = error_message
                    if status == "processing":
                        rec.processed_at = None
                    session.commit()
        except Exception as e:
            logger.error(f"DB-Status Update Fehler für #{order_id}: {e}")
    
    def _get_db(self) -> DatabaseService:
        """Gibt eine DatabaseService-Instanz zurück."""
        db_path = settings.database_path
        if not db_path.is_absolute():
            db_path = settings.base_path / db_path
        return DatabaseService(db_path=db_path)
    
    def _update_queue_positions(self):
        """Aktualisiert die Queue-Positionen aller wartenden Jobs."""
        position = 1
        for job in self._jobs.values():
            if job.status == JobStatus.QUEUED:
                job.queue_position = position
                position += 1
            else:
                job.queue_position = 0
    
    async def add_job(
        self, 
        order_id: int, 
        filename: str, 
        original_filepath: str,
        operator: str,
        enable_printing: bool = False
    ) -> PrintJob:
        """Fügt einen neuen Job zur Queue hinzu.
        
        Returns:
            PrintJob mit Status und Queue-Position
        """
        # Prüfen ob Job bereits existiert
        if order_id in self._jobs:
            existing_job = self._jobs[order_id]
            if existing_job.status in (JobStatus.QUEUED, JobStatus.PROCESSING):
                logger.warning(f"Job #{order_id} ist bereits in der Queue")
                return existing_job
            # Alten abgeschlossenen Job entfernen
            del self._jobs[order_id]
        
        # Neuen Job erstellen
        job = PrintJob(
            order_id=order_id,
            filename=filename,
            original_filepath=original_filepath,
            operator=operator,
            enable_printing=enable_printing
        )
        
        # In Registry und Queue einfügen
        self._jobs[order_id] = job
        await self._queue.put(job)
        
        # Position aktualisieren
        self._update_queue_positions()
        
        # DB-Status auf "queued" setzen
        await self._update_db_status(order_id, "queued")
        
        logger.info(
            f"Job #{order_id} zur Queue hinzugefügt "
            f"(Position: {job.queue_position}, Wartende: {self.pending_count})"
        )
        
        return job
    
    async def add_jobs_batch(
        self, 
        orders: list[dict],
        operator: str,
        enable_printing: bool = False
    ) -> list[PrintJob]:
        """Fügt mehrere Jobs zur Queue hinzu.
        
        Args:
            orders: Liste von Dicts mit 'order_id', 'filename', 'original_filepath'
            operator: Benutzername des Operators
            enable_printing: Drucken aktivieren?
            
        Returns:
            Liste der erstellten PrintJobs
        """
        jobs = []
        for order in orders:
            job = await self.add_job(
                order_id=order["order_id"],
                filename=order["filename"],
                original_filepath=order["original_filepath"],
                operator=operator,
                enable_printing=enable_printing
            )
            jobs.append(job)
        return jobs
    
    def get_job(self, order_id: int) -> Optional[PrintJob]:
        """Gibt den Job für eine Order-ID zurück."""
        return self._jobs.get(order_id)
    
    def get_job_status(self, order_id: int) -> Optional[dict]:
        """Gibt Status-Informationen für einen Job zurück."""
        job = self._jobs.get(order_id)
        if not job:
            return None
        
        return {
            "order_id": job.order_id,
            "filename": job.filename,
            "status": job.status.value,
            "queue_position": job.queue_position if job.status == JobStatus.QUEUED else 0,
            "queued_at": job.queued_at.isoformat() if job.queued_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "result_message": job.result_message,
            "error_message": job.error_message,
        }
    
    @property
    def pending_count(self) -> int:
        """Anzahl wartender Jobs in der Queue."""
        return sum(1 for j in self._jobs.values() if j.status == JobStatus.QUEUED)
    
    @property
    def processing_count(self) -> int:
        """Anzahl aktuell verarbeiteter Jobs."""
        return self._active_jobs
    
    @property
    def queue_status(self) -> dict:
        """Gibt umfassenden Queue-Status zurück."""
        queued_jobs = [
            {"order_id": j.order_id, "filename": j.filename, "position": j.queue_position}
            for j in self._jobs.values() 
            if j.status == JobStatus.QUEUED
        ]
        processing_jobs = [
            {"order_id": j.order_id, "filename": j.filename}
            for j in self._jobs.values() 
            if j.status == JobStatus.PROCESSING
        ]
        
        return {
            "running": self._running,
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "active_workers": len(self._workers),
            "pending_count": self.pending_count,
            "processing_count": self.processing_count,
            "total_processed": self._total_processed,
            "total_errors": self._total_errors,
            "queued_jobs": queued_jobs,
            "processing_jobs": processing_jobs,
        }
    
    def cleanup_old_jobs(self, max_age_hours: int = 24):
        """Entfernt abgeschlossene Jobs älter als max_age_hours."""
        now = datetime.now()
        to_remove = []
        
        for order_id, job in self._jobs.items():
            if job.status in (JobStatus.COMPLETED, JobStatus.ERROR, JobStatus.CANCELLED):
                if job.completed_at:
                    age = (now - job.completed_at).total_seconds() / 3600
                    if age > max_age_hours:
                        to_remove.append(order_id)
        
        for order_id in to_remove:
            del self._jobs[order_id]
        
        if to_remove:
            logger.info(f"{len(to_remove)} alte Jobs aus Registry entfernt")


def _run_pipeline_for_job(
    order_id: int,
    filename: str,
    original_filepath: str,
    operator: str,
    enable_printing: bool
) -> dict:
    """
    Führt die Pipeline für einen Job aus (synchron, läuft im Thread-Pool).
    
    Diese Funktion ist eine Kopie der Pipeline-Logik aus api_routes.py,
    optimiert für die Queue-Verarbeitung.
    """
    from ..processing.pipeline import OrderPipeline
    from ..services.file_organizer import FileOrganizer
    from ..models import Order, OrderStatus
    from ..database.models import OrderRecord
    from sqlalchemy import select
    import os
    
    filepath = Path(original_filepath) if original_filepath else None
    
    if filepath is None or not filepath.exists():
        return {
            "success": False,
            "message": f"Quelldatei nicht gefunden: {filepath}",
        }
    
    # DB-Service
    db_path = settings.database_path
    if not db_path.is_absolute():
        db_path = settings.base_path / db_path
    db = DatabaseService(db_path=db_path)
    
    organizer = FileOrganizer()
    organizer.ensure_directory_structure()
    pipeline = OrderPipeline(db_service=db, file_organizer=organizer)
    
    # Order-Objekt erstellen
    order = Order(
        order_id=order_id,
        filename=filename,
        filepath=filepath,
        file_size_bytes=filepath.stat().st_size,
        operator=operator or os.getenv("USER", os.getenv("USERNAME", "dashboard")),
    )
    
    # Pipeline ausführen
    work_dir = Path(tempfile.mkdtemp(prefix="skriptendruck_queue_"))
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
        
        # Billing-Record
        if order.status == OrderStatus.PROCESSED and order.user and order.price_calculation:
            try:
                db.create_billing_record(order)
            except Exception as exc:
                logger.warning(f"Billing-Record Fehler: {exc}")
        
        # Drucken
        printed = False
        should_print = enable_printing if enable_printing is not None else settings.enable_printing
        if order.status == OrderStatus.PROCESSED and should_print:
            try:
                from ..services.printing_service import PrintingService
                printer = PrintingService()
                printed = printer.print_order(order)
                if printed:
                    logger.info(f"Druckauftrag für #{order_id} gesendet")
            except Exception as exc:
                logger.warning(f"Druck-Fehler für #{order_id}: {exc}")
        
        if order.is_error:
            return {"success": False, "message": f"Verarbeitung fehlgeschlagen: {order.error_message}"}
        
        msg = f"Auftrag #{order_id} erfolgreich ({order.page_count} Seiten)"
        if printed:
            msg += " – gedruckt"
        
        return {"success": True, "message": msg}
        
    except Exception as exc:
        logger.error(f"Pipeline-Fehler für #{order_id}: {exc}")
        # Status auf Fehler setzen
        try:
            with db.SessionLocal() as session:
                stmt = select(OrderRecord).where(OrderRecord.order_id == order_id)
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
        shutil.rmtree(str(work_dir), ignore_errors=True)


# Globale Queue-Instanz
job_queue = JobQueue()
