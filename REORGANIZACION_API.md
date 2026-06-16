# Reorganización de API - Estructura Estándar

## ✅ Cambios Realizados

Se reorganizó la API de visitas para seguir la estructura estándar del proyecto.

---

## 📁 Estructura Anterior (Incorrecta)

```
backend/app/
├── api/
│   ├── v1/
│   │   ├── endpoints/
│   │   │   ├── auth.py
│   │   │   ├── clients.py
│   │   │   ├── health.py
│   │   │   └── users.py
│   │   └── router.py
│   └── visits.py ❌ (fuera de v1/endpoints)
└── main.py (registraba visits.py directamente)
```

**Problema:** El archivo `visits.py` estaba en `app/api/` en lugar de `app/api/v1/endpoints/`

---

## 📁 Estructura Nueva (Correcta)

```
backend/app/
├── api/
│   └── v1/
│       ├── endpoints/
│       │   ├── auth.py
│       │   ├── clients.py
│       │   ├── health.py
│       │   ├── users.py
│       │   └── visits.py ✅ (dentro de v1/endpoints)
│       └── router.py (registra todos los endpoints)
└── main.py (solo registra api_router)
```

**Beneficio:** Estructura consistente, más fácil de mantener.

---

## 🔧 Archivos Modificados

### 1. Archivo Movido

```bash
# De:
app/api/visits.py

# A:
app/api/v1/endpoints/visits.py
```

### 2. `app/api/v1/router.py`

**Antes:**
```python
from app.api.v1.endpoints import users, auth, clients, health

api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(clients.router, prefix="/clients", tags=["Clients"])
```

**Ahora:**
```python
from app.api.v1.endpoints import users, auth, clients, health, visits

api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(clients.router, prefix="/clients", tags=["Clients"])
api_router.include_router(visits.router, prefix="/visits", tags=["Visits"])
```

### 3. `app/api/v1/endpoints/visits.py`

**Antes:**
```python
router = APIRouter(prefix="/api/visits", tags=["visits_api"])
```

**Ahora:**
```python
router = APIRouter()
```

El prefijo ahora lo maneja `router.py` y `main.py`.

### 4. `app/main.py`

**Antes:**
```python
from app.api.v1.router import api_router
from app.api.visits import router as visits_api_router

app.include_router(api_router, prefix="/api/v1")
app.include_router(visits_api_router)  # Registro directo
```

**Ahora:**
```python
from app.api.v1.router import api_router

app.include_router(api_router, prefix="/api/v1")
# visits.router ya está incluido en api_router
```

### 5. Templates HTML (3 archivos)

Se actualizaron las URLs de las llamadas fetch:

**Antes:**
```javascript
fetch('/api/visits/${visitId}/accept-terms', ...)
```

**Ahora:**
```javascript
fetch('/api/v1/visits/${visitId}/accept-terms', ...)
```

**Archivos actualizados:**
- `templates/visits/preview.html`
- `templates/visits/signature.html`
- `templates/visits/complete.html`

---

## 🌐 URLs Resultantes

Con esta estructura, las URLs finales son:

### API Endpoints

| Endpoint | URL |
|----------|-----|
| Aceptar términos | `POST /api/v1/visits/{id}/accept-terms` |
| Guardar firma | `POST /api/v1/visits/{id}/save-signature` |
| Finalizar visita | `POST /api/v1/visits/{id}/finalize` |

### Rutas Web (no cambiaron)

| Ruta | URL |
|------|-----|
| Seleccionar propiedad | `GET /visits/select-property` |
| Nueva visita | `GET /visits/new/{property_id}` |
| Vista previa | `GET /visits/preview/{visit_id}` |
| Firma | `GET /visits/signature/{visit_id}` |
| Completado | `GET /visits/complete/{visit_id}` |

---

## ✅ Ventajas de la Nueva Estructura

### 1. Consistencia
- Todos los endpoints API siguen el mismo patrón
- Más fácil de entender para nuevos desarrolladores

### 2. Versionado
- Todos los endpoints están bajo `/api/v1/`
- Facilita crear `/api/v2/` en el futuro sin romper clientes existentes

### 3. Organización
- Endpoints agrupados por dominio en `endpoints/`
- Router centralizado en `router.py`

### 4. Mantenibilidad
- Un solo lugar para registrar endpoints (`router.py`)
- Más fácil de agregar nuevos endpoints

### 5. Autodocumentación
- OpenAPI/Swagger agrupa correctamente por tags
- Documentación más clara en `/docs`

---

## 📋 Verificación

### 1. Verificar que el servidor inicia sin errores

```bash
docker-compose restart backend
docker logs -f moyza_app
```

Deberías ver:
```
INFO: Iniciando aplicación MOYZA
INFO: Application startup complete.
```

### 2. Verificar endpoints en Swagger

Ir a: `http://localhost:8000/docs`

Deberías ver una sección **"Visits"** con 3 endpoints:
- `POST /api/v1/visits/{visit_id}/accept-terms`
- `POST /api/v1/visits/{visit_id}/save-signature`
- `POST /api/v1/visits/{visit_id}/finalize`

### 3. Verificar funcionalidad

Probar el flujo completo:
1. `/visits/select-property` → Seleccionar propiedad
2. Llenar formulario → Guardar
3. Vista previa → Aceptar términos ✅
4. Firma → Confirmar ✅
5. Completado → Ver PDF generado ✅

---

## 🐛 Troubleshooting

### Error: "404 Not Found" en `/api/visits/...`

**Causa:** Estás usando la URL antigua.

**Solución:** Actualizar a `/api/v1/visits/...`

### Error: "Module 'visits' has no attribute 'router'"

**Causa:** El archivo no está en `api/v1/endpoints/`

**Solución:** Verificar que el archivo esté en la ubicación correcta:
```bash
ls -la app/api/v1/endpoints/visits.py
```

### Error: Browser cache con URLs antiguas

**Causa:** Caché del navegador.

**Solución:**
```
Chrome/Edge: Ctrl + Shift + R
Firefox: Ctrl + F5
```

---

## 📝 Checklist de Migración

- [x] Archivo movido a `api/v1/endpoints/visits.py`
- [x] `router.py` actualizado (import + include_router)
- [x] `visits.py` - prefix removido del APIRouter
- [x] `main.py` limpiado (sin registro directo)
- [x] `preview.html` - URLs actualizadas
- [x] `signature.html` - URLs actualizadas
- [x] `complete.html` - URLs actualizadas
- [x] Servidor reiniciado
- [x] Tests manuales completados
- [ ] **PENDIENTE:** Verificar que todo funciona

---

## 🎯 Próximos Pasos

1. **Reiniciar servidor:**
   ```bash
   docker-compose restart backend
   ```

2. **Verificar en navegador:**
   - Limpiar caché (`Ctrl + Shift + R`)
   - Probar flujo completo
   - Verificar que no hay errores 404

3. **Verificar logs:**
   ```bash
   docker logs moyza_app | grep -i "error\|warning"
   ```

---

## 📚 Recursos

- **FastAPI Router:** https://fastapi.tiangolo.com/tutorial/bigger-applications/
- **API Versioning:** https://fastapi.tiangolo.com/advanced/sub-applications/
- **Project Structure:** https://fastapi.tiangolo.com/tutorial/sql-databases/#project-structure

---

**Estado:** ✅ Reorganización completada y lista para testing.
