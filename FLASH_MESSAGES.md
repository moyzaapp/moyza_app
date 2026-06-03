# Sistema de Mensajes Flash

Sistema de mensajes temporales para mostrar feedback al usuario después de realizar acciones en la aplicación.

## Características

- ✅ Mensajes con 4 categorías: `success`, `error`, `warning`, `info`
- ✅ Diseño visual con iconos y colores según el tipo
- ✅ Auto-cierre después de 5 segundos
- ✅ Botón de cierre manual
- ✅ Animación de entrada suave
- ✅ Almacenamiento en cookies (solo se muestran una vez)

## Tipos de Mensajes

### Success (Verde)
```python
set_flash(response, "success", "Propiedad creada correctamente")
```
- Color: Verde
- Icono: Check circle
- Uso: Operaciones exitosas

### Error (Rojo)
```python
set_flash(response, "error", "No se pudo crear la propiedad")
```
- Color: Rojo
- Icono: X circle
- Uso: Errores y fallos

### Warning (Amarillo)
```python
set_flash(response, "warning", "El cliente no tiene teléfono registrado")
```
- Color: Amarillo
- Icono: Alerta
- Uso: Advertencias y situaciones que requieren atención

### Info (Azul)
```python
set_flash(response, "info", "Recuerda completar los datos del cliente")
```
- Color: Azul
- Icono: Información
- Uso: Mensajes informativos

## Implementación en Rutas

### Ejemplo básico
```python
from app.web.utils.flash import set_flash
from fastapi.responses import RedirectResponse

@router.post("/properties/create")
async def create_property(...):
    # ... lógica de creación ...
    
    response = RedirectResponse(url="/properties", status_code=302)
    set_flash(response, "success", "Propiedad creada correctamente")
    return response
```

### Con manejo de errores
```python
@router.post("/properties/create")
async def create_property(...):
    try:
        # ... lógica de creación ...
        db.commit()
        
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "success", "Propiedad creada correctamente")
        return response
        
    except Exception as e:
        print(f"Error: {e}")
        response = RedirectResponse(url="/properties", status_code=302)
        set_flash(response, "error", "Ocurrió un error al crear la propiedad")
        return response
```

### Con validaciones
```python
@router.post("/reports/{report_id}/send-whatsapp")
async def send_report(...):
    response = RedirectResponse(url="/reports", status_code=302)
    
    # Validar existencia del reporte
    if not report:
        set_flash(response, "error", "Informe no encontrado")
        return response
    
    # Validar teléfono del cliente
    if not client_phone:
        set_flash(response, "warning", "El cliente no tiene teléfono registrado")
        return response
    
    # Enviar
    try:
        send_report(...)
        set_flash(response, "success", f"Informe enviado a {client_phone}")
    except Exception:
        set_flash(response, "error", "Error al enviar el informe")
    
    return response
```

## Rutas Implementadas

### Properties (`/properties`)
- ✅ **Crear propiedad**: Success al crear, error si falla
- ✅ **Actualizar propiedad**: Success al actualizar (diferencia entre precio y otros campos)
- ✅ **Archivar propiedad**: Success al archivar
- ✅ **Generar informe**: Success al generar, error si falla
- ✅ **Registrar visita**: Success al registrar
- ✅ **Crear interacción**: Success al crear actividad

### Reports (`/reports`)
- ✅ **Subir informe**: Success al subir, warning si falla WhatsApp
- ✅ **Enviar WhatsApp**: Success al enviar, error si no hay teléfono o falla
- ✅ **Descargar informe**: Error si no existe
- ✅ **Eliminar informe**: Success al eliminar, error si falla

## Personalización Visual

Los mensajes están en [base.html](backend/app/web/templates/base.html) líneas 28-95:

```html
<div class="flash-message bg-green-50 border-l-4 border-green-500 ...">
    <svg><!-- Icono --></svg>
    <p>{{ message }}</p>
    <button onclick="this.parentElement.remove()"><!-- X --></button>
</div>
```

## JavaScript

Auto-cierre después de 5 segundos:
```javascript
setTimeout(() => {
    const messages = document.querySelectorAll('.flash-message');
    messages.forEach(msg => {
        msg.style.opacity = '0';
        msg.style.transform = 'translateX(100%)';
        setTimeout(() => msg.remove(), 500);
    });
}, 5000);
```

## Middleware

El sistema utiliza dos componentes:

1. **FlashMiddleware** ([middleware/flash.py](backend/app/web/middleware/flash.py))
   - Lee la cookie `moyza_flash`
   - Decodifica los mensajes
   - Los expone en `request.state.flash_messages`
   - Elimina la cookie después de leerla

2. **set_flash()** ([utils/flash.py](backend/app/web/utils/flash.py))
   - Codifica el mensaje en base64
   - Lo almacena en una cookie con duración de 60 segundos
   - Solo se muestra una vez (one-time message)

## Notas Importantes

1. **Siempre crear el RedirectResponse primero**:
   ```python
   response = RedirectResponse(url="/...", status_code=302)
   set_flash(response, "success", "Mensaje")
   return response
   ```

2. **Los mensajes son temporales**: Se eliminan después de mostrarse una vez

3. **Múltiples mensajes**: Solo se muestra el último mensaje enviado (por diseño actual)

4. **Cookies httponly**: Los mensajes no son accesibles desde JavaScript del cliente

## Próximas Mejoras

- [ ] Soporte para múltiples mensajes simultáneos
- [ ] Posición configurable (top, bottom, center)
- [ ] Duración personalizable por mensaje
- [ ] Sonidos de notificación opcionales
- [ ] Persistencia en localStorage para mensajes importantes
