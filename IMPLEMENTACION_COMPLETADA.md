# Implementación del Flujo Legal de Visitas - COMPLETADA

## ✅ Estado: LISTO PARA PRUEBAS

La implementación del nuevo flujo de registro de visitas con validez legal ha sido completada exitosamente.

---

## 📋 Resumen de Implementación

### Componentes Creados

#### 1. **Base de Datos**
- ✅ **Migración Alembic**: [`g5h6i7j8k9l0_add_legal_visit_fields.py`](backend/alembic/versions/g5h6i7j8k9l0_add_legal_visit_fields.py)
  - Nuevos campos en `property_visits`:
    - Consentimiento RGPD: `data_consent_accepted`, `data_consent_accepted_at`, `data_consent_ip`, `data_consent_user_agent`
    - Firma digital: `signature_filename`, `signature_filepath`, `signature_captured_at`, `signature_ip`
    - Estado del flujo: `visit_status` (draft → preview → signed → completed)
    - Auditoría: `audit_trail` (JSON)
  
- ✅ **Nueva tabla**: `visit_audit_logs`
  - Registra todos los eventos del proceso
  - Trazabilidad completa para cumplimiento legal

- ✅ **Tabla preparada** (futuro): `visit_otp_verifications`
  - Lista para integrar OTP cuando se implemente Twilio

#### 2. **Modelos SQLAlchemy**
- ✅ [`property_visit.py`](backend/app/models/property_visit.py) - Actualizado con nuevos campos
- ✅ [`visit_audit_log.py`](backend/app/models/visit_audit_log.py) - Nuevo
- ✅ [`visit_otp_verification.py`](backend/app/models/visit_otp_verification.py) - Nuevo (preparación futura)

#### 3. **Servicios**
- ✅ [`visit_audit_service.py`](backend/app/services/visit_audit_service.py)
  - Funciones de auditoría y trazabilidad
  - Captura de metadatos (IP, User-Agent, timestamps)
  - Validación de cumplimiento legal
  
- ✅ [`signature_service.py`](backend/app/services/signature_service.py)
  - Validación de firmas (detecta canvas vacío)
  - Guardar/cargar firmas como archivos PNG
  - Gestión de archivos de firma

- ✅ [`visit_sheet_generator.py`](backend/app/services/visit_sheet_generator.py) - **MODIFICADO**
  - Genera PDF incluyendo firma digital desde archivo
  - Agrega metadatos de validación legal al pie del PDF
  - Timestamp de firma, IP ofuscada, ID de documento

#### 4. **API Endpoints** - [`/app/api/visits.py`](backend/app/api/visits.py)
- ✅ `POST /api/visits/{visit_id}/accept-terms` - Registra aceptación RGPD
- ✅ `POST /api/visits/{visit_id}/save-signature` - Guarda firma digital
- ✅ `POST /api/visits/{visit_id}/finalize` - Genera PDF y envía por WhatsApp

#### 5. **Rutas Web** - [`/app/web/routes/visits.py`](backend/app/web/routes/visits.py)
- ✅ `POST /visits/create/{property_id}` - **MODIFICADO**: Crea draft en vez de completar
- ✅ `GET /visits/preview/{visit_id}` - **NUEVO**: Vista previa del documento
- ✅ `GET /visits/signature/{visit_id}` - **NUEVO**: Canvas de firma
- ✅ `GET /visits/complete/{visit_id}` - **NUEVO**: Confirmación final

#### 6. **Templates HTML**
- ✅ [`visits/preview.html`](backend/app/web/templates/visits/preview.html)
  - Documento completo con formato profesional
  - Checkbox de aceptación RGPD obligatorio
  - Indicador de progreso (4 pasos)
  
- ✅ [`visits/signature.html`](backend/app/web/templates/visits/signature.html)
  - Canvas HTML5 para firma táctil/mouse
  - Validación en tiempo real
  - Vista previa de firma antes de confirmar
  
- ✅ [`visits/complete.html`](backend/app/web/templates/visits/complete.html)
  - Confirmación de finalización
  - Genera PDF automáticamente al cargar
  - Muestra estado de envío por WhatsApp

---

## 🔄 Flujo Completo Implementado

```
┌──────────────────────────────────────────────────────────────┐
│ FASE 1: CAPTURA DE DATOS                                     │
├──────────────────────────────────────────────────────────────┤
│ 1. Asesor selecciona propiedad                               │
│ 2. Completa formulario de visita                             │
│ 3. Marca "Generar y enviar ficha"                            │
│ 4. Sistema crea visita en estado 'draft'                     │
│ 5. Auditoría: Evento 'draft_created'                         │
│ ➜ REDIRECCIÓN: /visits/preview/{visit_id}                    │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ FASE 2: VISTA PREVIA Y ACEPTACIÓN                           │
├──────────────────────────────────────────────────────────────┤
│ 1. Cliente ve documento completo formateado                  │
│ 2. Lee términos y condiciones completos                      │
│ 3. Lee autorización RGPD                                     │
│ 4. Marca checkbox: "He leído y acepto..."                    │
│ 5. Click en "Continuar a Firma"                              │
│ 6. API registra:                                              │
│    - data_consent_accepted = true                            │
│    - data_consent_accepted_at = timestamp                    │
│    - data_consent_ip = IP del cliente                        │
│    - data_consent_user_agent = navegador                     │
│ 7. Estado: 'draft' → 'preview'                               │
│ 8. Auditoría: Evento 'preview_viewed' y 'consent_accepted'   │
│ ➜ REDIRECCIÓN: /visits/signature/{visit_id}                  │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ FASE 3: FIRMA DIGITAL                                        │
├──────────────────────────────────────────────────────────────┤
│ 1. Cliente ve canvas de firma                                │
│ 2. Dibuja su firma con mouse/touch                           │
│ 3. Click en "Confirmar Firma"                                │
│ 4. Sistema valida:                                            │
│    - Canvas no vacío (varianza de píxeles > 100)             │
│    - Tamaño mínimo (> 500 bytes)                             │
│ 5. Convierte canvas a PNG                                     │
│ 6. Guarda archivo: storage/signatures/signature_{id}.png     │
│ 7. Registra en DB:                                            │
│    - signature_filename = "signature_..."                    │
│    - signature_filepath = ruta completa                      │
│    - signature_captured_at = timestamp                       │
│    - signature_ip = IP del cliente                           │
│ 8. Estado: 'preview' → 'signed'                              │
│ 9. Auditoría: Evento 'signature_captured'                    │
│ ➜ REDIRECCIÓN: /visits/complete/{visit_id}                   │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ FASE 4: FINALIZACIÓN Y GENERACIÓN PDF                       │
├──────────────────────────────────────────────────────────────┤
│ 1. Página carga y ejecuta JS automático                      │
│ 2. Llama a: POST /api/visits/{id}/finalize                   │
│ 3. Sistema genera PDF:                                        │
│    - Incluye todos los datos de la visita                    │
│    - Incrusta imagen de firma desde archivo                  │
│    - Agrega metadatos de validación:                         │
│      • Fecha/hora generación                                 │
│      • Timestamp consentimiento RGPD                         │
│      • Timestamp captura firma                               │
│      • IP ofuscada (XXX.XXX.xxx.xxx)                         │
│      • ID único de documento                                 │
│ 4. Guarda PDF en: storage/visit_sheets/ficha_visita_...pdf  │
│ 5. Envía por WhatsApp:                                        │
│    - Al cliente (visit.phone)                                │
│    - Al agente (property.agent.phone)                        │
│ 6. Estado: 'signed' → 'completed'                            │
│ 7. Auditoría: Eventos 'pdf_generated', 'visit_completed'     │
│ 8. Muestra confirmación con enlaces de descarga              │
└──────────────────────────────────────────────────────────────┘
```

---

## 🗂️ Estructura de Archivos Creados/Modificados

```
moyza_app/
├── backend/
│   ├── alembic/versions/
│   │   └── g5h6i7j8k9l0_add_legal_visit_fields.py ✨ NUEVO
│   │
│   ├── app/
│   │   ├── api/
│   │   │   └── visits.py ✨ NUEVO
│   │   │
│   │   ├── models/
│   │   │   ├── property_visit.py 🔄 MODIFICADO
│   │   │   ├── visit_audit_log.py ✨ NUEVO
│   │   │   └── visit_otp_verification.py ✨ NUEVO
│   │   │
│   │   ├── services/
│   │   │   ├── visit_audit_service.py ✨ NUEVO
│   │   │   ├── signature_service.py ✨ NUEVO
│   │   │   └── visit_sheet_generator.py 🔄 MODIFICADO
│   │   │
│   │   ├── web/
│   │   │   ├── routes/
│   │   │   │   └── visits.py 🔄 MODIFICADO
│   │   │   │
│   │   │   └── templates/visits/
│   │   │       ├── preview.html ✨ NUEVO
│   │   │       ├── signature.html ✨ NUEVO
│   │   │       └── complete.html ✨ NUEVO
│   │   │
│   │   ├── db/
│   │   │   └── base.py 🔄 MODIFICADO (importa nuevos modelos)
│   │   │
│   │   └── main.py 🔄 MODIFICADO (registra API router)
│   │
│   └── storage/ (se crea automáticamente)
│       └── signatures/ (nueva carpeta para firmas)
│
└── DISEÑO_FLUJO_VISITAS_LEGAL.md 📄 DOCUMENTACIÓN
```

---

## 🚀 Pasos para Poner en Marcha

### 1. Ejecutar Migración de Base de Datos

```bash
cd /home/jnausa/projects/moyza_app/backend

# Aplicar migración
alembic upgrade head

# Verificar que se aplicó correctamente
alembic current
```

**Resultado esperado:**
```
INFO  [alembic.runtime.migration] Running upgrade c2c34d595013 -> g5h6i7j8k9l0, add legal visit fields
```

### 2. Crear Directorios de Almacenamiento

```bash
# Crear carpeta para firmas (si no existe)
mkdir -p /home/jnausa/projects/moyza_app/storage/signatures

# Verificar permisos
chmod -R 755 /home/jnausa/projects/moyza_app/storage
```

### 3. Instalar Dependencia Faltante (si es necesario)

El servicio de firma usa **Pillow** para validar imágenes:

```bash
cd /home/jnausa/projects/moyza_app/backend
pip install Pillow
```

### 4. Reiniciar el Servidor

```bash
# Si está corriendo, detenerlo
# Ctrl+C

# Iniciar de nuevo
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Verificar que el Servidor Inició Correctamente

```bash
curl http://localhost:8000/
# Debe retornar: {"message":"MOYZA API"}
```

---

## 🧪 Pruebas Manuales Recomendadas

### Test 1: Flujo Completo Feliz

1. **Ir a**: http://localhost:8000/visits/select-property
2. **Seleccionar** una propiedad
3. **Completar** formulario de visita con todos los datos
4. **Marcar** checkbox "Generar y enviar ficha"
5. **Click** "Guardar visita"
6. **Verificar** redirección a `/visits/preview/{id}`
7. **Leer** documento completo
8. **Marcar** checkbox de aceptación RGPD
9. **Click** "Continuar a Firma" (debe estar habilitado)
10. **Verificar** redirección a `/visits/signature/{id}`
11. **Dibujar** firma en el canvas
12. **Click** "Confirmar Firma"
13. **Verificar** redirección a `/visits/complete/{id}`
14. **Esperar** generación de PDF (loading)
15. **Verificar** mensaje de éxito
16. **Click** "Descargar" y verificar PDF con firma

### Test 2: Validaciones

- **Sin marcar checkbox**: Botón "Continuar a Firma" debe estar deshabilitado
- **Canvas vacío**: Al confirmar firma, debe mostrar error
- **Sin aceptar términos**: No debe permitir acceder a `/signature`
- **Sin firma**: No debe permitir finalizar

### Test 3: Auditoría

Verificar en base de datos que se registraron los eventos:

```sql
-- Ver audit logs de una visita
SELECT * FROM visit_audit_logs WHERE visit_id = {visit_id} ORDER BY timestamp;

-- Eventos esperados:
-- 1. draft_created
-- 2. preview_viewed
-- 3. consent_accepted
-- 4. signature_captured
-- 5. pdf_generated
-- 6. visit_completed
```

### Test 4: Archivos Generados

```bash
# Verificar que se creó el archivo de firma
ls -la /home/jnausa/projects/moyza_app/storage/signatures/

# Verificar que se creó el PDF
ls -la /home/jnausa/projects/moyza_app/storage/visit_sheets/

# Abrir PDF y verificar que incluye la firma
```

---

## 📊 Verificación de Base de Datos

### Consultas Útiles

```sql
-- Ver visitas con el nuevo flujo
SELECT 
    id, 
    visitor_name, 
    visit_status,
    data_consent_accepted,
    signature_filepath,
    created_at
FROM property_visits 
WHERE visit_status IN ('draft', 'preview', 'signed', 'completed')
ORDER BY created_at DESC;

-- Ver audit trail de una visita específica
SELECT 
    id,
    visitor_name,
    audit_trail
FROM property_visits 
WHERE id = {visit_id};

-- Ver logs de auditoría detallados
SELECT 
    vl.id,
    vl.visit_id,
    vl.event_type,
    vl.timestamp,
    vl.ip_address,
    v.visitor_name
FROM visit_audit_logs vl
JOIN property_visits v ON v.id = vl.visit_id
ORDER BY vl.timestamp DESC
LIMIT 20;
```

---

## ⚠️ Problemas Conocidos y Soluciones

### Error: "Module 'PIL' not found"
**Solución:** Instalar Pillow
```bash
pip install Pillow
```

### Error: "No such table: visit_audit_logs"
**Solución:** Ejecutar migración
```bash
alembic upgrade head
```

### Error: "Permission denied" al guardar firma
**Solución:** Verificar permisos de carpeta
```bash
chmod -R 755 /home/jnausa/projects/moyza_app/storage
```

### Botón "Continuar a Firma" no se habilita
**Solución:** Verificar que JavaScript está funcionando (abrir consola del navegador)

### PDF no incluye la firma
**Solución:** Verificar que el archivo de firma existe en `storage/signatures/`

---

## 🔮 Próximos Pasos (Futuro)

### Fase 2: Implementación OTP

Cuando esté listo para integrar verificación por SMS/WhatsApp:

1. **Registrarse en Twilio**: https://www.twilio.com/
2. **Obtener credenciales**: Account SID, Auth Token, Phone Number
3. **Agregar al `.env`**:
   ```
   TWILIO_ACCOUNT_SID=ACxxxx...
   TWILIO_AUTH_TOKEN=xxxxx...
   TWILIO_PHONE_NUMBER=+1234567890
   TWILIO_WHATSAPP_NUMBER=whatsapp:+1234567890
   ```
4. **Instalar SDK**:
   ```bash
   pip install twilio
   ```
5. **Activar flujo OTP**: Ya está todo preparado en `visit_otp_verification.py`

### Mejoras Sugeridas

- [ ] Agregar preview del PDF antes de enviar (opcional)
- [ ] Permitir re-generar PDF si falla el envío
- [ ] Dashboard de estadísticas de visitas por estado
- [ ] Exportar audit logs a CSV/Excel
- [ ] Notificaciones por email además de WhatsApp
- [ ] Firma del agente inmobiliario también

---

## 📝 Notas de Cumplimiento Legal

### RGPD
- ✅ Consentimiento explícito capturado
- ✅ Timestamp de aceptación registrado
- ✅ IP capturada y ofuscada en documentos públicos
- ✅ Audit trail completo
- ⚠️ **PENDIENTE**: Implementar endpoint "Derecho al Olvido"

### Validez de Firma Digital
- ✅ Firma capturada con timestamp
- ✅ Metadatos de validación en PDF
- ✅ IP registrada (ofuscada en doc público)
- ✅ Trazabilidad completa en audit logs
- ℹ️ **OPCIONAL**: Integrar TSA (Time Stamping Authority) para máxima garantía legal

---

## 📞 Soporte

Si encuentras algún problema durante las pruebas:

1. Revisar logs del servidor:
   ```bash
   tail -f /var/log/moyza/app.log
   ```

2. Verificar consola del navegador (F12)

3. Revisar audit logs en base de datos

4. Contactar al desarrollador con:
   - Pasos para reproducir el error
   - Screenshots
   - Logs relevantes
   - ID de la visita afectada

---

## ✅ Checklist Final de Implementación

- [x] Migración de base de datos creada
- [x] Modelos SQLAlchemy actualizados
- [x] Servicios de auditoría implementados
- [x] Servicio de firma implementado
- [x] API endpoints creados
- [x] Rutas web creadas/modificadas
- [x] Templates HTML creados
- [x] Generador de PDF modificado
- [x] Indicadores de progreso agregados
- [x] Documentación completa
- [ ] **PENDIENTE**: Ejecutar migración en servidor
- [ ] **PENDIENTE**: Pruebas manuales completas
- [ ] **PENDIENTE**: Pruebas en dispositivos móviles (firma táctil)

---

**¡El sistema está LISTO para pruebas!** 🎉

Una vez ejecutada la migración de base de datos, el flujo legal estará completamente operativo.
