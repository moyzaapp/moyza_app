# 🧪 Guía de Testing del Scheduler

## 📋 Tabla de Contenidos
1. [Tests Unitarios (test_scheduler.py)](#tests-unitarios)
2. [Tests de Integración (test_multi_worker.sh)](#tests-de-integración)
3. [Ejemplos Prácticos](#ejemplos-prácticos)

---

## 1️⃣ Tests Unitarios (test_scheduler.py)

### ¿Qué es?
Tests automatizados con **pytest** que verifican la lógica del scheduler de manera aislada, sin necesidad de correr toda la aplicación.

### ¿Para qué sirve?
- ✅ Verificar que la lógica de `check_automatic_reports()` funciona correctamente
- ✅ Probar casos edge (sin propiedades, con errores, etc.)
- ✅ Testing rápido durante desarrollo
- ✅ CI/CD (integración continua)

### Cómo ejecutar:

```bash
cd /home/jnausa/projects/moyza_app/backend

# Opción 1: Ejecutar todos los tests
./run_tests.sh

# Opción 2: Solo tests del scheduler
./run_tests.sh scheduler

# Opción 3: Con reporte de cobertura
./run_tests.sh coverage

# Opción 4: Modo watch (re-ejecuta al cambiar archivos)
./run_tests.sh watch

# Opción 5: Pytest directamente (más control)
pytest tests/test_scheduler.py -v
pytest tests/test_scheduler.py::test_check_automatic_reports_sin_propiedades -v
```

### Salida esperada:

```
🧪 Ejecutando tests unitarios...
================================

collected 4 items

tests/test_scheduler.py::test_check_automatic_reports_sin_propiedades PASSED    [ 25%]
tests/test_scheduler.py::test_check_automatic_reports_con_propiedad_activa PASSED [ 50%]
tests/test_scheduler.py::test_check_automatic_reports_con_propiedad_inactiva PASSED [ 75%]
tests/test_scheduler.py::test_check_automatic_reports_maneja_errores PASSED   [100%]

============================== 4 passed in 0.23s ==============================
✅ Tests completados
```

### Estructura del test:

```python
def test_nombre_del_test(mock_db_session):
    """Descripción de qué verifica este test."""
    # 1. Setup - Preparar datos de prueba
    mock_db = Mock()
    mock_property = Mock()
    mock_property.id = 1
    # ...

    # 2. Execute - Ejecutar la función a probar
    check_automatic_reports()

    # 3. Verify - Verificar que funcionó correctamente
    mock_db.query.assert_called_once()
    mock_db.close.assert_called_once()
```

### Añadir nuevos tests:

```python
# En tests/test_scheduler.py

def test_mi_nuevo_caso(mock_db_session):
    """Verifica [descripción del caso]."""
    # Setup
    mock_db = Mock()
    mock_db_session.return_value = mock_db
    # ... configurar mocks

    # Execute
    check_automatic_reports()

    # Verify
    assert algo == esperado
```

---

## 2️⃣ Tests de Integración (test_multi_worker.sh)

### ¿Qué es?
Script Bash que **inicia Gunicorn real** con múltiples workers y verifica que solo uno ejecuta el scheduler.

### ¿Para qué sirve?
- ✅ Verificar comportamiento en producción (multi-worker)
- ✅ Testing manual visual
- ✅ Debugging de problemas de configuración
- ✅ Demostración del funcionamiento

### Cómo ejecutar:

```bash
cd /home/jnausa/projects/moyza_app/backend

# Ejecutar el test
./test_multi_worker.sh
```

### Salida esperada:

```
🧪 Probando scheduler con multi-worker...
========================================

▶️  Iniciando Gunicorn con 4 workers...
⏳ Esperando inicio de workers...
✓ Workers de Gunicorn activos: 4

📋 Verificando logs del scheduler...
======================================

✅ Scheduler iniciado: 1 veces (debería ser 1)
❌ Scheduler deshabilitado: 3 veces (debería ser 3)

✅ CORRECTO: Solo un worker inició el scheduler

📄 Extracto de logs relevantes:
================================
Worker 0: Worker maestro: Iniciando scheduler
Worker 0: Scheduler iniciado correctamente en worker maestro
Worker 1: Scheduler deshabilitado (solo corre en worker maestro)
Worker 2: Scheduler deshabilitado (solo corre en worker maestro)
Worker 3: Scheduler deshabilitado (solo corre en worker maestro)

🌐 Verificando endpoints de health...

1️⃣  GET /api/v1/health
{
    "status": "healthy",
    "worker_id": "0",
    "scheduler_running": true
}

2️⃣  GET /api/v1/health/scheduler
{
    "status": "running",
    "worker_id": "0",
    "is_master": true,
    "jobs": [
        {
            "id": "check_automatic_reports",
            "name": "check_automatic_reports",
            "next_run_time": "2026-06-08 17:00:00",
            "trigger": "interval[0:00:54]"
        }
    ],
    "total_jobs": 1
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 Comandos útiles:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  📄 Ver logs en tiempo real:
     tail -f gunicorn.log

  🔍 Buscar logs del scheduler:
     grep -i scheduler gunicorn.log

  🔄 Ver workers activos:
     ps aux | grep gunicorn

  🛑 Detener Gunicorn:
     kill $(cat gunicorn.pid)
     # o simplemente:
     ./stop_multi_worker.sh

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Test completado.
```

### Para detener Gunicorn:

```bash
# Opción 1: Script dedicado
./stop_multi_worker.sh

# Opción 2: Manual
kill $(cat gunicorn.pid)

# Opción 3: Forzar si no responde
pkill -9 gunicorn
```

---

## 3️⃣ Ejemplos Prácticos

### Ejemplo 1: Desarrollo (cambié código, quiero verificar)

```bash
# 1. Ejecutar tests unitarios rápidos
./run_tests.sh scheduler

# 2. Si pasan, probar con servidor real
./test_multi_worker.sh

# 3. Ver logs en tiempo real mientras funciona
tail -f gunicorn.log | grep -i scheduler

# 4. Cuando termines, detener
./stop_multi_worker.sh
```

### Ejemplo 2: Debugging (algo no funciona)

```bash
# 1. Iniciar con logging DEBUG
./test_multi_worker.sh

# 2. Ver todos los logs
cat gunicorn.log

# 3. Filtrar logs del scheduler
grep -i scheduler gunicorn.log

# 4. Ver qué worker está ejecutando qué
grep -i "worker\|scheduler" gunicorn.log

# 5. Verificar estado via API
curl http://localhost:8000/api/v1/health/scheduler | python3 -m json.tool

# 6. Ver procesos activos
ps aux | grep gunicorn
```

### Ejemplo 3: CI/CD (GitHub Actions, GitLab CI)

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements.txt
          pip install pytest pytest-cov

      - name: Run tests
        run: |
          cd backend
          ./run_tests.sh coverage

      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

### Ejemplo 4: Docker (testing en contenedor)

```bash
# En docker-compose.yml
services:
  backend-test:
    build: ./backend
    command: ./run_tests.sh
    volumes:
      - ./backend:/app

# Ejecutar
docker-compose run backend-test
```

---

## 🔍 Verificación Manual (sin scripts)

### Opción 1: Con Uvicorn (desarrollo)

```bash
# Iniciar (solo 1 worker, siempre activa scheduler)
uvicorn app.main:app --reload

# Ver logs en consola
# Deberías ver: "Worker maestro: Iniciando scheduler"

# Verificar endpoint
curl http://localhost:8000/api/v1/health/scheduler
```

### Opción 2: Con Gunicorn (producción)

```bash
# Iniciar con 4 workers
gunicorn -c gunicorn.conf.py app.main:app --log-level debug

# En otra terminal, verificar workers
ps aux | grep gunicorn

# Verificar que solo uno tiene scheduler activo
# Hacer requests y ver logs
curl http://localhost:8000/api/v1/health/scheduler
```

### Opción 3: Con Docker

```bash
# Build
docker build -t moyza-backend ./backend

# Run con logging
docker run -p 8000:8000 moyza-backend

# Ver logs
docker logs -f <container_id>

# Verificar scheduler
docker exec <container_id> curl http://localhost:8000/api/v1/health/scheduler
```

---

## 📊 Interpretación de Resultados

### ✅ Resultado CORRECTO

```
✅ Scheduler iniciado: 1 veces
❌ Scheduler deshabilitado: 3 veces (con 4 workers)
```

**Significado:** Solo el worker maestro (ID=0) ejecuta el scheduler. Los demás workers solo procesan requests HTTP.

### ❌ Resultado INCORRECTO

```
⚠️  Scheduler iniciado: 4 veces
❌ Scheduler deshabilitado: 0 veces
```

**Problema:** Todos los workers están iniciando el scheduler → jobs se ejecutan múltiples veces.

**Solución:**
1. Verificar que `gunicorn.conf.py` tiene el hook `post_fork()`
2. Verificar que `scheduler.py` está checando `WORKER_ID`
3. Revisar logs: `grep WORKER_ID gunicorn.log`

---

## 🛠️ Troubleshooting

### Problema: pytest no se encuentra

```bash
pip install pytest pytest-cov
```

### Problema: El script .sh no se ejecuta

```bash
# Dar permisos
chmod +x test_multi_worker.sh
chmod +x run_tests.sh
chmod +x stop_multi_worker.sh

# Ejecutar
./test_multi_worker.sh
```

### Problema: Gunicorn no se detiene

```bash
# Forzar detención
pkill -9 gunicorn

# Limpiar PID file
rm -f gunicorn.pid
```

### Problema: Puerto 8000 en uso

```bash
# Ver qué proceso usa el puerto
lsof -i :8000

# Matar proceso
kill -9 <PID>

# O cambiar puerto en gunicorn.conf.py
bind = "0.0.0.0:8001"
```

---

## 📚 Recursos Adicionales

- **Pytest docs:** https://docs.pytest.org/
- **APScheduler docs:** https://apscheduler.readthedocs.io/
- **Gunicorn docs:** https://docs.gunicorn.org/
- **README del scheduler:** [app/jobs/README.md](app/jobs/README.md)
- **Opciones avanzadas:** [SCHEDULER_OPTIONS.md](SCHEDULER_OPTIONS.md)
