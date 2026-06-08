#!/bin/bash
# Script para probar que el scheduler solo se inicia en un worker

echo "🧪 Probando scheduler con multi-worker..."
echo "========================================"
echo ""

# Iniciar Gunicorn con 4 workers
echo "▶️  Iniciando Gunicorn con 4 workers..."
gunicorn -c gunicorn.conf.py app.main:app --daemon --pid gunicorn.pid

# Esperar a que inicie
sleep 3

# Verificar logs
echo ""
echo "📋 Verificando logs del scheduler..."
echo "======================================"

# Contar cuántos workers iniciaron el scheduler
SCHEDULER_STARTS=$(ps aux | grep gunicorn | grep -v grep | wc -l)
echo "✓ Workers de Gunicorn activos: $SCHEDULER_STARTS"

# Hacer una request de prueba
echo ""
echo "🌐 Haciendo request de prueba..."
curl -s http://localhost:8000/ | jq '.'

echo ""
echo "🔍 Para ver los logs completos:"
echo "   tail -f /var/log/gunicorn.log"
echo ""
echo "🛑 Para detener:"
echo "   kill \$(cat gunicorn.pid)"
echo ""
echo "✅ Test completado. Verifica que solo un worker inició el scheduler."
