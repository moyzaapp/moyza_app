#!/bin/bash
# Script para probar que el scheduler solo se inicia en un worker

set -e  # Detener si hay error

echo "🧪 Probando scheduler con multi-worker..."
echo "========================================"
echo ""

# Verificar si ya hay una instancia corriendo
if [ -f gunicorn.pid ]; then
    echo "⚠️  Gunicorn ya está corriendo. Deteniendo..."
    kill $(cat gunicorn.pid) 2>/dev/null || true
    sleep 2
    rm -f gunicorn.pid
fi

# Limpiar logs anteriores
rm -f gunicorn.log

# Iniciar Gunicorn con 4 workers y logging
echo "▶️  Iniciando Gunicorn con 4 workers..."
gunicorn -c gunicorn.conf.py app.main:app \
    --daemon \
    --pid gunicorn.pid \
    --log-file gunicorn.log \
    --log-level debug \
    --capture-output

# Esperar a que inicie
echo "⏳ Esperando inicio de workers..."
sleep 5

# Verificar que está corriendo
if [ ! -f gunicorn.pid ]; then
    echo "❌ Error: Gunicorn no inició correctamente"
    echo "Revisa gunicorn.log para más detalles"
    exit 1
fi

# Contar workers activos
WORKER_COUNT=$(ps aux | grep "[g]unicorn.*worker" | wc -l)
echo "✓ Workers de Gunicorn activos: $WORKER_COUNT"

# Verificar logs del scheduler
echo ""
echo "📋 Verificando logs del scheduler..."
echo "======================================"
echo ""

# Buscar menciones del scheduler en logs
SCHEDULER_INIT=$(grep -i "scheduler iniciado" gunicorn.log | wc -l)
SCHEDULER_DISABLED=$(grep -i "scheduler deshabilitado" gunicorn.log | wc -l)

echo "✅ Scheduler iniciado: $SCHEDULER_INIT veces (debería ser 1)"
echo "❌ Scheduler deshabilitado: $SCHEDULER_DISABLED veces (debería ser $(($WORKER_COUNT - 1)))"
echo ""

if [ "$SCHEDULER_INIT" -eq 1 ]; then
    echo "✅ CORRECTO: Solo un worker inició el scheduler"
else
    echo "⚠️  ADVERTENCIA: El scheduler se inició $SCHEDULER_INIT veces (esperado: 1)"
fi

# Mostrar extracto de logs relevantes
echo ""
echo "📄 Extracto de logs relevantes:"
echo "================================"
grep -i "scheduler\|worker" gunicorn.log | tail -10 || echo "(No se encontraron logs del scheduler)"

# Hacer request a health check
echo ""
echo "🌐 Verificando endpoints de health..."
sleep 1

# Health check básico
echo ""
echo "1️⃣  GET /api/v1/health"
curl -s http://localhost:8000/api/v1/health | python3 -m json.tool || echo "❌ Endpoint no respondió"

# Health check del scheduler
echo ""
echo "2️⃣  GET /api/v1/health/scheduler"
curl -s http://localhost:8000/api/v1/health/scheduler | python3 -m json.tool || echo "❌ Endpoint no respondió"

# Información útil
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 Comandos útiles:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  📄 Ver logs en tiempo real:"
echo "     tail -f gunicorn.log"
echo ""
echo "  🔍 Buscar logs del scheduler:"
echo "     grep -i scheduler gunicorn.log"
echo ""
echo "  🔄 Ver workers activos:"
echo "     ps aux | grep gunicorn"
echo ""
echo "  🛑 Detener Gunicorn:"
echo "     kill \$(cat gunicorn.pid)"
echo "     # o simplemente:"
echo "     ./stop_multi_worker.sh"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ Test completado."
echo "   Presiona Ctrl+C cuando termines de revisar"
echo "   o ejecuta: kill \$(cat gunicorn.pid)"
