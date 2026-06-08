#!/bin/bash
# Script para detener Gunicorn de manera limpia

echo "🛑 Deteniendo Gunicorn..."

if [ -f gunicorn.pid ]; then
    PID=$(cat gunicorn.pid)
    echo "   PID encontrado: $PID"

    kill $PID

    # Esperar a que se detenga
    sleep 2

    # Verificar que se detuvo
    if ps -p $PID > /dev/null 2>&1; then
        echo "⚠️  Proceso aún activo, forzando detención..."
        kill -9 $PID
    fi

    rm -f gunicorn.pid
    echo "✅ Gunicorn detenido correctamente"
else
    echo "⚠️  No se encontró gunicorn.pid"

    # Buscar procesos de gunicorn
    GUNICORN_PIDS=$(ps aux | grep "[g]unicorn" | awk '{print $2}')

    if [ -z "$GUNICORN_PIDS" ]; then
        echo "✅ No hay procesos de Gunicorn corriendo"
    else
        echo "🔍 Procesos de Gunicorn encontrados:"
        ps aux | grep "[g]unicorn"
        echo ""
        echo "Para detenerlos manualmente:"
        echo "   kill $GUNICORN_PIDS"
    fi
fi
