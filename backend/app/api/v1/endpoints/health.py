"""
Endpoints de health check y diagnóstico del sistema.
"""
import os
from fastapi import APIRouter
from app.jobs.scheduler import scheduler

router = APIRouter()


@router.get("/")
def health_check():
    """Health check básico."""
    return {
        "status": "healthy",
        "worker_id": os.getenv("WORKER_ID", "unknown"),
        "scheduler_running": scheduler.running if scheduler else False
    }


@router.get("/scheduler")
def scheduler_status():
    """Estado detallado del scheduler."""
    worker_id = os.getenv("WORKER_ID", "unknown")

    if not scheduler:
        return {
            "status": "not_initialized",
            "worker_id": worker_id,
            "is_master": worker_id == "0"
        }

    jobs = []
    if scheduler.running:
        for job in scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger)
            })

    return {
        "status": "running" if scheduler.running else "stopped",
        "worker_id": worker_id,
        "is_master": worker_id == "0",
        "jobs": jobs,
        "total_jobs": len(jobs)
    }
