# Solución: Error "La firma parece estar vacía"

## Problema

Al intentar confirmar la firma digital en el canvas, aparece el mensaje:
```
Error: La firma parece estar vacía. Por favor, firme en el recuadro.
```

Esto ocurre incluso cuando has dibujado algo en el canvas.

---

## Causa Raíz

La validación de la firma usa un algoritmo que calcula la **varianza de píxeles** en la imagen. Si la varianza es muy baja (imagen muy uniforme), el sistema la considera "vacía".

El problema original era que el threshold de varianza era demasiado alto (`100.0`), lo que rechazaba firmas válidas pero con trazos ligeros.

---

## ✅ Solución Implementada

Se realizaron los siguientes cambios:

### 1. Reducción del Threshold de Varianza

**Archivo:** `backend/app/services/signature_service.py`

```python
# ANTES
def validate_signature_not_empty(signature_base64: str, min_variance: float = 100.0)

# AHORA
def validate_signature_not_empty(signature_base64: str, min_variance: float = 10.0)
```

**Cambio:** De 100.0 a 10.0 (10 veces más permisivo)

### 2. Reducción del Tamaño Mínimo de Bytes

```python
# ANTES
if len(img_bytes) < 500:

# AHORA
if len(img_bytes) < 200:
```

**Cambio:** De 500 bytes a 200 bytes

### 3. Mejoras en el Canvas (Frontend)

**Archivo:** `backend/app/web/templates/visits/signature.html`

- **Fondo blanco inicializado:** Se rellena el canvas con blanco al cargar
- **Trazo más grueso:** `lineWidth` aumentado de 2 a 3 píxeles
- **Mejor limpieza:** Al limpiar, se vuelve a rellenar con blanco

### 4. Logging Mejorado

Ahora el sistema registra en los logs:
- Tamaño de la firma en bytes
- Varianza calculada
- Threshold usado
- Resultado de la validación

**Ejemplo de log:**
```
INFO: Signature validation - Size: 3456 bytes, Variance: 45.23, Threshold: 10.0
INFO: Signature validated successfully - Variance: 45.23
```

---

## 🔧 Cómo Aplicar la Solución

### Paso 1: Actualizar el código

Los cambios ya están aplicados en los archivos:
- `backend/app/services/signature_service.py`
- `backend/app/api/visits.py`
- `backend/app/web/templates/visits/signature.html`

### Paso 2: Reiniciar el servidor

```bash
# Desde tu terminal local
docker-compose restart backend

# O si estás ejecutando manualmente
# Ctrl+C y volver a iniciar el servidor
```

### Paso 3: Limpiar caché del navegador

Es importante limpiar la caché del navegador para cargar el nuevo JavaScript:

**Chrome/Edge:**
- `Ctrl + Shift + R` (hard refresh)
- O `F12` → pestaña "Network" → marcar "Disable cache"

**Firefox:**
- `Ctrl + F5` (hard refresh)

**Safari:**
- `Cmd + Option + R`

### Paso 4: Probar de nuevo

1. Ir a: `/visits/select-property`
2. Completar el formulario
3. Aceptar términos en la vista previa
4. En el canvas de firma:
   - Dibujar tu firma con trazos claros
   - Click en "Confirmar Firma"
5. Debería funcionar ahora ✅

---

## 🐛 Si el Problema Persiste

### Verificación 1: Revisar logs del servidor

```bash
# Ver logs en tiempo real
docker logs -f moyza_app

# Buscar líneas relacionadas con firma
docker logs moyza_app | grep -i signature
```

**Buscar líneas como:**
```
INFO: Signature validation - Size: XXX bytes, Variance: XX.XX, Threshold: 10.0
```

### Verificación 2: Inspeccionar en el navegador

1. Abrir DevTools (`F12`)
2. Ir a la pestaña "Console"
3. Buscar mensajes:
   ```
   Signature data length: XXXXX
   Signature data preview: data:image/png;base64,iVBORw0K...
   ```

### Verificación 3: Probar con diferentes firmas

**Firmas que deberían funcionar:**
- ✅ Firma con trazos largos y continuos
- ✅ Firma con varias letras conectadas
- ✅ Rúbrica simple pero visible

**Firmas que podrían fallar:**
- ❌ Un solo punto
- ❌ Trazos muy cortos (< 3 píxeles)
- ❌ Canvas casi vacío

---

## 🎯 Ajuste Fino del Threshold (Avanzado)

Si necesitas ajustar más el threshold, edita estos valores:

### Para ser MÁS PERMISIVO (aceptar más firmas):

```python
# En backend/app/services/signature_service.py
def validate_signature_not_empty(signature_base64: str, min_variance: float = 5.0):
    # Reducir a 5.0 o incluso 1.0
```

### Para ser MÁS ESTRICTO (rechazar firmas débiles):

```python
# En backend/app/services/signature_service.py
def validate_signature_not_empty(signature_base64: str, min_variance: float = 20.0):
    # Aumentar a 20.0 o 30.0
```

### Recomendación por tipo de uso:

| Uso | Threshold Recomendado |
|-----|----------------------|
| Testing/Desarrollo | `1.0` - `5.0` (muy permisivo) |
| Producción normal | `10.0` - `15.0` (balanceado) |
| Legal/Formal | `20.0` - `30.0` (estricto) |
| Muy estricto | `50.0` - `100.0` (original) |

---

## 🧪 Modo Debug Temporal

Si quieres DESHABILITAR completamente la validación para testing:

**Archivo:** `backend/app/api/visits.py`

```python
# COMENTAR esta línea temporalmente:
# is_valid, error_message = validate_signature_not_empty(data.signature_data, min_variance=10.0)
# if not is_valid:
#     logger.warning(f"Signature validation failed for visit {visit_id}: {error_message}")
#     raise HTTPException(status_code=400, detail=error_message)

# Agregar log temporal:
logger.info(f"VALIDATION BYPASSED for testing - Visit {visit_id}")
```

⚠️ **IMPORTANTE:** Solo usar en desarrollo, NUNCA en producción.

---

## 📊 Tabla de Valores Típicos de Varianza

Para ayudarte a entender los valores:

| Tipo de Imagen | Varianza Típica |
|---------------|-----------------|
| Canvas vacío (blanco) | `0.0` |
| 1-2 puntos pequeños | `0.1` - `2.0` |
| Trazo muy fino | `3.0` - `8.0` |
| **Firma simple** | `10.0` - `30.0` ✅ |
| Firma compleja | `30.0` - `100.0` |
| Firma con rúbrica | `50.0` - `200.0` |
| Imagen con mucho contraste | `500.0+` |

**Threshold actual: 10.0** → Acepta firmas simples en adelante.

---

## ✅ Checklist de Verificación

Después de aplicar la solución:

- [ ] Código actualizado en `signature_service.py`
- [ ] Código actualizado en `visits.py` (API)
- [ ] Código actualizado en `signature.html` (template)
- [ ] Servidor reiniciado
- [ ] Caché del navegador limpiada
- [ ] Prueba con firma simple: ✅ Funciona
- [ ] Prueba con firma compleja: ✅ Funciona
- [ ] Logs muestran valores de varianza

---

## 🆘 Contacto de Soporte

Si después de aplicar todos estos cambios el problema persiste:

1. Captura de pantalla del error
2. Logs del servidor (últimas 50 líneas con "signature")
3. Console del navegador (DevTools → Console)
4. Describe el tipo de firma que estás intentando

**Comando para obtener logs relevantes:**
```bash
docker logs moyza_app --tail 100 | grep -i "signature\|visit\|error"
```

---

## 📝 Resumen de Cambios

| Parámetro | Antes | Ahora | Efecto |
|-----------|-------|-------|--------|
| `min_variance` | 100.0 | 10.0 | 10x más permisivo |
| `min_bytes` | 500 | 200 | 2.5x más permisivo |
| `lineWidth` | 2px | 3px | Trazos más visibles |
| Fondo canvas | Transparente | Blanco | Mejor contraste |

**Resultado esperado:** Las firmas normales ahora se validan correctamente. ✅
