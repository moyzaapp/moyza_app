# Diseño del Flujo de Registro de Visitas con Validez Legal

## 1. ANÁLISIS DEL FLUJO ACTUAL

### Estado Actual
- **Modelo**: `PropertyVisit` con campos básicos (visitante, feedbacks, notas)
- **Flujo**: El asesor completa un formulario → Se guarda → Se genera PDF automáticamente
- **Problema**: No hay validación del cliente, no hay firma digital, no hay trazabilidad legal

### Problemas Identificados
1. ❌ El cliente NO ve el documento antes de ser generado
2. ❌ No hay aceptación explícita de términos
3. ❌ No hay firma digital capturada
4. ❌ No hay trazabilidad de la aceptación (IP, timestamp, evidencias)
5. ❌ El PDF se genera sin intervención del cliente
6. ❌ No cumple con estándares de validez legal/comercial

---

## 2. ANÁLISIS UX Y MEJORAS PROPUESTAS

### ✅ Flujo Propuesto (Validez Legal)

```
FASE 1: CAPTURA DE DATOS
├─ Asesor inicia registro de visita
├─ Selecciona propiedad
├─ Completa formulario con datos del cliente
│  ├─ Datos obligatorios: nombre, DNI, teléfono, email
│  ├─ Feedbacks de la visita
│  └─ Observaciones
└─ [CONTINUAR A VISTA PREVIA]

FASE 2: VISTA PREVIA Y ACEPTACIÓN
├─ Se muestra documento completo en pantalla
│  ├─ Formato similar al PDF final
│  ├─ Todos los datos ingresados visibles
│  ├─ Texto legal completo
│  └─ Autorización RGPD
├─ Cliente lee el contenido completo
├─ ☑️ Checkbox obligatorio: "He leído y acepto el tratamiento de datos personales"
└─ [CONTINUAR A FIRMA] (solo si acepta)

FASE 3: FIRMA DIGITAL
├─ Canvas de firma táctil/mouse
├─ Botones: [LIMPIAR] [CONFIRMAR FIRMA]
├─ Cliente firma en pantalla
├─ Se captura firma como imagen base64
└─ [FINALIZAR Y GUARDAR]

FASE 4: GENERACIÓN Y ENVÍO
├─ Se registra en DB:
│  ├─ Datos de la visita
│  ├─ Aceptación de términos (timestamp)
│  ├─ Firma digital (imagen)
│  ├─ Metadatos de auditoría (IP, user agent, timestamp)
├─ Se genera PDF final con:
│  ├─ Todos los datos
│  ├─ Firma del cliente incrustada
│  ├─ Pie de página con metadatos de validación
├─ Se envía por WhatsApp a cliente y agente
└─ ✅ COMPLETADO
```

### Mejoras UX
1. ✅ **Transparencia total**: El cliente ve exactamente qué va a firmar
2. ✅ **Consentimiento informado**: Lee y acepta explícitamente
3. ✅ **Control del cliente**: Puede revisar antes de firmar
4. ✅ **Validación progresiva**: No puede avanzar sin completar cada paso
5. ✅ **Feedback visual**: Cada fase tiene indicador de progreso
6. ✅ **Capacidad de corrección**: Puede limpiar y re-firmar

---

## 3. ESTRUCTURA DE BASE DE DATOS

### 3.1. Extensión del Modelo `PropertyVisit`

Agregar nuevos campos al modelo existente:

```python
# Nuevos campos para validez legal
data_consent_accepted = Column(Boolean, default=False, nullable=False)
data_consent_accepted_at = Column(DateTime, nullable=True)
data_consent_ip = Column(String, nullable=True)
data_consent_user_agent = Column(String, nullable=True)

# Firma digital
signature_data = Column(Text, nullable=True)  # Base64 de la imagen
signature_captured_at = Column(DateTime, nullable=True)
signature_ip = Column(String, nullable=True)

# Estado del proceso
visit_status = Column(String, default='draft', nullable=False)
# Estados: 'draft', 'preview', 'signed', 'completed'

# Metadatos de auditoría
audit_trail = Column(JSON, nullable=True)
# Estructura JSON con trazabilidad completa del proceso
```

### 3.2. Nueva Tabla `VisitAuditLog` (Opcional - Auditoría Detallada)

Para trazabilidad exhaustiva:

```python
class VisitAuditLog(Base):
    __tablename__ = "visit_audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("property_visits.id"), nullable=False)
    
    event_type = Column(String, nullable=False)
    # Tipos: 'created', 'preview_viewed', 'consent_accepted', 
    #        'signature_captured', 'pdf_generated', 'pdf_sent'
    
    event_data = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Relaciones
    visit = relationship("PropertyVisit", back_populates="audit_logs")
```

### 3.3. Tabla para OTP (Preparación Futura)

```python
class VisitOTPVerification(Base):
    __tablename__ = "visit_otp_verifications"
    
    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("property_visits.id"), nullable=False)
    
    phone_number = Column(String, nullable=False)
    otp_code = Column(String, nullable=False)  # Encriptado
    otp_sent_at = Column(DateTime, nullable=False)
    otp_verified_at = Column(DateTime, nullable=True)
    otp_expires_at = Column(DateTime, nullable=False)
    
    verification_method = Column(String, nullable=False)
    # Tipos: 'sms', 'whatsapp'
    
    status = Column(String, default='pending', nullable=False)
    # Estados: 'pending', 'verified', 'expired', 'failed'
    
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    
    # Relaciones
    visit = relationship("PropertyVisit", back_populates="otp_verifications")
```

---

## 4. ENDPOINTS FASTAPI

### 4.1. Endpoints del Nuevo Flujo

```python
# ============================================
# FASE 1: CREAR VISITA (DRAFT)
# ============================================
POST /api/visits/create-draft
Body: {
    property_id: int,
    visitor_name: str,
    dni: str,
    phone: str,
    email: str,
    interest_level: int,
    price_feedback: str,
    location_feedback: str,
    condition_feedback: str,
    lighting_feedback: str,
    elevator_feedback: str,
    garage_feedback: str,
    notes: str
}
Response: {
    visit_id: int,
    status: 'draft',
    redirect_url: '/visits/preview/{visit_id}'
}

# ============================================
# FASE 2: VISTA PREVIA DEL DOCUMENTO
# ============================================
GET /visits/preview/{visit_id}
Response: HTML con vista previa del documento completo
Features:
- Muestra todos los datos formateados
- Incluye texto legal completo
- Checkbox de aceptación RGPD
- Botón "Continuar a Firma" (deshabilitado hasta aceptar)

# ============================================
# FASE 2.5: REGISTRAR ACEPTACIÓN DE TÉRMINOS
# ============================================
POST /api/visits/{visit_id}/accept-terms
Body: {
    accepted: bool,
    ip_address: str (capturado en backend),
    user_agent: str (capturado en backend)
}
Response: {
    success: bool,
    redirect_url: '/visits/signature/{visit_id}'
}

# ============================================
# FASE 3: PÁGINA DE FIRMA
# ============================================
GET /visits/signature/{visit_id}
Response: HTML con canvas de firma
Features:
- Canvas HTML5 para firma táctil/mouse
- Botones: Limpiar, Confirmar
- Validación: no puede confirmar si canvas vacío

# ============================================
# FASE 3.5: GUARDAR FIRMA
# ============================================
POST /api/visits/{visit_id}/save-signature
Body: {
    signature_data: str (base64 de la imagen PNG),
    ip_address: str,
    user_agent: str
}
Response: {
    success: bool,
    redirect_url: '/visits/complete/{visit_id}'
}

# ============================================
# FASE 4: FINALIZAR Y GENERAR PDF
# ============================================
POST /api/visits/{visit_id}/finalize
Response: {
    success: bool,
    pdf_generated: bool,
    pdf_sent: bool,
    visit_sheet_url: str,
    redirect_url: '/properties/{property_id}'
}
Features:
- Cambia estado a 'completed'
- Genera PDF con firma incrustada
- Envía por WhatsApp
- Registra auditoría completa

# ============================================
# ENDPOINTS DE UTILIDAD
# ============================================
GET /api/visits/{visit_id}/preview-data
Response: JSON con todos los datos formateados para vista previa

GET /api/visits/{visit_id}/audit-trail
Response: JSON con historial completo de auditoría
```

### 4.2. Estructura de Rutas Web

```
/visits/select-property         → Seleccionar propiedad
/visits/new/{property_id}       → Formulario de datos (Fase 1)
/visits/preview/{visit_id}      → Vista previa documento (Fase 2)
/visits/signature/{visit_id}    → Canvas de firma (Fase 3)
/visits/complete/{visit_id}     → Confirmación final (Fase 4)
/visits/{visit_id}/download     → Descargar PDF (existente)
```

---

## 5. DISEÑO DE INTERFAZ DE USUARIO

### 5.1. Componente: Vista Previa del Documento

```html
<div class="document-preview-container">
    <!-- Header con progreso -->
    <div class="progress-indicator">
        <div class="step completed">✓ Datos</div>
        <div class="step active">Vista Previa</div>
        <div class="step">Firma</div>
        <div class="step">Finalizado</div>
    </div>
    
    <!-- Documento simulado (estilo papel) -->
    <div class="document-paper">
        <!-- Logo MOYZA -->
        <img src="/static/logo_moyza.png" class="logo">
        
        <h1>FICHA DE VISITA INMOBILIARIA MOYZA</h1>
        
        <section class="section">
            <h2>DATOS DEL COMPRADOR</h2>
            <table>
                <tr><td>Nombre:</td><td>{{ visitor_name }}</td></tr>
                <tr><td>DNI:</td><td>{{ dni }}</td></tr>
                <tr><td>Teléfono:</td><td>{{ phone }}</td></tr>
                <tr><td>E-mail:</td><td>{{ email }}</td></tr>
            </table>
        </section>
        
        <section class="section">
            <h2>DATOS DEL INMUEBLE VISITADO</h2>
            <!-- ... datos de la propiedad ... -->
        </section>
        
        <section class="section">
            <h2>FEEDBACK DE LA VISITA</h2>
            <!-- ... feedbacks ... -->
        </section>
        
        <section class="legal-text">
            <h2>TÉRMINOS Y CONDICIONES</h2>
            <p><!-- Texto legal completo --></p>
        </section>
        
        <section class="rgpd-section">
            <h2>AUTORIZACIÓN RGPD</h2>
            <p><!-- Texto RGPD completo --></p>
        </section>
    </div>
    
    <!-- Área de aceptación -->
    <div class="acceptance-area">
        <label class="checkbox-large">
            <input type="checkbox" id="rgpd-acceptance" required>
            <span>
                He leído y acepto el contenido del documento, 
                incluyendo la autorización para el tratamiento 
                de mis datos personales conforme al RGPD
            </span>
        </label>
        
        <div class="button-container">
            <button class="btn-secondary" onclick="history.back()">
                ← Volver a Editar
            </button>
            <button class="btn-primary" id="continue-to-signature" disabled>
                Continuar a Firma →
            </button>
        </div>
    </div>
</div>

<style>
.document-paper {
    background: white;
    padding: 40px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
    max-width: 800px;
    margin: 20px auto;
    border: 1px solid #ddd;
    font-family: 'Helvetica', sans-serif;
}

.acceptance-area {
    max-width: 800px;
    margin: 30px auto;
    padding: 20px;
    background: #f9fafb;
    border-radius: 12px;
}

.checkbox-large {
    display: flex;
    gap: 12px;
    font-size: 16px;
    cursor: pointer;
    align-items: flex-start;
}

.checkbox-large input[type="checkbox"] {
    width: 24px;
    height: 24px;
    margin-top: 2px;
    flex-shrink: 0;
}
</style>

<script>
const checkbox = document.getElementById('rgpd-acceptance');
const continueBtn = document.getElementById('continue-to-signature');

checkbox.addEventListener('change', function() {
    continueBtn.disabled = !this.checked;
});

continueBtn.addEventListener('click', async function() {
    const visitId = {{ visit.id }};
    
    // Registrar aceptación en backend
    const response = await fetch(`/api/visits/${visitId}/accept-terms`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            accepted: true,
            timestamp: new Date().toISOString()
        })
    });
    
    if (response.ok) {
        const data = await response.json();
        window.location.href = data.redirect_url;
    }
});
</script>
```

### 5.2. Componente: Canvas de Firma Digital

```html
<div class="signature-container">
    <!-- Header con progreso -->
    <div class="progress-indicator">
        <div class="step completed">✓ Datos</div>
        <div class="step completed">✓ Vista Previa</div>
        <div class="step active">Firma</div>
        <div class="step">Finalizado</div>
    </div>
    
    <div class="signature-card">
        <h2>Firma del Cliente</h2>
        <p class="instruction">
            Por favor, firme en el recuadro inferior utilizando su dedo (en pantalla táctil) 
            o el mouse. La firma será incluida en el documento oficial de visita.
        </p>
        
        <!-- Canvas de firma -->
        <div class="canvas-wrapper">
            <canvas id="signature-canvas" width="600" height="200"></canvas>
        </div>
        
        <!-- Vista previa de la firma -->
        <div id="signature-preview" class="signature-preview hidden">
            <h3>Vista previa de su firma:</h3>
            <img id="signature-image" src="" alt="Firma">
        </div>
        
        <!-- Botones de acción -->
        <div class="button-container">
            <button class="btn-secondary" id="clear-signature">
                🗑️ Limpiar
            </button>
            <button class="btn-primary" id="confirm-signature" disabled>
                ✓ Confirmar Firma
            </button>
        </div>
    </div>
</div>

<style>
.signature-card {
    max-width: 700px;
    margin: 30px auto;
    padding: 30px;
    background: white;
    border-radius: 16px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
}

.canvas-wrapper {
    border: 2px solid #e5e7eb;
    border-radius: 8px;
    background: white;
    margin: 20px 0;
    cursor: crosshair;
}

#signature-canvas {
    display: block;
    touch-action: none;
}

.signature-preview {
    margin-top: 20px;
    padding: 20px;
    background: #f9fafb;
    border-radius: 8px;
}

.signature-preview img {
    max-width: 100%;
    border: 1px solid #ddd;
    background: white;
    padding: 10px;
}
</style>

<script>
// ============================================
// SIGNATURE PAD IMPLEMENTATION
// ============================================
const canvas = document.getElementById('signature-canvas');
const ctx = canvas.getContext('2d');
const clearBtn = document.getElementById('clear-signature');
const confirmBtn = document.getElementById('confirm-signature');
const previewDiv = document.getElementById('signature-preview');
const previewImg = document.getElementById('signature-image');

let isDrawing = false;
let hasDrawn = false;

// Configurar canvas
ctx.strokeStyle = '#000';
ctx.lineWidth = 2;
ctx.lineCap = 'round';
ctx.lineJoin = 'round';

// Eventos de dibujo (mouse)
canvas.addEventListener('mousedown', startDrawing);
canvas.addEventListener('mousemove', draw);
canvas.addEventListener('mouseup', stopDrawing);
canvas.addEventListener('mouseout', stopDrawing);

// Eventos de dibujo (touch)
canvas.addEventListener('touchstart', handleTouchStart, {passive: false});
canvas.addEventListener('touchmove', handleTouchMove, {passive: false});
canvas.addEventListener('touchend', stopDrawing);

function startDrawing(e) {
    isDrawing = true;
    const pos = getPosition(e);
    ctx.beginPath();
    ctx.moveTo(pos.x, pos.y);
}

function draw(e) {
    if (!isDrawing) return;
    
    e.preventDefault();
    const pos = getPosition(e);
    ctx.lineTo(pos.x, pos.y);
    ctx.stroke();
    
    hasDrawn = true;
    confirmBtn.disabled = false;
}

function stopDrawing() {
    isDrawing = false;
}

function getPosition(e) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    
    return {
        x: (e.clientX - rect.left) * scaleX,
        y: (e.clientY - rect.top) * scaleY
    };
}

function handleTouchStart(e) {
    e.preventDefault();
    const touch = e.touches[0];
    const mouseEvent = new MouseEvent('mousedown', {
        clientX: touch.clientX,
        clientY: touch.clientY
    });
    canvas.dispatchEvent(mouseEvent);
}

function handleTouchMove(e) {
    e.preventDefault();
    const touch = e.touches[0];
    const mouseEvent = new MouseEvent('mousemove', {
        clientX: touch.clientX,
        clientY: touch.clientY
    });
    canvas.dispatchEvent(mouseEvent);
}

// Limpiar canvas
clearBtn.addEventListener('click', function() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    hasDrawn = false;
    confirmBtn.disabled = true;
    previewDiv.classList.add('hidden');
});

// Confirmar firma
confirmBtn.addEventListener('click', async function() {
    if (!hasDrawn) {
        alert('Por favor, firme antes de continuar');
        return;
    }
    
    // Convertir canvas a base64
    const signatureData = canvas.toDataURL('image/png');
    
    // Mostrar vista previa
    previewImg.src = signatureData;
    previewDiv.classList.remove('hidden');
    
    // Enviar al backend
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Guardando firma...';
    
    try {
        const visitId = {{ visit.id }};
        const response = await fetch(`/api/visits/${visitId}/save-signature`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                signature_data: signatureData
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            
            // Esperar 1 segundo para que vea la vista previa
            setTimeout(() => {
                window.location.href = data.redirect_url;
            }, 1000);
        } else {
            alert('Error al guardar la firma. Inténtelo de nuevo.');
            confirmBtn.disabled = false;
            confirmBtn.textContent = '✓ Confirmar Firma';
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Error de conexión. Verifique su internet.');
        confirmBtn.disabled = false;
        confirmBtn.textContent = '✓ Confirmar Firma';
    }
});
</script>
```

### 5.3. Página de Confirmación Final

```html
<div class="completion-container">
    <div class="success-card">
        <div class="success-icon">✓</div>
        <h1>¡Visita Registrada Exitosamente!</h1>
        
        <p class="success-message">
            El documento de visita ha sido generado y enviado por WhatsApp 
            al cliente y al agente inmobiliario.
        </p>
        
        <div class="document-info">
            <h3>Documento generado:</h3>
            <div class="file-card">
                <span class="file-icon">📄</span>
                <span class="file-name">{{ visit_sheet_filename }}</span>
                <a href="/visits/{{ visit.id }}/download" class="btn-download">
                    Descargar PDF
                </a>
            </div>
        </div>
        
        <div class="sent-to-info">
            <h3>Enviado a:</h3>
            <ul>
                <li>✓ Cliente: {{ visit.phone }}</li>
                <li>✓ Agente: {{ agent.phone }}</li>
            </ul>
        </div>
        
        <div class="button-container">
            <a href="/properties/{{ property.id }}" class="btn-secondary">
                ← Volver a la Propiedad
            </a>
            <a href="/visits/select-property" class="btn-primary">
                Registrar Otra Visita
            </a>
        </div>
    </div>
</div>
```

---

## 6. ALMACENAMIENTO DE FIRMA

### 6.1. Opción Recomendada: Base64 en Base de Datos

**Ventajas:**
- ✅ Simplicidad de implementación
- ✅ No requiere gestión de archivos adicionales
- ✅ Respaldo automático con backup de DB
- ✅ Fácil de incluir en PDF (ya está en formato imagen)
- ✅ No hay riesgo de pérdida de archivos

**Desventajas:**
- ⚠️ Aumenta tamaño de DB (estimado: 5-15 KB por firma)
- ⚠️ Ligeramente más lento para queries grandes

**Implementación:**
```python
# En PropertyVisit
signature_data = Column(Text, nullable=True)
# Almacena: "data:image/png;base64,iVBORw0KGgoAAAA..."

# Para guardar:
visit.signature_data = request_data['signature_data']  # Ya viene en base64 del canvas

# Para usar en PDF:
from reportlab.platypus import Image
from io import BytesIO
import base64

# Extraer datos base64
signature_base64 = visit.signature_data.split(',')[1]
signature_bytes = base64.b64decode(signature_base64)
signature_image = Image(BytesIO(signature_bytes))
signature_image.drawHeight = 50
signature_image.drawWidth = 150
```

### 6.2. Opción Alternativa: Archivo en Disco

**Ventajas:**
- ✅ DB más ligera
- ✅ Mejor para queries masivos

**Desventajas:**
- ⚠️ Requiere gestión de archivos
- ⚠️ Riesgo de pérdida de sincronización
- ⚠️ Requiere backup adicional de carpeta

**Implementación:**
```python
# En PropertyVisit
signature_filename = Column(String, nullable=True)
signature_filepath = Column(String, nullable=True)

# Para guardar:
signature_base64 = request_data['signature_data'].split(',')[1]
signature_bytes = base64.b64decode(signature_base64)

signatures_dir = Path("storage/signatures")
signatures_dir.mkdir(parents=True, exist_ok=True)

filename = f"signature_{visit_id}_{uuid4().hex[:8]}.png"
filepath = signatures_dir / filename

with open(filepath, 'wb') as f:
    f.write(signature_bytes)

visit.signature_filename = filename
visit.signature_filepath = str(filepath)
```

**Recomendación:** Usar **Base64 en DB** por simplicidad y confiabilidad.

---

## 7. GENERACIÓN DE PDF CON FIRMA

### 7.1. Modificación del Generador Actual

```python
def generate_visit_sheet_with_signature(
    property_item,
    visit,
    agent,
    output_path
):
    """
    Genera la Ficha de Visita con FIRMA DIGITAL incrustada
    """
    
    # ... código existente hasta la sección de FIRMAS ...
    
    # =========================
    # FIRMAS CON FIRMA DIGITAL
    # =========================
    
    # Crear tabla de firmas con imagen de firma del cliente
    signature_data = []
    
    # Fila 1: Espaciado
    signature_data.append(["", "", "", "", "", ""])
    
    # Fila 2: Etiquetas
    signature_data.append(["", "COMPRADOR", "", "", "AGENTE INMOBILIARIO", ""])
    
    # Fila 3: Imagen de firma (si existe)
    if visit.signature_data:
        # Decodificar firma base64
        signature_base64 = visit.signature_data.split(',')[1]
        signature_bytes = base64.b64decode(signature_base64)
        
        # Crear imagen desde bytes
        signature_img = Image(BytesIO(signature_bytes))
        signature_img.drawHeight = 40
        signature_img.drawWidth = 140
        
        # Fila con la firma
        signature_data.append(["", signature_img, "", "", "", ""])
    else:
        # Fila vacía si no hay firma
        signature_data.append(["", "", "", "", "", ""])
    
    # Fila 4: Línea de firma
    signature_data.append(["", "", "", "", "", ""])
    
    # Fila 5: Metadatos de firma
    if visit.signature_captured_at:
        signature_date = visit.signature_captured_at.strftime("%d/%m/%Y %H:%M")
        signature_data.append([
            "", 
            f"Firmado digitalmente el {signature_date}", 
            "", 
            "", 
            "", 
            ""
        ])
    
    signature_table = Table(
        signature_data,
        colWidths=[40, 155, 40, 40, 155, 40],
        rowHeights=[15, 15, 50, 5, 15]
    )
    
    signature_table.setStyle(
        TableStyle([
            ("FONTNAME", (1, 1), (1, 1), "Helvetica-Bold"),
            ("FONTNAME", (4, 1), (4, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ALIGN", (1, 0), (1, -1), "CENTER"),
            ("ALIGN", (4, 0), (4, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            # Línea de firma para comprador
            ("LINEABOVE", (1, 3), (1, 3), 1, colors.black),
            # Línea de firma para agente
            ("LINEABOVE", (4, 3), (4, 3), 1, colors.black),
            ("GRID", (0, 0), (-1, -1), 0, colors.white),
        ])
    )
    
    elements.append(signature_table)
    
    # =========================
    # PIE DE PÁGINA CON METADATOS DE VALIDACIÓN
    # =========================
    
    elements.append(Spacer(1, 20))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CCCCCC")))
    elements.append(Spacer(1, 10))
    
    validation_metadata = f"""
    <b>METADATOS DE VALIDACIÓN LEGAL</b><br/>
    Documento generado electrónicamente el {datetime.utcnow().strftime("%d/%m/%Y a las %H:%M UTC")}<br/>
    """
    
    if visit.data_consent_accepted_at:
        consent_date = visit.data_consent_accepted_at.strftime("%d/%m/%Y %H:%M")
        validation_metadata += f"Consentimiento RGPD aceptado el {consent_date}<br/>"
    
    if visit.signature_captured_at:
        sig_date = visit.signature_captured_at.strftime("%d/%m/%Y %H:%M")
        validation_metadata += f"Firma digital capturada el {sig_date}<br/>"
    
    if visit.data_consent_ip:
        # Ofuscar IP por privacidad (mostrar solo primeros 2 octetos)
        ip_parts = visit.data_consent_ip.split('.')
        if len(ip_parts) == 4:
            ip_masked = f"{ip_parts[0]}.{ip_parts[1]}.xxx.xxx"
            validation_metadata += f"IP de validación: {ip_masked}<br/>"
    
    validation_metadata += f"ID de documento: MOYZA-VISIT-{visit.id}-{property_item.id}<br/>"
    
    validation_style = ParagraphStyle(
        "ValidationStyle",
        parent=styles["BodyText"],
        fontSize=7,
        leading=10,
        textColor=colors.HexColor("#666666"),
        alignment=TA_LEFT,
    )
    
    elements.append(Paragraph(validation_metadata, validation_style))
    
    # ... continuar con el build del PDF ...
    
    doc.build(elements)
    return output_path
```

### 7.2. Ejemplo Visual de PDF con Firma

```
┌─────────────────────────────────────────────────────────┐
│                    [LOGO MOYZA]                         │
│         FICHA DE VISITA INMOBILIARIA MOYZA              │
│                                                         │
│ FECHA: 15/06/2026                                       │
│ DIRECCIÓN: Calle Ejemplo 123, Jaén                     │
│                                                         │
│ DATOS DEL COMPRADOR                                     │
│ ├─ Nombre: Juan Pérez García                           │
│ ├─ DNI: 12345678A                                       │
│ ├─ Teléfono: +34 600 123 456                           │
│ └─ E-mail: juan@ejemplo.com                            │
│                                                         │
│ ... [más secciones] ...                                 │
│                                                         │
│ ┌─────────────────────┐     ┌─────────────────────┐   │
│ │     COMPRADOR       │     │ AGENTE INMOBILIARIO │   │
│ │                     │     │                     │   │
│ │  [FIRMA DIGITAL]    │     │                     │   │
│ │   ~~~~~~~~~~~       │     │                     │   │
│ │  Juan Pérez         │     │                     │   │
│ │ ─────────────────── │     │ ─────────────────── │   │
│ │ Firmado: 15/06/2026 │     │                     │   │
│ │ a las 14:30         │     │                     │   │
│ └─────────────────────┘     └─────────────────────┘   │
│                                                         │
│ ─────────────────────────────────────────────────────  │
│ METADATOS DE VALIDACIÓN LEGAL                          │
│ Documento generado: 15/06/2026 14:35 UTC              │
│ Consentimiento RGPD: 15/06/2026 14:28                 │
│ Firma digital capturada: 15/06/2026 14:30             │
│ IP de validación: 192.168.xxx.xxx                     │
│ ID de documento: MOYZA-VISIT-1234-5678                │
└─────────────────────────────────────────────────────────┘
```

---

## 8. ARQUITECTURA EXTENSIBLE PARA OTP

### 8.1. Preparación del Diseño

El diseño actual ya está preparado para agregar OTP sin reescribir, mediante:

1. **Estado de visita**: Campo `visit_status` permite agregar estado `'pending_otp'`
2. **Tabla OTP**: Ya diseñada (ver sección 3.3)
3. **Audit trail**: Registra todos los pasos del proceso

### 8.2. Flujo Futuro con OTP (No Implementar Aún)

```
FLUJO ACTUAL                   FLUJO CON OTP (FUTURO)
═══════════════════           ═══════════════════════════
1. Datos                      1. Datos
2. Vista previa               2. Vista previa
3. Firma                      3. Firma
4. Finalizar                  4. [NUEVO] Enviar OTP
                              5. [NUEVO] Verificar OTP
                              6. Finalizar
```

### 8.3. Endpoints OTP (Diseño Futuro)

```python
# Enviar código OTP
POST /api/visits/{visit_id}/send-otp
Body: {
    phone: str,
    method: 'sms' | 'whatsapp'
}
Response: {
    otp_sent: bool,
    expires_at: datetime,
    verification_id: int
}

# Verificar código OTP
POST /api/visits/{visit_id}/verify-otp
Body: {
    verification_id: int,
    otp_code: str
}
Response: {
    verified: bool,
    redirect_url: str
}
```

### 8.4. Integración con Proveedor SMS/WhatsApp

**Opciones de Proveedores:**
- **Twilio**: SMS + WhatsApp (más confiable, $$$)
- **Vonage (Nexmo)**: SMS (balance precio/calidad)
- **WhatsApp Business API**: Requiere cuenta business verificada
- **AWS SNS**: SMS económico pero solo SMS

**Implementación futura (ejemplo con Twilio):**

```python
from twilio.rest import Client

def send_otp_code(phone: str, otp_code: str, method: str = 'sms'):
    """
    Envía código OTP por SMS o WhatsApp
    """
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    
    message = f"Tu código de verificación MOYZA es: {otp_code}. Válido por 10 minutos."
    
    if method == 'whatsapp':
        from_number = f"whatsapp:{settings.TWILIO_WHATSAPP_NUMBER}"
        to_number = f"whatsapp:{phone}"
    else:
        from_number = settings.TWILIO_PHONE_NUMBER
        to_number = phone
    
    message_response = client.messages.create(
        body=message,
        from_=from_number,
        to=to_number
    )
    
    return message_response.sid
```

### 8.5. Lógica de Generación y Validación OTP

```python
import secrets
import hashlib
from datetime import datetime, timedelta

def generate_otp_code() -> str:
    """
    Genera código OTP de 6 dígitos
    """
    return ''.join([str(secrets.randbelow(10)) for _ in range(6)])

def hash_otp_code(otp_code: str) -> str:
    """
    Hash seguro del código OTP para almacenamiento
    """
    return hashlib.sha256(otp_code.encode()).hexdigest()

def verify_otp_code(stored_hash: str, input_code: str) -> bool:
    """
    Verifica código OTP contra hash almacenado
    """
    input_hash = hash_otp_code(input_code)
    return secrets.compare_digest(stored_hash, input_hash)

# Uso en endpoint
def send_otp(visit_id: int, phone: str, method: str):
    otp_code = generate_otp_code()
    otp_hash = hash_otp_code(otp_code)
    
    otp_verification = VisitOTPVerification(
        visit_id=visit_id,
        phone_number=phone,
        otp_code=otp_hash,  # Almacenar solo hash
        otp_sent_at=datetime.utcnow(),
        otp_expires_at=datetime.utcnow() + timedelta(minutes=10),
        verification_method=method,
        status='pending'
    )
    
    db.add(otp_verification)
    db.commit()
    
    # Enviar código real al cliente
    send_otp_code(phone, otp_code, method)
    
    return otp_verification
```

---

## 9. MIGRACIÓN DE BASE DE DATOS

### 9.1. Script de Migración Alembic

```python
"""add_legal_visit_fields

Revision ID: abc123def456
Revises: previous_revision
Create Date: 2026-06-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'abc123def456'
down_revision = 'previous_revision'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar campos de consentimiento
    op.add_column('property_visits', 
        sa.Column('data_consent_accepted', sa.Boolean(), 
                  nullable=False, server_default='false'))
    op.add_column('property_visits', 
        sa.Column('data_consent_accepted_at', sa.DateTime(), nullable=True))
    op.add_column('property_visits', 
        sa.Column('data_consent_ip', sa.String(), nullable=True))
    op.add_column('property_visits', 
        sa.Column('data_consent_user_agent', sa.String(), nullable=True))
    
    # Agregar campos de firma
    op.add_column('property_visits', 
        sa.Column('signature_data', sa.Text(), nullable=True))
    op.add_column('property_visits', 
        sa.Column('signature_captured_at', sa.DateTime(), nullable=True))
    op.add_column('property_visits', 
        sa.Column('signature_ip', sa.String(), nullable=True))
    
    # Agregar campo de estado
    op.add_column('property_visits', 
        sa.Column('visit_status', sa.String(), 
                  nullable=False, server_default='completed'))
    
    # Agregar audit trail
    op.add_column('property_visits', 
        sa.Column('audit_trail', postgresql.JSON(astext_type=sa.Text()), 
                  nullable=True))
    
    # Crear tabla de audit logs (opcional)
    op.create_table('visit_audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('visit_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('event_data', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('ip_address', sa.String(), nullable=True),
        sa.Column('user_agent', sa.String(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['visit_id'], ['property_visits.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_visit_audit_logs_id'), 'visit_audit_logs', ['id'])
    op.create_index(op.f('ix_visit_audit_logs_visit_id'), 'visit_audit_logs', ['visit_id'])
    
    # Crear tabla OTP (preparación futura)
    op.create_table('visit_otp_verifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('visit_id', sa.Integer(), nullable=False),
        sa.Column('phone_number', sa.String(), nullable=False),
        sa.Column('otp_code', sa.String(), nullable=False),
        sa.Column('otp_sent_at', sa.DateTime(), nullable=False),
        sa.Column('otp_verified_at', sa.DateTime(), nullable=True),
        sa.Column('otp_expires_at', sa.DateTime(), nullable=False),
        sa.Column('verification_method', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.ForeignKeyConstraint(['visit_id'], ['property_visits.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_visit_otp_verifications_id'), 
                    'visit_otp_verifications', ['id'])


def downgrade():
    # Eliminar tablas
    op.drop_index(op.f('ix_visit_otp_verifications_id'), 
                  table_name='visit_otp_verifications')
    op.drop_table('visit_otp_verifications')
    
    op.drop_index(op.f('ix_visit_audit_logs_visit_id'), 
                  table_name='visit_audit_logs')
    op.drop_index(op.f('ix_visit_audit_logs_id'), 
                  table_name='visit_audit_logs')
    op.drop_table('visit_audit_logs')
    
    # Eliminar columnas
    op.drop_column('property_visits', 'audit_trail')
    op.drop_column('property_visits', 'visit_status')
    op.drop_column('property_visits', 'signature_ip')
    op.drop_column('property_visits', 'signature_captured_at')
    op.drop_column('property_visits', 'signature_data')
    op.drop_column('property_visits', 'data_consent_user_agent')
    op.drop_column('property_visits', 'data_consent_ip')
    op.drop_column('property_visits', 'data_consent_accepted_at')
    op.drop_column('property_visits', 'data_consent_accepted')
```

---

## 10. CONSIDERACIONES DE SEGURIDAD

### 10.1. Protección de Datos Personales (RGPD)

✅ **Cumplimiento RGPD:**
1. Consentimiento explícito antes de procesar datos
2. Derecho al olvido: endpoint para eliminar visita + datos
3. Minimización de datos: solo capturar lo necesario
4. Cifrado en tránsito (HTTPS obligatorio)
5. Ofuscación de IPs en documentos públicos
6. Retención limitada: definir política de borrado (ej: 2 años)

### 10.2. Seguridad de Firmas Digitales

✅ **Medidas de seguridad:**
1. Firma no modificable una vez guardada (inmutable)
2. Timestamp criptográfico del momento de firma
3. Hash del documento en audit trail
4. Validación de que canvas no está vacío
5. Rate limiting en endpoints de firma

### 10.3. Prevención de Fraude

```python
def validate_signature_not_empty(signature_base64: str) -> bool:
    """
    Valida que la firma no sea un canvas vacío o casi vacío
    """
    # Decodificar imagen
    img_data = signature_base64.split(',')[1]
    img_bytes = base64.b64decode(img_data)
    
    # Verificar tamaño mínimo (una firma real tiene varios KB)
    if len(img_bytes) < 500:  # Menos de 500 bytes = probablemente vacío
        return False
    
    # Opcionalmente: usar Pillow para verificar que no sea todo blanco
    from PIL import Image
    from io import BytesIO
    
    img = Image.open(BytesIO(img_bytes))
    
    # Convertir a escala de grises y verificar varianza
    grayscale = img.convert('L')
    pixels = list(grayscale.getdata())
    
    # Calcular varianza de píxeles
    mean = sum(pixels) / len(pixels)
    variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
    
    # Si varianza muy baja = canvas vacío o casi vacío
    return variance > 100  # Ajustar threshold según pruebas
```

### 10.4. Auditoría y Trazabilidad

```python
def create_audit_log(
    visit_id: int,
    event_type: str,
    event_data: dict,
    db: Session,
    request: Request
):
    """
    Registra evento en audit log
    """
    audit_log = VisitAuditLog(
        visit_id=visit_id,
        event_type=event_type,
        event_data=event_data,
        timestamp=datetime.utcnow(),
        ip_address=request.client.host,
        user_agent=request.headers.get('user-agent'),
        user_id=request.state.user.id if hasattr(request.state, 'user') else None
    )
    
    db.add(audit_log)
    db.commit()

# Uso:
create_audit_log(
    visit_id=visit.id,
    event_type='signature_captured',
    event_data={
        'signature_size_bytes': len(signature_bytes),
        'signature_timestamp': datetime.utcnow().isoformat()
    },
    db=db,
    request=request
)
```

---

## 11. TESTING

### 11.1. Tests Unitarios Críticos

```python
# tests/test_visit_legal_flow.py

def test_create_draft_visit():
    """Verifica creación de visita en estado draft"""
    pass

def test_cannot_accept_terms_without_draft():
    """Verifica que no se puede aceptar términos sin visita draft"""
    pass

def test_accept_terms_records_metadata():
    """Verifica que aceptación registra IP y timestamp"""
    pass

def test_signature_validation_rejects_empty():
    """Verifica que no se acepta firma vacía"""
    pass

def test_signature_saved_as_base64():
    """Verifica que firma se guarda correctamente en base64"""
    pass

def test_pdf_includes_signature():
    """Verifica que PDF generado incluye la firma"""
    pass

def test_audit_trail_complete():
    """Verifica que audit trail registra todos los pasos"""
    pass

def test_visit_status_progression():
    """Verifica que status progresa: draft → preview → signed → completed"""
    pass
```

### 11.2. Tests de Integración

```python
def test_full_legal_visit_flow():
    """
    Test end-to-end del flujo completo:
    1. Crear draft
    2. Aceptar términos
    3. Capturar firma
    4. Finalizar y generar PDF
    5. Verificar PDF contiene firma
    6. Verificar auditoría completa
    """
    pass
```

---

## 12. ESTIMACIÓN DE ESFUERZO

### 12.1. Desglose de Tareas

| Tarea | Complejidad | Tiempo Est. |
|-------|-------------|-------------|
| Migración DB + Modelos | Media | 2-3 horas |
| Endpoint: create-draft | Baja | 1 hora |
| Vista: preview document | Media | 3-4 horas |
| Endpoint: accept-terms | Baja | 1 hora |
| Vista: signature canvas | Alta | 4-5 horas |
| Endpoint: save-signature | Media | 2 horas |
| Endpoint: finalize | Media | 2 horas |
| Modificar PDF generator | Alta | 3-4 horas |
| Audit logs | Media | 2 horas |
| Testing | Alta | 4-5 horas |
| Documentación | Baja | 1 hora |
| **TOTAL** | | **25-32 horas** |

### 12.2. Fases de Implementación

**FASE 1 (MVP Legal)** - Prioridad Alta:
- ✅ Migración DB
- ✅ Flujo draft → preview → signature → complete
- ✅ PDF con firma
- ✅ Auditoría básica

**FASE 2 (Mejoras)** - Prioridad Media:
- Validación avanzada de firmas
- UI mejorada con animaciones
- Mejor manejo de errores
- Tests exhaustivos

**FASE 3 (OTP)** - Futuro:
- Integración con proveedor SMS/WhatsApp
- Lógica de OTP
- Doble factor de autenticación

---

## 13. RECOMENDACIONES FINALES

### 13.1. Mejores Prácticas

✅ **Hacer:**
1. Implementar el flujo paso a paso, probando cada fase
2. Usar transacciones DB para garantizar consistencia
3. Capturar todos los errores y mostrar mensajes claros al usuario
4. Hacer backup de DB antes de migración
5. Testear en dispositivos móviles (el canvas táctil es crítico)
6. Documentar el proceso en manuales de usuario

❌ **Evitar:**
1. Permitir saltar pasos del flujo (validar en backend)
2. Guardar firmas sin validación
3. Generar PDF antes de completar el flujo
4. Exponer IPs completas en documentos públicos
5. Permitir modificar visitas después de firmadas

### 13.2. Validez Legal

Para máxima validez legal, considerar:

1. **Añadir cláusula explícita** en el texto legal que indique:
   > "La firma digital capturada mediante dispositivo electrónico tiene 
   > plena validez conforme a la Ley 6/2020 reguladora de determinados 
   > aspectos de los servicios electrónicos de confianza."

2. **Timestamp certificado** (opcional, para máxima garantía):
   - Integrar con TSA (Time Stamping Authority)
   - Ej: servicio de sellado de tiempo de FNMT (España)

3. **Conservación de evidencias**:
   - Guardar audit logs al menos 5 años
   - Realizar backups regulares cifrados
   - Considerar almacenamiento en cloud inmutable (S3 con versioning)

4. **Política de privacidad actualizada**:
   - Añadir sección sobre firma digital
   - Explicar cómo se procesan y almacenan las firmas
   - Publicar en website de MOYZA

### 13.3. Cumplimiento Normativo

📋 **Checklist de Cumplimiento:**
- [ ] RGPD: Consentimiento explícito ✅
- [ ] RGPD: Derecho de acceso (endpoint para ver datos) ✅
- [ ] RGPD: Derecho al olvido (endpoint para eliminar) ⚠️ Por implementar
- [ ] LOPD: Registro de actividades de tratamiento ⚠️ Documentar
- [ ] eIDAS: Firma electrónica avanzada ✅ (Canvas capture)
- [ ] Ley 6/2020: Servicios electrónicos de confianza ✅

---

## 14. PRÓXIMOS PASOS

### 14.1. Plan de Acción Inmediato

1. **Revisar y aprobar** este diseño
2. **Priorizar** qué partes implementar primero
3. **Crear migración** de base de datos
4. **Implementar** Fase 1 (MVP Legal)
5. **Testear** en entorno de desarrollo
6. **Desplegar** en producción con feature flag
7. **Monitorear** y recoger feedback
8. **Iterar** con mejoras

### 14.2. Preguntas para Decidir

Antes de implementar, necesito tu feedback sobre:

1. ¿Apruebas el flujo propuesto de 4 fases?
2. ¿Prefieres base64 en DB o archivos en disco para las firmas?
3. ¿Quieres implementar audit logs en tabla separada o solo en JSON?
4. ¿Necesitas la funcionalidad OTP inmediatamente o puede ser fase 2?
5. ¿Hay algún requisito legal adicional específico de tu jurisdicción?
6. ¿El asesor debe poder "revisar y aprobar" antes de enviar, o el flujo debe ser directo después de la firma del cliente?

---

## 15. CONCLUSIÓN

Este diseño proporciona:

✅ **Validez comercial y legal**: Firma digital, consentimiento explícito, trazabilidad  
✅ **Experiencia de usuario clara**: Flujo guiado paso a paso  
✅ **Transparencia total**: Cliente ve todo antes de firmar  
✅ **Arquitectura extensible**: Preparado para OTP sin reescritura  
✅ **Cumplimiento RGPD**: Consentimiento, auditoría, derechos del usuario  
✅ **Seguridad robusta**: Validaciones, rate limiting, auditoría  

El sistema propuesto transforma el registro de visitas de un simple formulario a un **proceso legal robusto con evidencias digitales**, apto para uso comercial y defensa legal.

---

**Documento elaborado el 15/06/2026**  
**Versión: 1.0**  
**Autor: Claude (Anthropic)**  
**Proyecto: MOYZA - Sistema de Registro de Visitas Inmobiliarias**
