# 🤖 Integración de IA en MOYZA

## Descripción General

Este documento describe la integración de Inteligencia Artificial (OpenAI GPT-4o) en el sistema MOYZA para generar valuaciones automáticas y observaciones estratégicas en los reportes de propiedades.

## Características

- ✅ **Valuación automática**: Estimación de valor de mercado basada en ubicación, características y actividad comercial
- ✅ **Análisis de mercado**: Evaluación del comportamiento comercial de la propiedad
- ✅ **Recomendaciones estratégicas**: Sugerencias accionables para optimizar la comercialización
- ✅ **Evaluación de riesgo**: Nivel de riesgo comercial (bajo, medio, alto)
- ✅ **Identificación de oportunidades**: Puntos de mejora detectados automáticamente

## Arquitectura

```
ReportJobService (orquestador)
    ├─> PropertyMetricsService (recolección de datos)
    ├─> AIValuationService (análisis con IA) ← NUEVO
    └─> ReportGenerator (generación de PDF)
```

## Archivos Modificados/Creados

### Nuevos Archivos
- `backend/app/services/ai_valuation.py` - Servicio principal de IA

### Archivos Modificados
- `backend/requirements.txt` - Agregada dependencia `openai>=1.50.0`
- `backend/.env.example` - Variables de configuración de OpenAI
- `backend/app/core/config.py` - Configuración de credenciales de IA
- `backend/app/services/report_job_service.py` - Integración del análisis de IA
- `backend/app/services/report_generator.py` - Visualización de datos de IA en PDF

## Configuración

### 1. Variables de Entorno

Copia `.env.example` a `.env` y configura según el proveedor que quieras usar:

#### **Opción A: Usar OpenAI (default)**

```bash
AI_PROVIDER=openai

# OpenAI API Configuration
OPENAI_API_KEY=sk-proj-tu-api-key-aqui
OPENAI_MODEL=gpt-4o  # Opciones: gpt-4o, gpt-4o-mini, gpt-4-turbo
OPENAI_MAX_TOKENS=2000
OPENAI_TEMPERATURE=0.3
```

**Obtener API Key de OpenAI:**
1. Ve a [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Inicia sesión o crea una cuenta
3. Click en "Create new secret key"
4. Copia la key y agrégala a tu `.env`

⚠️ **IMPORTANTE**: Necesitas tener créditos en tu cuenta de OpenAI. La API es de pago.

#### **Opción B: Usar Gemini (más económico)**

```bash
AI_PROVIDER=gemini

# Gemini API Configuration
GEMINI_API_KEY=AIza-tu-api-key-aqui
GEMINI_MODEL=gemini-1.5-flash  # Opciones: gemini-1.5-flash, gemini-1.5-pro, gemini-2.0-flash-exp
OPENAI_MAX_TOKENS=2000  # Gemini usa la misma config para max tokens y temperature
OPENAI_TEMPERATURE=0.3
```

**Obtener API Key de Gemini:**
1. Ve a [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Inicia sesión con tu cuenta de Google
3. Click en "Create API key"
4. Copia la key y agrégala a tu `.env`

✅ **VENTAJA**: Gemini tiene un tier **gratuito generoso** (15 RPM) para desarrollo/pruebas.

### 3. Instalar Dependencias

```bash
cd backend
pip install -r requirements.txt
```

## Uso

### Automático (Reportes Programados)

El análisis de IA se ejecuta automáticamente cuando:
- APScheduler genera un reporte programado
- Una propiedad tiene `auto_send_report=True`

No requiere acción manual.

### Manual (Desarrollo/Testing)

Puedes probar el servicio directamente:

```python
from app.services.ai_valuation import AIValuationService
from app.services.property_metrics import PropertyMetricsService

# Obtener propiedad
property_item = db.query(Property).filter(Property.id == 1).first()

# Recolectar métricas
metrics = PropertyMetricsService(db).report_data(property_item)

# Generar análisis con IA
ai_service = AIValuationService(db)
analysis = ai_service.generate_analysis(property_item, metrics)

print(analysis)
```

## Estructura de Respuesta de IA

### Valuación (`ai_valuation`)

```json
{
  "estimated_value": 150000.00,
  "confidence": "alta",
  "reasoning": "Análisis detallado del tasador IA...",
  "price_range": {
    "min": 140000.00,
    "max": 160000.00
  }
}
```

### Observaciones (`ai_observations`)

```json
{
  "market_analysis": "Análisis del comportamiento actual...",
  "recommendations": [
    "Recomendación 1 específica",
    "Recomendación 2 específica",
    "Recomendación 3 específica"
  ],
  "risk_level": "medio",
  "opportunities": "Descripción de oportunidades..."
}
```

## Manejo de Errores

El sistema está diseñado para **degradar gracefully**:

1. **Sin API Key configurada**: El reporte se genera sin análisis de IA
2. **Error de OpenAI**: Se logea el error y el reporte continúa sin IA
3. **Timeout**: Después del timeout configurado, se salta el análisis

En todos los casos, el PDF muestra un mensaje indicando que el análisis no está disponible.

## Logs

El servicio registra eventos importantes:

```python
# Éxito
INFO: Valuación generada exitosamente para propiedad 42
INFO: Observaciones generadas exitosamente para propiedad 42

# Advertencias
WARNING: OPENAI_API_KEY no configurada. El servicio de IA no estará disponible.
WARNING: No se pudo generar análisis de IA para propiedad 42

# Errores
ERROR: Error de OpenAI generando análisis para propiedad 42: RateLimitError
```

## Costos Estimados

### Comparación de Proveedores

#### **OpenAI GPT-4o**

- **Input**: $2.50 por 1M tokens
- **Output**: $10 por 1M tokens
- **Por reporte**: ~$0.012 USD
- **100 reportes/mes**: ~$36 USD

#### **Gemini 1.5 Flash (Recomendado para producción económica)**

- **Input**: $0.075 por 1M tokens
- **Output**: $0.30 por 1M tokens
- **Por reporte**: ~$0.0007 USD
- **100 reportes/mes**: ~$2.10 USD
- **🎉 Tier gratuito**: 15 RPM (suficiente para desarrollo/staging)

#### **Gemini 1.5 Pro (Balance calidad/precio)**

- **Input**: $1.25 por 1M tokens
- **Output**: $5.00 por 1M tokens
- **Por reporte**: ~$0.006 USD
- **100 reportes/mes**: ~$18 USD

### Proyecciones Mensuales Comparadas

| Reportes/mes | GPT-4o (OpenAI) | Gemini 1.5 Flash | Ahorro |
|--------------|-----------------|------------------|--------|
| 300          | $36.00          | $2.10            | 94%    |
| 1,500        | $180.00         | $10.50           | 94%    |
| 3,000        | $360.00         | $21.00           | 94%    |
| 15,000       | $1,800.00       | $105.00          | 94%    |

💡 **Recomendación**: 
- **Desarrollo/Staging**: Gemini con tier gratuito
- **Producción bajo volumen**: Gemini 1.5 Flash
- **Producción alta calidad**: GPT-4o o Gemini 1.5 Pro

## Optimizaciones Futuras

### 1. Sistema de Cache (Recomendado)

Evita llamadas redundantes a la API:
- Cache análisis por X días si no cambian los datos de la propiedad
- Invalida cache cuando cambia el precio o métricas significativas

**Ahorro estimado**: 60-80% de costos

### 2. Batching de Propiedades

Si tienes muchas propiedades del mismo vecindario:
- Analizar múltiples propiedades en un solo prompt
- Aprovechar contexto compartido

**Ahorro estimado**: 30-40% de costos

### 3. Usar GPT-4o-mini para Análisis Simples

Para propiedades con poca actividad:
- Usar modelo más económico (~10x más barato)
- Reservar GPT-4o para casos complejos

**Ahorro estimado**: 50-70% de costos en casos simples

### 4. Prompt Caching (OpenAI)

Aprovechar la feature de prompt caching de OpenAI:
- Cachear la parte del system prompt
- Reducir tokens de input en llamadas repetidas

**Ahorro estimado**: 20-30% de costos

## Sistema de Auditoría

### Tabla `ai_analysis_logs`

Todos los análisis de IA se registran automáticamente en la tabla `ai_analysis_logs`, que incluye:

- **Tracking de costos**: Tokens usados y costo estimado en USD
- **Debugging**: Prompts completos y respuestas JSON
- **Performance**: Tiempo de respuesta de cada llamada
- **Errores**: Stack traces de fallos
- **Metadata**: Modelo, temperatura, max_tokens

### Endpoints de Auditoría

El sistema incluye endpoints REST para consultar los logs:

#### 1. **Listar logs** - `GET /api/ai-logs`

Query params:
- `property_id`: Filtrar por propiedad
- `analysis_type`: `valuation` o `observations`
- `status`: `success`, `error`, o `timeout`
- `limit`: Máximo de resultados (default: 50)
- `offset`: Para paginación

Ejemplo:
```bash
curl "http://localhost:8000/api/ai-logs?property_id=42&limit=10"
```

#### 2. **Detalle de log** - `GET /api/ai-logs/{log_id}`

Obtiene el detalle completo incluyendo prompt y response.

```bash
curl "http://localhost:8000/api/ai-logs/123"
```

#### 3. **Estadísticas resumidas** - `GET /api/ai-logs/stats/summary`

Query params:
- `days`: Cantidad de días a incluir (default: 30)

Retorna:
- Total de llamadas
- Tasa de éxito
- Tokens consumidos
- Costo total
- Tiempo promedio de respuesta
- Distribución por tipo de análisis
- Costos por modelo

```bash
curl "http://localhost:8000/api/ai-logs/stats/summary?days=7"
```

Respuesta ejemplo:
```json
{
  "period_days": 7,
  "total_calls": 150,
  "success_count": 147,
  "error_count": 3,
  "success_rate": 98.0,
  "total_tokens": 225000,
  "total_cost_usd": 1.85,
  "avg_response_time_seconds": 2.3,
  "valuations_count": 75,
  "observations_count": 75,
  "costs_by_model": [
    {
      "model": "gpt-4o",
      "calls": 150,
      "total_cost": 1.85,
      "total_tokens": 225000,
      "avg_cost_per_call": 0.012
    }
  ]
}
```

#### 4. **Estadísticas diarias** - `GET /api/ai-logs/stats/daily`

Útil para gráficos de tendencias.

```bash
curl "http://localhost:8000/api/ai-logs/stats/daily?days=30"
```

#### 5. **Historial por propiedad** - `GET /api/ai-logs/property/{property_id}/history`

Historial completo de análisis para una propiedad específica.

```bash
curl "http://localhost:8000/api/ai-logs/property/42/history"
```

### Queries SQL Útiles

```sql
-- Costo total en los últimos 30 días
SELECT 
  SUM(estimated_cost) as total_cost_usd,
  SUM(total_tokens) as total_tokens,
  COUNT(*) as total_calls
FROM ai_analysis_logs
WHERE created_at >= NOW() - INTERVAL '30 days'
  AND status = 'success';

-- Propiedades más analizadas
SELECT 
  p.id,
  p.title,
  COUNT(aal.id) as analyses_count,
  SUM(aal.estimated_cost) as total_cost
FROM properties p
JOIN ai_analysis_logs aal ON aal.property_id = p.id
WHERE aal.status = 'success'
GROUP BY p.id, p.title
ORDER BY total_cost DESC
LIMIT 10;

-- Promedio de tokens por tipo de análisis
SELECT 
  analysis_type,
  AVG(prompt_tokens) as avg_prompt_tokens,
  AVG(completion_tokens) as avg_completion_tokens,
  AVG(total_tokens) as avg_total_tokens,
  AVG(estimated_cost) as avg_cost
FROM ai_analysis_logs
WHERE status = 'success'
GROUP BY analysis_type;

-- Errores más comunes
SELECT 
  error_message,
  COUNT(*) as error_count,
  MAX(created_at) as last_occurrence
FROM ai_analysis_logs
WHERE status = 'error'
GROUP BY error_message
ORDER BY error_count DESC;

-- Tendencia de costos por día (últimos 30 días)
SELECT 
  DATE(created_at) as date,
  COUNT(*) as calls,
  SUM(estimated_cost) as daily_cost,
  SUM(total_tokens) as daily_tokens
FROM ai_analysis_logs
WHERE created_at >= NOW() - INTERVAL '30 days'
  AND status = 'success'
GROUP BY DATE(created_at)
ORDER BY date DESC;
```

## Monitoreo

### Dashboard Recomendado

Puedes crear un dashboard usando los endpoints de auditoría:

1. **KPIs principales**:
   - Costo del día/mes
   - Tokens consumidos
   - Tasa de éxito
   - Tiempo promedio de respuesta

2. **Gráficos**:
   - Tendencia de costos (últimos 30 días)
   - Distribución por tipo de análisis
   - Propiedades más analizadas

3. **Alertas**:
   - Costo diario > umbral definido
   - Tasa de error > 5%
   - Tiempo de respuesta > 10s

### Ejemplo de Alertas

```python
# Script para monitoreo (ejecutar con cron)
import requests

response = requests.get("http://localhost:8000/api/ai-logs/stats/summary?days=1")
stats = response.json()

# Alerta de costo
if stats["total_cost_usd"] > 10.0:
    send_alert(f"⚠️ Costo de IA alto: ${stats['total_cost_usd']:.2f} USD hoy")

# Alerta de errores
if stats["success_rate"] < 95.0:
    send_alert(f"⚠️ Tasa de éxito baja: {stats['success_rate']:.1f}%")
```

## Troubleshooting

### El análisis de IA no se genera

1. ✅ Verifica que `OPENAI_API_KEY` está configurada
2. ✅ Verifica que tienes créditos en OpenAI
3. ✅ Revisa los logs en `backend/logs/`
4. ✅ Prueba el servicio manualmente (ver sección "Uso")

### Error: "RateLimitError"

- Has excedido el rate limit de OpenAI
- **Solución**: Espera o aumenta tu tier en OpenAI

### Error: "AuthenticationError"

- API Key inválida o expirada
- **Solución**: Genera una nueva key en OpenAI

### Los análisis son muy genéricos

- Ajusta `OPENAI_TEMPERATURE` (más bajo = más consistente)
- Mejora los prompts en `ai_valuation.py`
- Considera usar GPT-4o (más capaz que GPT-4o-mini)

## Seguridad

⚠️ **Nunca commitees tu API key al repositorio**

```bash
# Asegúrate que .env está en .gitignore
echo ".env" >> .gitignore
```

## Soporte

Para preguntas o issues:
1. Revisa los logs en `backend/logs/`
2. Revisa la documentación de OpenAI: [https://platform.openai.com/docs](https://platform.openai.com/docs)
3. Contacta al equipo de desarrollo

---

**Última actualización**: 2026-06-11
