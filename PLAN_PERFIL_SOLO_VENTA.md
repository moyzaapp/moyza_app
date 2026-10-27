# Plan: perfil obligatorio solo en Venta (opcional en Alquiler)

Fecha: 2026-10-20. Rama: `63-agregar-moes`.

> **2026-10-26, alquiler sin perfil de comprador**: en Alquiler el perfil ya
> **no se muestra ni se guarda** (`buyer_matching.profile_applies`): sin bloque
> de perfil, sin paso Perfil (pasos: Contactar y Propuesta con buscador manual),
> sin sugerencias, sin perfil en «Contactado» (el servidor ignora esos campos) y
> el POST del paso Perfil no guarda nada. Una alerta de Venta que pasa a
> Alquiler desde el perfil solo cambia la operación. La ficha de un comprador
> solo de alquiler (`buyer_profile_applies`) no tiene las pestañas de perfil ni
> de compatibles. Solo visibilidad: los perfiles guardados y sus columnas se
> conservan. Lo de abajo sobre "perfil opcional en Alquiler" queda sustituido.

## Decisión cerrada con el usuario

El perfil de búsqueda (`PLAN_PERFIL_OBLIGATORIO.md`, mínimos de
`PLAN_PERFIL_UBICACION.md`) es **obligatorio solo cuando la operación de la
alerta es Venta**. En **Alquiler** el perfil es **opcional**: se puede rellenar
y, si existe, se usa para sugerir propiedades, pero no bloquea nada.

## Diseño: un único interruptor

En `app/services/buyer_matching.py`:

```python
def profile_required(alert) -> bool:
    """El perfil es obligatorio solo para alertas de Venta con comprador.
    Alquiler (y cualquier otro valor) → opcional. Sin comprador no hay dónde guardarlo."""
    return alert.buyer_id is not None and alert.business_type == BusinessType.VENTA
```

Sustituye al `profile_applies` que hoy exime a las alertas sin comprador en
`add_follow_up`, y es la **única** fuente de verdad: rutas, plantillas, JS y
tests la usan. `profile_is_complete` / `missing_profile_fields` no cambian
(siguen diciendo si el perfil está completo; `profile_required` dice si hace
falta). Si la operación cambia desde el perfil (Venta ↔ Alquiler), la
obligatoriedad cambia con ella en la misma petición.

## Comportamiento cuando NO es obligatorio (Alquiler)

| Punto | Venta (como hoy) | Alquiler (nuevo) |
|---|---|---|
| Seguimiento Contactado | campos de perfil obligatorios la 1.ª vez | campos visibles pero **opcionales**; si se rellenan, deben cumplir los mínimos y registran el perfil igual (1 solo `CONTACTADO`) |
| Visita programada / Oferta / Cerrado | bloqueados sin perfil | **no se bloquean** |
| Paso Perfil | obligatorio | opcional, texto "Opcional en alquiler: si lo registras verás propiedades sugeridas"; mínimos solo si se envía algo |
| Paso Propuesta | sin perfil: ni sugerencias ni buscador | sin perfil: **buscador manual** disponible y asociar permitido; con perfil: sugerencias como siempre |
| Asociar / cambiar propiedad (`link_property`, buscador) | exige perfil | **no** exige perfil |
| Banner "Perfil pendiente" | sí | no (en su lugar, línea discreta "Perfil opcional en alquiler" con enlace al paso Perfil) |
| Chip "Sin perfil" en `/alerts` (admin) | sí | no |
| Ficha del comprador (perfil) | mínimos obligatorios | mínimos solo si la operación elegida es Venta; al cambiar el select la UI quita/pone los asteriscos y el servidor valida según la operación enviada |

## Cambios por archivo

- `app/services/buyer_matching.py`: `profile_required(alert)`;
  `profile_required_for_business_type(bt)` para la ficha del comprador.
- `app/web/routes/alerts.py`: `_search_link_denied(..., require_profile=…)` →
  calcular con `profile_required(alert)`; `_page_profiles(with_missing)`
  excluir alertas que no lo requieren; `_search_context` pasar
  `profile_required` al contexto y permitir Propuesta sin perfil cuando no es
  obligatorio; `save_alert_search_profile` (validar mínimos solo si es
  obligatorio o si se envió algún campo); `add_follow_up` (Contactado: campos
  opcionales si no es obligatorio; `PROFILE_REQUIRED_STAGES` solo bloquean si
  es obligatorio); `save_search_criteria` (ficha): mínimos según operación.
- Plantillas: `alerts/_search_steps.html` (banner vs línea discreta;
  Propuesta con buscador sin perfil), `alerts/detail.html` (modal: `required`
  y `PROFILE_BLOCKS_STAGES` según `profile_required`), `alerts/list.html`
  (chip), `buyers/detail.html` + `components/search_profile_form.html`
  (asteriscos dinámicos según operación), `app/static/js/search-profile.js`
  (la validación de ubicación solo cuando es obligatorio o hay campos
  rellenos; en la ficha, escuchar el select de operación).
- Documentación: `docs/DECISIONES_ALERTAS_BUSQUEDA.md` §7 y nota en
  `PLAN_PERFIL_OBLIGATORIO.md`.

## Tests (patrón `tests/test_profile_required.py`)

- `profile_required`: Venta con comprador → True; Alquiler → False; sin
  comprador → False; `business_type` None → False.
- Alquiler sin perfil: Visita programada OK; Cerrado OK; Contactado sin campos
  OK (sin perfil creado); Contactado con campos parciales → error de mínimos;
  Contactado con mínimos → perfil + 1 `CONTACTADO`; asociar propiedad OK;
  Propuesta renderiza el buscador y no el banner.
- Venta: todo como antes (los tests existentes siguen pasando).
- Cambio de operación desde el perfil: Venta→Alquiler deja de bloquear;
  Alquiler→Venta con perfil incompleto → error de mínimos en esa misma
  petición.
- Ficha del comprador: Alquiler sin mínimos → OK; Venta sin mínimos → error.
- Chip "Sin perfil": solo alertas de Venta.
- Suite completa: el conjunto de fallos no cambia (previo:
  `test_scheduler.py::test_check_automatic_reports_con_propiedad_activa`;
  errores de integración por falta de PostgreSQL).

## Verificación adicional

`python -c "import app.main"`; plantillas compilan; `node --check`;
`build_css.sh`; `ui_lint.py` sin avisos nuevos. Sin migración.

## Entrega

Sin commits. Informe con archivos tocados, decisiones, resultados con números,
pasos de prueba manual (una alerta de Alquiler y una de Venta), riesgos.
Marcar "Estado".

## Estado

- [x] `profile_required` y uso en todas las rutas
- [x] Plantillas y JS (alerta, modal, listado, ficha del comprador)
- [x] Tests, documentación, lint, CSS

Sin migración (no cambia el esquema). Sin commits.

### Notas de implementación (2026-10-20)

La decisión cerrada no se ha cambiado. Donde el plan dejaba margen:

- **Firma**: `profile_required(alert, business_type=None)`; el segundo
  argumento opcional es la operación pedida en la misma petición (cambio
  desde el perfil). La comparación con Venta vive solo en
  `profile_required_for_business_type`; `profile_required_operations()` da la
  lista al JS (sin "Venta" escrito en plantillas ni JS).
- `_profile_applies` desaparece. Las rutas usan `_profile_pending(alert, op)`
  (= `profile_required` y perfil incompleto) para bloquear, y
  `_can_hold_profile(alert)` (= tiene comprador) solo para saber si hay dónde
  guardar un perfil opcional (pasos y perfil en el modal); este último no
  decide la obligatoriedad.
- **Paso Perfil en Alquiler sin ningún dato** (país y operación no cuentan):
  si tampoco cambia la operación, no se guarda nada (flash `info` "No se ha
  guardado nada: el perfil de X está vacío y es opcional en alquiler"); si
  solo cambia la operación (p. ej. Venta → Alquiler sin perfil), se registra
  `PERFIL_GUARDADO` con la nota "Operación: Venta → Alquiler" y el perfil no se
  toca (si ya existía, solo toma la operación nueva).
- **Contactado**: la operación se lee siempre (antes solo si llegaban datos
  del perfil); un cambio de operación sin datos se aplica y va en la nota del
  mismo `CONTACTADO`.
- **Paso por defecto** tras la primera gestión en Alquiler sin perfil:
  Propuesta (buscador), no Perfil. En Propuesta sin perfil el buscador se
  titula "Buscar una propiedad" (con perfil, "¿No está en la lista?" bajo las
  sugerencias). Las sugerencias siguen saliendo solo con el perfil completo.
- **Ficha del comprador en Alquiler**: sin mínimos en absoluto (también con
  datos parciales), al pie de la letra de la tabla; en la alerta, en cambio,
  un perfil opcional que se rellena debe ir completo.
- **Textos**: "Perfil opcional en alquiler: si lo registras verás propiedades
  sugeridas." + enlace "Registrar perfil"; el "en alquiler" sale de la
  operación de la alerta (sin operación: "Perfil opcional").
- **JS** (`search-profile.js`): el bloque `[data-search-profile]` trae
  `data-required-operations` (los mínimos siguen al select de operación) o
  `data-profile-required` (fijo), y `data-minimums-if-filled` (perfil
  opcional: mínimos en cuanto hay algún dato). Pone/quita `required` y
  asteriscos de tipo, precio máximo y ubicación al cambiar. Modal con perfil
  completo: opcional con mínimos si hay datos (como el servidor).
