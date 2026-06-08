#!/bin/bash
# Script para ejecutar tests unitarios

set -e

echo "🧪 Ejecutando tests unitarios..."
echo "================================"
echo ""

# Verificar que pytest está instalado
if ! command -v pytest &> /dev/null; then
    echo "⚠️  pytest no está instalado. Instalando..."
    pip install pytest pytest-cov
fi

# Opciones según argumento
case "${1:-all}" in
    "scheduler")
        echo "🔧 Ejecutando solo tests del scheduler..."
        pytest tests/test_scheduler.py -v --tb=short
        ;;
    "coverage")
        echo "📊 Ejecutando tests con coverage..."
        pytest tests/ -v --cov=app --cov-report=term-missing --cov-report=html
        echo ""
        echo "📄 Reporte HTML generado en: htmlcov/index.html"
        ;;
    "watch")
        echo "👀 Ejecutando tests en modo watch..."
        pytest tests/ -v --tb=short -f
        ;;
    "all")
        echo "🚀 Ejecutando todos los tests..."
        pytest tests/ -v --tb=short
        ;;
    *)
        echo "❌ Opción no reconocida: $1"
        echo ""
        echo "Uso: $0 [scheduler|coverage|watch|all]"
        echo ""
        echo "Ejemplos:"
        echo "  $0              # Ejecutar todos los tests"
        echo "  $0 scheduler    # Solo tests del scheduler"
        echo "  $0 coverage     # Con reporte de cobertura"
        echo "  $0 watch        # Modo watch (re-ejecuta al cambiar archivos)"
        exit 1
        ;;
esac

echo ""
echo "✅ Tests completados"
