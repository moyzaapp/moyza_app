#!/bin/bash

# Script para ejecutar la migración de base de datos del flujo legal de visitas
# Este script debe ejecutarse DESDE DENTRO del contenedor Docker

echo "=========================================="
echo "Migración: Flujo Legal de Visitas"
echo "=========================================="
echo ""

# Verificar que estamos en el directorio correcto
if [ ! -f "alembic.ini" ]; then
    echo "❌ ERROR: Este script debe ejecutarse desde el directorio /app dentro del contenedor"
    echo "   Usa: docker exec -it <container_name> bash"
    echo "   Luego: cd /app && bash EJECUTAR_MIGRACION.sh"
    exit 1
fi

echo "📋 Estado actual de migraciones..."
echo ""
alembic current
echo ""

echo "📝 Mostrando heads disponibles..."
echo ""
alembic heads
echo ""

echo "⬆️  Ejecutando migración..."
echo ""
alembic upgrade head

if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "✅ MIGRACIÓN COMPLETADA EXITOSAMENTE"
    echo "=========================================="
    echo ""
    echo "Verificando estado..."
    alembic current
    echo ""

    echo "📁 Creando directorio para firmas..."
    mkdir -p /app/storage/signatures
    chmod -R 755 /app/storage
    echo "✅ Directorio creado: /app/storage/signatures"
    echo ""

    echo "=========================================="
    echo "🎉 TODO LISTO!"
    echo "=========================================="
    echo ""
    echo "El sistema está listo para usar el nuevo flujo legal."
    echo ""
    echo "Próximos pasos:"
    echo "1. Reiniciar el servidor FastAPI si está corriendo"
    echo "2. Probar el flujo: http://localhost:8000/visits/select-property"
    echo "3. Revisar la documentación en IMPLEMENTACION_COMPLETADA.md"
    echo ""
else
    echo ""
    echo "=========================================="
    echo "❌ ERROR EN LA MIGRACIÓN"
    echo "=========================================="
    echo ""
    echo "Por favor revisa los errores arriba."
    echo "Si necesitas ayuda, contacta al desarrollador."
    echo ""
    exit 1
fi
