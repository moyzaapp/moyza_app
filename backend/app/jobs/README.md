# Sistema de Tareas Programadas (Scheduler)

## 📋 Descripción

Sistema de tareas programadas usando APScheduler para ejecutar jobs recurrentes como la generación automática de informes.

## 🏗️ Arquitectura

### Componente Principal
- **scheduler.py**: Configuración del scheduler con APScheduler
- **Estrategia Multi-Worker**: Solo el worker maestro ejecuta el scheduler

### Problema resuelto
En producción con Gunicorn multi-worker, sin control cada worker iniciaría su propio scheduler, causando ejecuciones duplicadas de los jobs.

## ✅ Solución Implementada

### Control por Variable de Entorno

```python
# Solo el worker con WORKER_ID=0 ejecuta el scheduler
worker_id = os.getenv("WORKER_ID", "0")
if worker_id == "0":
    scheduler.start()
```

### Configuración de Gunicorn

```python
# gunicorn.conf.py
def post_fork(server, worker):
    """Asigna ID único a cada worker."""
    os.environ["WORKER_ID"] = str(worker.age)
```

## 📊 Monitoreo

### Endpoints de Health Check

```bash
# Health check básico
curl http://localhost:8000/api/v1/health

# Estado detallado del scheduler
curl http://localhost:8000/api/v1/health/scheduler
```

**Respuesta esperada:**

```json
{
  "status": "running",
  "worker_id": "0",
  "is_master": true,
  "jobs": [
    {
      "id": "check_automatic_reports",
      "name": "check_automatic_reports",
      "next_run_time": "2026-06-08 14:00:00",
      "trigger": "interval[1:00:00]"
    }
  ],
  "total_jobs": 1
}
```

### Logs

```bash
# Ver logs del scheduler
docker logs backend_container | grep -i scheduler

# Deberías ver:
# Worker maestro: Iniciando scheduler
# Scheduler iniciado correctamente en worker maestro
# Worker 1: Scheduler deshabilitado (solo corre en worker maestro)
# Worker 2: Scheduler deshabilitado (solo corre en worker maestro)
# ...
```

## 🔄 Jobs Configurados

### check_automatic_reports

**Frecuencia:** Cada hora  
**Función:** Revisa propiedades con `auto_send_report=True` y genera informes según configuración

**Condiciones para ejecutar:**
- `property.auto_send_report == True`
- `property.status == "ACTIVA"`
- `property.report_frequency == "MONTHLY"`
- `property.report_day == current_day`
- `property.report_hour == current_hour`

## 🚀 Uso en Desarrollo

### Con Uvicorn (sin Gunicorn)
```bash
uvicorn app.main:app --reload
# El scheduler se inicia automáticamente
```

### Con Gunicorn
```bash
gunicorn -c gunicorn.conf.py app.main:app
# Solo el worker 0 ejecuta el scheduler
```

## 🐳 Uso en Docker

### Dockerfile
```dockerfile
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app"]
```

### Docker Compose (desarrollo)
```yaml
services:
  backend:
    build: ./backend
    command: uvicorn app.main:app --host 0.0.0.0 --reload
    # Scheduler se inicia automáticamente
```

### Docker Compose (producción)
```yaml
services:
  backend:
    build: ./backend
    command: gunicorn -c gunicorn.conf.py app.main:app
    # Solo worker 0 ejecuta scheduler
```

## 🧪 Testing

### Test Manual
```bash
# Ejecutar script de prueba
./test_multi_worker.sh
```

### Test Unitario
```bash
pytest tests/test_scheduler.py -v
```

### Verificar Worker Maestro
```bash
# Ver cuál worker está ejecutando el scheduler
ps aux | grep gunicorn
docker exec backend_container ps aux | grep gunicorn
```

## 📝 Añadir Nuevos Jobs

```python
# En scheduler.py - función start_scheduler()

scheduler.add_job(
    mi_nueva_funcion,
    "cron",
    hour=8,
    minute=0,
    id="mi_job_diario",
    replace_existing=True
)
```

**Tipos de triggers:**
- `interval`: Ejecutar cada X tiempo (hours, minutes, seconds)
- `cron`: Ejecutar en horarios específicos (estilo crontab)
- `date`: Ejecutar una vez en una fecha específica

## 🔧 Troubleshooting

### El job se ejecuta múltiples veces
- Verificar que `WORKER_ID` se está seteando correctamente
- Revisar logs: `docker logs backend | grep "Scheduler"`
- Confirmar que solo un worker muestra "Scheduler iniciado"

### El job no se ejecuta
- Verificar estado: `curl http://localhost:8000/api/v1/health/scheduler`
- Revisar logs: `docker logs backend | grep "check_automatic_reports"`
- Confirmar que el scheduler está running

### El scheduler no inicia
- Verificar que APScheduler está instalado: `pip list | grep apscheduler`
- Revisar logs de startup de la aplicación
- Confirmar que no hay errores de importación

## 📚 Referencias

- [APScheduler Documentation](https://apscheduler.readthedocs.io/)
- [Gunicorn Workers](https://docs.gunicorn.org/en/stable/design.html#async-workers)
- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)

## 🔄 Alternativas

Para necesidades más complejas, ver [SCHEDULER_OPTIONS.md](../../SCHEDULER_OPTIONS.md):
- **Opción 2**: Proceso separado con Docker Compose
- **Opción 3**: Celery Beat (enterprise)
