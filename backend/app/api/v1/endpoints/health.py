"""
Endpoints de health check y diagnóstico del sistema.
"""
import os
import json
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter
from app.jobs.scheduler import scheduler

router = APIRouter()

# Archivo compartido para estado de workers
WORKER_STATE_FILE = Path("/tmp/moyza_workers_state.json")


def update_worker_state():
    """Actualiza el estado de este worker en el archivo compartido."""
    worker_id = os.getenv("WORKER_ID", "unknown")

    try:
        # Usar file locking para evitar race conditions
        import fcntl

        # Abrir con lock exclusivo
        with open(WORKER_STATE_FILE, 'a+') as f:
            # Obtener lock exclusivo
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

            try:
                f.seek(0)
                content = f.read()
                workers_state = json.loads(content) if content else {}
            except (json.JSONDecodeError, ValueError):
                workers_state = {}

            # Actualizar este worker
            workers_state[worker_id] = {
                "worker_id": worker_id,
                "scheduler_running": scheduler.running if scheduler else False,
                "is_master": worker_id == "0",
                "last_seen": datetime.now().isoformat(),
                "pid": os.getpid()
            }

            # Guardar estado actualizado
            f.seek(0)
            f.truncate()
            json.dump(workers_state, f, indent=2)

            # Lock se libera automáticamente al cerrar

        return workers_state
    except Exception as e:
        return {"error": str(e)}


@router.get("/")
def health_check():
    """Health check básico con estado de este worker."""
    return {
        "status": "healthy",
        "worker_id": os.getenv("WORKER_ID", "unknown"),
        "scheduler_running": scheduler.running if scheduler else False
    }


@router.get("/workers")
def workers_status():
    """Estado de todos los workers."""
    workers_state = update_worker_state()

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "workers": workers_state,
        "total_workers": len(workers_state) if isinstance(workers_state, dict) and "error" not in workers_state else 0
    }


@router.get("/scheduler")
def scheduler_status():
    """Estado detallado del scheduler y todos los workers."""
    worker_id = os.getenv("WORKER_ID", "unknown")

    # Actualizar estado de este worker
    workers_state = update_worker_state()

    if not scheduler:
        return {
            "status": "not_initialized",
            "worker_id": worker_id,
            "is_master": worker_id == "0",
            "all_workers": workers_state
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
        "current_worker_id": worker_id,
        "is_master": worker_id == "0",
        "jobs": jobs,
        "total_jobs": len(jobs),
        "all_workers": workers_state,
        "total_workers": len(workers_state) if isinstance(workers_state, dict) and "error" not in workers_state else 0
    }
