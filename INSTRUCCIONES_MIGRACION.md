# 🚀 Instrucciones para Ejecutar la Migración

## Contexto

Ya resolvimos el conflicto de las dos heads de Alembic creando una migración de merge. Ahora puedes ejecutar la migración desde **dentro del contenedor Docker**.

---

## ✅ Solución del Problema

**Problema detectado:** Había dos heads en Alembic:
- `a9b8c7d6e5f4` - add visit sheet fields (migración previa)
- `g5h6i7j8k9l0` - add legal visit fields (migración nueva del flujo legal)

**Solución aplicada:** Se creó una migración de merge:
- `2127fcfd5306` - merge visit fields migrations

Ahora solo hay **una head** y la migración puede ejecutarse sin problemas.

---

## 📋 Método 1: Script Automático (Recomendado)

Desde **dentro del contenedor Docker**:

```bash
# 1. Entrar al contenedor (desde tu terminal local)
docker exec -it moyza_app bash

# 2. Ir al directorio de la aplicación
cd /app

# 3. Ejecutar el script de migración
bash EJECUTAR_MIGRACION.sh
```

El script hará automáticamente:
- ✅ Verificar estado actual
- ✅ Ejecutar migración
- ✅ Crear directorio de firmas
- ✅ Verificar que todo funcionó

---

## 📋 Método 2: Manual (Paso a Paso)

Si prefieres hacerlo manualmente:

### Paso 1: Entrar al contenedor

```bash
# Desde tu terminal local
docker exec -it moyza_app bash
```

### Paso 2: Ir al directorio correcto

```bash
cd /app
```

### Paso 3: Verificar estado actual (opcional)

```bash
alembic current
alembic heads
```

Deberías ver solo una head: `2127fcfd5306`

### Paso 4: Ejecutar migración

```bash
alembic upgrade head
```

**Salida esperada:**
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade c2c34d595013 -> g5h6i7j8k9l0, add legal visit fields
INFO  [alembic.runtime.migration] Running upgrade c2c34d595013 -> a9b8c7d6e5f4, add visit sheet fields
INFO  [alembic.runtime.migration] Running upgrade a9b8c7d6e5f4, g5h6i7j8k9l0 -> 2127fcfd5306, merge visit fields migrations
```

### Paso 5: Crear directorio para firmas

```bash
mkdir -p /app/storage/signatures
chmod -R 755 /app/storage
```

### Paso 6: Verificar migración

```bash
alembic current
```

Debería mostrar: `2127fcfd5306 (head)`

---

## 🎯 Después de la Migración

### 1. Verificar en Base de Datos

Puedes conectarte a PostgreSQL y verificar que se crearon las nuevas columnas y tablas:

```sql
-- Ver columnas nuevas en property_visits
\d property_visits

-- Ver tabla de auditoría
\d visit_audit_logs

-- Ver tabla OTP (preparación futura)
\d visit_otp_verifications
```

### 2. Reiniciar Servidor (si está corriendo)

Si el servidor FastAPI está corriendo, reinícialo para que cargue los nuevos modelos:

```bash
# Desde fuera del contenedor
docker-compose restart backend

# O detener y volver a iniciar
docker-compose down
docker-compose up -d
```

### 3. Probar el Flujo

Abre tu navegador y ve a:
```
http://localhost:8000/visits/select-property
```

Sigue el flujo completo:
1. Selecciona propiedad
2. Llena formulario
3. Marca "Generar y enviar ficha"
4. → Vista previa
5. → Acepta términos
6. → Firma
7. → Confirmación con PDF

---

## ⚠️ Problemas Comunes

### Error: "could not translate host name 'db'"

**Causa:** No estás dentro del contenedor Docker.

**Solución:**
```bash
docker exec -it moyza_app bash
cd /app
alembic upgrade head
```

### Error: "Multiple head revisions"

**Causa:** Ya fue resuelto con la migración de merge, pero si vuelve a aparecer:

**Solución:**
```bash
alembic merge -m "merge heads" heads
alembic upgrade head
```

### Error: "Permission denied" al crear directorio

**Causa:** Permisos insuficientes.

**Solución:**
```bash
sudo mkdir -p /home/jnausa/projects/moyza_app/storage/signatures
sudo chmod -R 755 /home/jnausa/projects/moyza_app/storage
sudo chown -R $(whoami):$(whoami) /home/jnausa/projects/moyza_app/storage
```

### Error: "Module 'PIL' not found"

**Causa:** Falta la librería Pillow.

**Solución:**
```bash
pip install Pillow
```

---

## 📊 Verificación Post-Migración

### Checklist Rápido

- [ ] Migración ejecutada sin errores
- [ ] `alembic current` muestra `2127fcfd5306`
- [ ] Directorio `storage/signatures` existe
- [ ] Servidor reiniciado
- [ ] Puede acceder a `/visits/select-property`
- [ ] Flujo completo funciona

### SQL de Verificación

```sql
-- Verificar columnas nuevas
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'property_visits' 
  AND column_name LIKE '%consent%' OR column_name LIKE '%signature%';

-- Verificar tabla de auditoría
SELECT COUNT(*) FROM visit_audit_logs;

-- Verificar tabla OTP
SELECT COUNT(*) FROM visit_otp_verifications;
```

---

## 🎉 ¡Listo!

Una vez completada la migración, el sistema estará completamente operativo con el nuevo flujo legal de visitas.

**Documentación completa:**
- [DISEÑO_FLUJO_VISITAS_LEGAL.md](DISEÑO_FLUJO_VISITAS_LEGAL.md) - Diseño técnico detallado
- [IMPLEMENTACION_COMPLETADA.md](IMPLEMENTACION_COMPLETADA.md) - Guía de implementación

**¿Necesitas ayuda?**
Revisa los logs del servidor y la base de datos, o contacta al desarrollador con los detalles del error.
