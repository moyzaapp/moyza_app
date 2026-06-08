# 🚀 Quick Start - Testing del Scheduler

## 📦 Resumen de archivos

```
backend/
├── test_multi_worker.sh      ← Script para probar multi-worker
├── stop_multi_worker.sh       ← Script para detener Gunicorn
├── run_tests.sh               ← Script para ejecutar tests unitarios
├── tests/
│   └── test_scheduler.py      ← Tests unitarios con pytest
├── app/jobs/
│   ├── scheduler.py           ← Lógica del scheduler
│   └── README.md              ← Documentación del scheduler
├── TESTING_GUIDE.md           ← Guía completa de testing
└── SCHEDULER_OPTIONS.md       ← Alternativas avanzadas
```

---

## 🎯 Dos tipos de tests

| Tipo | Archivo | Qué hace | Cuándo usar |
|------|---------|----------|-------------|
| **Unitario** | `test_scheduler.py` | Prueba la lógica aislada con mocks | Durante desarrollo, CI/CD |
| **Integración** | `test_multi_worker.sh` | Prueba con Gunicorn real | Antes de deploy, debugging |

---

## ⚡ Comandos Rápidos

### 1️⃣ Tests Unitarios (Rápido - 1 segundo)

```bash
cd backend

# Ejecutar todos los tests
./run_tests.sh

# Solo scheduler
./run_tests.sh scheduler

# Con cobertura de código
./run_tests.sh coverage
```

**Salida esperada:**
```
✅ 4 passed in 0.23s
```

---

### 2️⃣ Test Multi-Worker (Completo - 10 segundos)

```bash
cd backend

# Iniciar test
./test_multi_worker.sh

# Espera a que termine y verás:
✅ Scheduler iniciado: 1 veces
❌ Scheduler deshabilitado: 3 veces
✅ CORRECTO: Solo un worker inició el scheduler

# Ver logs en tiempo real (opcional)
tail -f gunicorn.log

# Cuando termines, detener
./stop_multi_worker.sh
```

---

## 🔍 Ejemplo Completo Paso a Paso

### Escenario: "Acabé de modificar el scheduler, ¿funciona?"

```bash
# 1. Ir al directorio backend
cd /home/jnausa/projects/moyza_app/backend

# 2. Ejecutar tests unitarios (rápido)
./run_tests.sh scheduler

# 3. Si pasa, probar con servidor real
./test_multi_worker.sh

# 4. Verificar endpoint de health
curl http://localhost:8000/api/v1/health/scheduler | python3 -m json.tool

# 5. Ver logs del scheduler
grep -i scheduler gunicorn.log

# 6. Limpiar
./stop_multi_worker.sh
```

**Salida paso a paso:**

```bash
# Paso 2 - Tests unitarios
🧪 Ejecutando solo tests del scheduler...
================================
tests/test_scheduler.py::test_check_automatic_reports_sin_propiedades PASSED
tests/test_scheduler.py::test_check_automatic_reports_con_propiedad_activa PASSED
tests/test_scheduler.py::test_check_automatic_reports_con_propiedad_inactiva PASSED
tests/test_scheduler.py::test_check_automatic_reports_maneja_errores PASSED
✅ Tests completados

# Paso 3 - Test multi-worker
🧪 Probando scheduler con multi-worker...
▶️  Iniciando Gunicorn con 4 workers...
✓ Workers de Gunicorn activos: 4
✅ Scheduler iniciado: 1 veces (debería ser 1)
❌ Scheduler deshabilitado: 3 veces (debería ser 3)
✅ CORRECTO: Solo un worker inició el scheduler

# Paso 4 - Health check
{
  "status": "running",
  "worker_id": "0",
  "is_master": true,
  "jobs": [
    {
      "id": "check_automatic_reports",
      "next_run_time": "2026-06-08 17:00:00"
    }
  ]
}

# Paso 5 - Logs
[2026-06-08 16:05:23] Worker maestro: Iniciando scheduler
[2026-06-08 16:05:23] Scheduler iniciado correctamente en worker maestro
[2026-06-08 16:05:23] Worker 1: Scheduler deshabilitado
[2026-06-08 16:05:23] Worker 2: Scheduler deshabilitado
[2026-06-08 16:05:23] Worker 3: Scheduler deshabilitado

# Paso 6 - Detener
🛑 Deteniendo Gunicorn...
   PID encontrado: 12345
✅ Gunicorn detenido correctamente
```

---

## 📖 Explicación de test_scheduler.py

### ¿Qué hace?

Prueba la función `check_automatic_reports()` que:
1. Lee propiedades de la BD
2. Filtra las que tienen `auto_send_report=True`
3. Si coincide día y hora, genera informe

### Tests incluidos:

```python
✅ test_check_automatic_reports_sin_propiedades
   → Verifica que funciona cuando no hay propiedades

✅ test_check_automatic_reports_con_propiedad_activa
   → Verifica que procesa propiedad que coincide hora/día

✅ test_check_automatic_reports_con_propiedad_inactiva
   → Verifica que ignora propiedades con hora diferente

✅ test_check_automatic_reports_maneja_errores
   → Verifica que errores no rompen la aplicación
```

### Cómo funciona:

```python
def test_check_automatic_reports_sin_propiedades(mock_db_session):
    # 1. SETUP: Preparar mock de BD sin propiedades
    mock_db = Mock()
    mock_db.query.return_value.filter.return_value.all.return_value = []

    # 2. EXECUTE: Ejecutar función
    check_automatic_reports()

    # 3. VERIFY: Verificar que se llamó correctamente
    mock_db.query.assert_called_once()  # ✅ Consultó BD
    mock_db.close.assert_called_once()  # ✅ Cerró conexión
```

**Mock = Simulación:** No usa BD real, usa objetos falsos para testing rápido.

---

## 📖 Explicación de test_multi_worker.sh

### ¿Qué hace?

1. ✅ Inicia Gunicorn con 4 workers
2. ✅ Espera que inicien
3. ✅ Revisa logs para contar cuántos iniciaron scheduler
4. ✅ Verifica que solo sea 1
5. ✅ Hace request a endpoints de health
6. ✅ Muestra resumen

### Líneas clave del script:

```bash
# Iniciar Gunicorn con 4 workers
gunicorn -c gunicorn.conf.py app.main:app --daemon --pid gunicorn.pid

# Contar cuántos iniciaron scheduler
SCHEDULER_INIT=$(grep -i "scheduler iniciado" gunicorn.log | wc -l)

# Verificar que sea 1
if [ "$SCHEDULER_INIT" -eq 1 ]; then
    echo "✅ CORRECTO"
else
    echo "⚠️  ADVERTENCIA"
fi
```

---

## ❓ FAQ

### P: ¿Tengo que ejecutar ambos tests?

**R:** Depende:
- **Durante desarrollo:** Solo tests unitarios (`./run_tests.sh`)
- **Antes de deploy:** Ambos para estar seguro
- **Debugging problema:** Test multi-worker para ver logs

### P: ¿Cómo sé si funcionó correctamente?

**R:** Tests unitarios:
```
✅ 4 passed
```

Test multi-worker:
```
✅ Scheduler iniciado: 1 veces
```

### P: ¿Qué hago si falla un test?

**R:** 
1. Lee el mensaje de error
2. Ve el archivo que falló (`test_scheduler.py:42`)
3. Ejecuta solo ese test: `pytest tests/test_scheduler.py::nombre_del_test -v`
4. Revisa logs: `grep -i error gunicorn.log`

### P: ¿Necesito instalar algo?

**R:** 
```bash
# Para tests unitarios
pip install pytest pytest-cov

# Ya está en requirements.txt:
- apscheduler
```

### P: ¿Cómo ejecuto los scripts .sh?

**R:**
```bash
# 1. Dar permisos (solo primera vez)
chmod +x test_multi_worker.sh
chmod +x run_tests.sh
chmod +x stop_multi_worker.sh

# 2. Ejecutar
./test_multi_worker.sh

# Si da error "Permission denied":
bash test_multi_worker.sh
```

### P: ¿Cómo veo logs en tiempo real?

**R:**
```bash
# Después de ejecutar ./test_multi_worker.sh

# En otra terminal:
tail -f gunicorn.log

# O filtrar solo scheduler:
tail -f gunicorn.log | grep -i scheduler

# Para salir: Ctrl+C
```

---

## 🎓 Próximos pasos

1. ✅ Lee esta guía
2. ✅ Ejecuta `./run_tests.sh` para ver tests unitarios
3. ✅ Ejecuta `./test_multi_worker.sh` para ver test multi-worker
4. ✅ Lee [TESTING_GUIDE.md](TESTING_GUIDE.md) para más detalles
5. ✅ Lee [app/jobs/README.md](app/jobs/README.md) para arquitectura

---

## 💡 Comandos más usados

```bash
# Testing rápido
./run_tests.sh scheduler

# Testing completo
./test_multi_worker.sh

# Ver logs
grep -i scheduler gunicorn.log

# Health check
curl http://localhost:8000/api/v1/health/scheduler

# Detener Gunicorn
./stop_multi_worker.sh

# Ver procesos
ps aux | grep gunicorn
```

---

**¿Dudas?** Lee [TESTING_GUIDE.md](TESTING_GUIDE.md) para ejemplos más detallados.
