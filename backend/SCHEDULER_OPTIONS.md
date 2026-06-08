# Opciones para ejecutar Scheduler con Gunicorn Multi-Worker

## Problema
Con múltiples workers de Gunicorn, cada worker inicia su propio scheduler, causando que los jobs se ejecuten N veces (una por worker).

## ✅ Opción 1: Variable de entorno (IMPLEMENTADA)

**Pros:**
- Simple y directo
- No requiere dependencias adicionales
- Funciona en desarrollo y producción

**Cómo funciona:**
- Gunicorn asigna un WORKER_ID a cada worker en el hook `post_fork`
- Solo el worker con ID=0 inicia el scheduler
- Los demás workers solo procesan requests HTTP

**Configuración:**
```python
# gunicorn.conf.py
def post_fork(server, worker):
    os.environ["WORKER_ID"] = str(worker.age)
```

---

## Opción 2: Proceso separado con Docker Compose

**Pros:**
- Separación de responsabilidades clara
- Mejor escalabilidad
- Fácil monitoreo independiente

**Contras:**
- Requiere Docker Compose o K8s
- Más complejo de configurar

**Implementación:**

### docker-compose.yml
```yaml
services:
  api:
    build: ./backend
    command: gunicorn -c gunicorn.conf.py app.main:app
    ports:
      - "8000:8000"
    environment:
      - ENABLE_SCHEDULER=false  # Deshabilitado en API

  scheduler:
    build: ./backend
    command: python -m app.jobs.run_scheduler  # Script separado
    environment:
      - ENABLE_SCHEDULER=true
    depends_on:
      - api
```

### app/jobs/run_scheduler.py
```python
"""
Script independiente para ejecutar el scheduler.
Uso: python -m app.jobs.run_scheduler
"""
import time
import logging
from app.core.logging_config import setup_logging
from app.jobs.scheduler import scheduler, check_automatic_reports

setup_logging()
logger = logging.getLogger(__name__)

def main():
    logger.info("Iniciando scheduler en proceso dedicado")
    
    scheduler.add_job(
        check_automatic_reports,
        "interval",
        hours=1,
        id="check_automatic_reports"
    )
    
    scheduler.start()
    
    try:
        # Mantener el proceso vivo
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Deteniendo scheduler...")
        scheduler.shutdown()

if __name__ == "__main__":
    main()
```

---

## Opción 3: Celery Beat (PRODUCCIÓN ENTERPRISE)

**Pros:**
- Solución robusta y battle-tested
- Sistema distribuido con locks
- Monitoreo avanzado (Flower)
- Retry automático
- Persistencia de estado

**Contras:**
- Requiere Redis o RabbitMQ
- Más complejo de configurar
- Mayor overhead

**Implementación:**

### requirements.txt
```
celery[redis]
```

### app/jobs/celery_app.py
```python
from celery import Celery
from celery.schedules import crontab

celery_app = Celery(
    "moyza",
    broker="redis://redis:6379/0",
    backend="redis://redis:6379/0"
)

celery_app.conf.beat_schedule = {
    'check-automatic-reports': {
        'task': 'app.jobs.tasks.check_automatic_reports_task',
        'schedule': crontab(minute='0'),  # Cada hora en punto
    },
}
```

### app/jobs/tasks.py
```python
from app.jobs.celery_app import celery_app
from app.jobs.scheduler import check_automatic_reports

@celery_app.task
def check_automatic_reports_task():
    return check_automatic_reports()
```

### docker-compose.yml
```yaml
services:
  redis:
    image: redis:alpine
    
  api:
    build: ./backend
    command: gunicorn -c gunicorn.conf.py app.main:app
    depends_on:
      - redis
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0

  celery-worker:
    build: ./backend
    command: celery -A app.jobs.celery_app worker --loglevel=info
    depends_on:
      - redis

  celery-beat:
    build: ./backend
    command: celery -A app.jobs.celery_app beat --loglevel=info
    depends_on:
      - redis
```

---

## Recomendación por escenario

| Escenario | Opción recomendada | Razón |
|-----------|-------------------|-------|
| Startup / MVP | **Opción 1** | Simple, sin dependencias extra |
| Producción pequeña/mediana | **Opción 2** | Balance entre simplicidad y separación |
| Producción enterprise | **Opción 3** | Robustez, monitoreo, escalabilidad |
| Desarrollo local | **Opción 1** | Menos complejidad |

---

## Testing de la implementación actual

```bash
# Ver que solo un worker ejecuta el scheduler
docker logs backend_container | grep "Scheduler"

# Deberías ver:
# Worker 0: Iniciando scheduler
# Worker 1: Scheduler deshabilitado
# Worker 2: Scheduler deshabilitado
# Worker 3: Scheduler deshabilitado
```
