# Plan: perfil y propuesta en TODAS las alertas, y perfil obligatorio al contactar

Fecha: 2026-10-19. Rama: `63-agregar-moes`.

## Contexto

Hoy los pasos **Contactar → Perfil → Propuesta**, la asociación de propiedad y
"Cambiar propiedad" solo existen en las alertas creadas **sin referencia**
(`origin = 'search'`, `PLAN_ALERTA_SIN_REFERENCIA.md`). Guardar el perfil
registra un seguimiento `PERFIL_GUARDADO` (repetible, no avanza etapa). Las
etapas seleccionables son: Sin respuesta, Contactado, Visita programada,
Oferta/Negociación y los cierres (Cerrado, Sin interés, Sin solvencia, No apto);
"Primera llamada" y "Calificado" son heredadas y el formulario las rechaza
(`PLAN_RECORDATORIO_SIN_RESPUESTA.md` §3.3).

Lo que se ha visto en el uso: un comprador entra por una propiedad concreta y
después hay que ofrecerle otras que se ajusten a lo que puede. Y el perfil no
se está tomando de forma sistemática.

## Decisiones cerradas con el usuario (no cambiar)

1. **Perfil, Propuesta y "Cambiar propiedad" en todas las alertas**, también en
   las creadas con referencia. `origin` se conserva solo como dato (cómo entró
   el comprador) para analítica; deja de condicionar el flujo.
2. **El perfil es obligatorio y se toma al contactar.** El seguimiento
   **Contactado** lleva dentro los campos del perfil (obligatorios). Sin
   perfil completo **no** se puede registrar Visita programada, Oferta ni
   Cerrado (éxito), ni usar el paso Propuesta ni "Cambiar propiedad".
3. **Se puede registrar sin perfil**: Sin respuesta (el comprador no contesta)
   y los cierres negativos (Sin interés, Sin solvencia económica, No apto para
   el propietario).
4. **Perfil mínimo completo** = tipo de inmueble + precio máximo + al menos una
   zona o una ciudad. Dormitorios, baños, precio mínimo e imprescindibles son
   opcionales. La operación ya viene de la alerta.
   > **2026-10-19, `PLAN_PERFIL_UBICACION.md`**: la ubicación pasa a ser una
   > cascada País → Provincia → Población → Zona y el mínimo de ubicación es
   > **provincia, o al menos una población o una zona** (etiqueta "ubicación"
   > en los mensajes). La operación se puede cambiar desde el perfil de la
   > alerta (cambia la de la alerta). La ficha del comprador exige los mismos
   > mínimos (deuda "Alinealo" resuelta).
5. **Perfil = Contactado**: la **primera vez** que se completa el perfil de un
   comprador (desde el paso Perfil o desde el seguimiento Contactado) se
   registra un seguimiento **`CONTACTADO`** con el resumen del perfil como
   nota (avanza la etapa). Las **ediciones posteriores** del perfil registran
   `PERFIL_GUARDADO` como hoy (no mueven la etapa).
6. **Aplica a todas las alertas existentes**: una alerta antigua sin perfil lo
   pedirá la próxima vez que el agente avance de etapa.

## Diseño

### Helper único de "perfil completo"

En `app/services/buyer_matching.py`:
`profile_is_complete(criteria) -> bool` = `criteria` existe y tiene
`property_type`, `max_price` y (`zones` o `cities`) no vacíos. Es la **única**
definición; la usan rutas, plantillas y tests. Añadir también
`missing_profile_fields(criteria) -> list[str]` para los mensajes
("Falta: tipo de inmueble, precio máximo").

### Reglas de bloqueo (servidor, `routes/alerts.py`)

- Nueva constante en `FollowUpActionType`:
  `PROFILE_REQUIRED_STAGES = {VISITA_PROGRAMADA, OFERTA, CERRADO}`.
- `add_follow_up`:
  - Si `action_type in PROFILE_REQUIRED_STAGES` y el perfil no está completo →
    flash error "Registra primero el perfil del comprador (seguimiento
    Contactado) para poder marcar «{etapa}»" y volver al detalle en el paso
    Perfil (`?step=profile`).
  - Si `action_type == CONTACTADO`: el formulario trae los campos del perfil;
    si el perfil ya estaba completo los campos son opcionales (editar), si no,
    son obligatorios (validación de mínimos con `missing_profile_fields`). Se
    guarda el perfil (`buyer_matching.apply_profile`) **y** un único
    seguimiento `CONTACTADO` cuya nota = nota del agente + resumen del perfil.
    No se crea además un `PERFIL_GUARDADO`.
  - Sin respuesta y cierres negativos: sin cambios.
- `save_alert_search_profile` (paso Perfil): valida mínimos; si antes el perfil
  **no** estaba completo → seguimiento `CONTACTADO` (nota = resumen); si ya lo
  estaba → `PERFIL_GUARDADO` como hoy. Redirige a Propuesta.
- `link_property` y el helper de bloqueo (`_search_block_reason` o como se
  llame): quitar la condición `origin != SEARCH`; añadir "perfil completo"
  como requisito (mensaje: "Registra primero el perfil del comprador").
- `_search_context`: construir el contexto de pasos para **todas** las
  alertas (ya no retornar antes si no es búsqueda). Paso por defecto: igual
  que hoy (Contactar si no hay gestión desde la asignación; Perfil si falta
  perfil; si no, Propuesta). Para una alerta con referencia y sin gestión,
  abre en Contactar con la propiedad visible.
- Pasar al detalle: `profile_complete`, `profile_missing` (lista), y para el
  modal de seguimiento los valores actuales del perfil (precarga).

### Detalle (`alerts/detail.html`, `_search_steps.html`, modal de seguimiento)

Leer antes `.claude/skills/moyza-ui-ux-pro/SKILL.md`, `references/components.md`
y `references/ux-rules.md`. Una acción primaria por paso; móvil primero.

- **Indicador de pasos en todas las alertas.** En las de referencia, la
  tarjeta de la propiedad se mantiene arriba; "Cambiar propiedad" aparece
  cuando hay perfil completo.
- **Aviso "Perfil pendiente"** (banner ámbar, macro `ui.banner`) en Contactar
  y Propuesta mientras el perfil no esté completo, con el texto "Cuando
  hables con el comprador, registra su perfil en el seguimiento Contactado" y
  un enlace al paso Perfil. Si el perfil está completo, en su lugar el resumen
  del perfil (chips) con enlace "Editar".
- **Modal de seguimiento**:
  - Al elegir **Contactado** se despliegan los campos del perfil (mismo
    partial `components/search_profile_form.html`, precargados). Obligatorios
    si el perfil no está completo; etiqueta "Perfil del comprador".
  - Las etapas bloqueadas (Visita programada, Oferta, Cerrado) **no se
    deshabilitan por JS**: se dejan seleccionables y, al elegirlas sin perfil,
    aparece un aviso inline bajo el select ("Primero registra el perfil con
    Contactado") y el botón de guardar queda deshabilitado. El servidor lo
    valida igualmente (red de seguridad).
  - Sin respuesta y cierres negativos: sin cambios.
- **Paso Perfil**: marcar los tres campos mínimos como obligatorios (asterisco
  y `required` donde aplique; zonas/ciudades son checkboxes: validación JS
  "elige al menos una zona o ciudad" + validación servidor). Texto bajo el
  título: "Datos mínimos: tipo, precio máximo y zona o ciudad".
- **Paso Propuesta** sin perfil completo: no se muestran sugerencias; se
  muestra el estado vacío con el aviso y el enlace al paso Perfil.
- La propiedad actual de una alerta con referencia aparece en Propuesta como
  "Asociada ahora" (ya existe ese marcado para búsquedas).

### Listado y ficha del comprador

- Sin cambios obligatorios. Opcional si es barato: en `/alerts`, para el
  admin, un chip gris "Sin perfil" junto a la etapa en alertas abiertas sin
  perfil completo (una consulta agrupada, sin N+1). Si no es trivial, dejarlo
  anotado como siguiente paso.

### Documentación

- `docs/DECISIONES_ALERTAS_BUSQUEDA.md`: nueva sección "2026-10-19: perfil y
  propuesta en todas las alertas; perfil obligatorio al contactar" con las
  decisiones 1–6 y qué significa ahora `origin`.
- `PLAN_ASIGNACION_ALERTAS.md`: fila en la tabla de reglas.
- `PLAN_RECORDATORIO_SIN_RESPUESTA.md` §3.3: nota de que el primer perfil
  registra `CONTACTADO` y las ediciones `PERFIL_GUARDADO`.
- `PLAN_ALERTA_SIN_REFERENCIA.md`: nota al inicio indicando que este plan
  generaliza el flujo a todas las alertas.

## Tests (SQLite en proceso, patrón `tests/test_alert_search.py`)

- `profile_is_complete` / `missing_profile_fields`: combinaciones de mínimos.
- `add_follow_up`: Sin respuesta sin perfil → OK; Visita programada / Oferta /
  Cerrado sin perfil → error y sin cambios; cierres negativos sin perfil → OK;
  Contactado sin campos y sin perfil → error; Contactado con mínimos →
  perfil guardado + un solo `CONTACTADO` con nota; Contactado con perfil ya
  completo y campos vacíos → OK (no borra el perfil).
- Paso Perfil: primera vez → `CONTACTADO`; segunda vez → `PERFIL_GUARDADO`.
- `link_property` en alerta de origen `property` con perfil → OK y agente
  intacto; sin perfil → rechazado.
- Render del detalle de una alerta **con referencia**: indicador de pasos,
  banner "Perfil pendiente", tarjeta de propiedad; tras completar el perfil,
  chips y "Cambiar propiedad".
- Actualizar los tests que asumían el bloqueo por `origin`.
- Suite completa: el conjunto de fallos no cambia (previo:
  `test_scheduler.py::test_check_automatic_reports_con_propiedad_activa`; los
  de integración dan error sin PostgreSQL).

## Verificación adicional

`python -c "import app.main"`; plantillas compilan; `build_css.sh` + clases
nuevas en el CSS; `ui_lint.py` sin avisos nuevos (ejecutar antes y después);
grep final de `origin != AlertOrigin.SEARCH` / `is_search` para confirmar que
ya no condiciona ningún flujo (solo etiquetas y analítica). **Sin migración**:
no cambia el esquema.

## Entrega

Sin commits. Informe con archivos tocados, decisiones donde el plan dejaba
margen, resultados con números, pasos de prueba manual (agente: alerta con
referencia → Sin respuesta OK → intentar Visita programada → bloqueo →
Contactado con perfil → Propuesta → Cambiar propiedad; admin: lo mismo más el
chip "Sin perfil" si se hizo), riesgos y deuda. Marcar "Estado".

## Estado

- [x] `profile_is_complete` / `missing_profile_fields` y constante `PROFILE_REQUIRED_STAGES`
- [x] Rutas: `add_follow_up` (Contactado con perfil, bloqueos), perfil (primera vez = Contactado), `link_property` sin condición de origen
- [x] Detalle: pasos en todas las alertas, banner "Perfil pendiente", modal de seguimiento con perfil embebido, mínimos en el paso Perfil
- [x] Tests
- [x] Documentación, lint, CSS
- [x] Opcional: chip "Sin perfil" para el admin en `/alerts` (misma consulta de perfiles de la página, sin N+1)

Sin migración (no cambia el esquema). Sin commits.

### Notas de implementación (2026-10-19)

Ninguna decisión cerrada se ha cambiado. Donde el plan dejaba margen:

- **Precio máximo** cuenta como mínimo solo si es mayor que 0.
- **Alertas sin comprador** (anteriores a la tabla de compradores): el perfil
  vive en el comprador, así que quedan **fuera del requisito** (pueden avanzar
  y cerrarse); no muestran pasos ni el perfil en el modal.
- **Contactado con perfil ya completo**: si llegan campos, es una edición y
  debe seguir cumpliendo los mínimos (no se puede dejar un perfil completo a
  medias); si no llega ninguno, el perfil no se toca. La nota del `CONTACTADO`
  lleva el resumen del perfil solo cuando el perfil se guarda en ese mismo
  seguimiento (nota del agente + salto de línea + resumen).
- Los errores de perfil (etapa bloqueada, Contactado sin mínimos, paso Perfil
  sin mínimos, asociar sin perfil) vuelven al **paso Perfil**
  (`?step=profile#propuesta`) con flash `error`; no se guarda nada.
- En el modal, los imprescindibles se envían como `profile_notes` (allí
  `notes` es la nota del seguimiento). El bloque del perfil es un
  `<fieldset disabled>` que solo se activa con «Contactado» (no se envía ni se
  valida con otra etapa). "Al menos una zona o ciudad" lo valida
  `static/js/search-profile.js` (en captura, antes de la guardia `data-once`).
- La tarjeta de la propiedad va **encima** de los pasos cuando la alerta tiene
  propiedad. En Propuesta, si la propiedad actual no sale entre las
  sugeridas, se pinta aparte marcada "Asociada ahora". Sin perfil, la
  Propuesta no muestra ni sugerencias ni el buscador "¿No está en la lista?"
  (y `/alerts/search-properties?alert_id=` aplica la regla de siempre).
- El enlace a la ficha de una propiedad de otro agente se oculta al agente en
  **cualquier** alerta (antes solo en búsquedas). La línea "agente de la
  propiedad" solo sale si la propiedad se asoció/cambió desde la Propuesta
  (`property_linked_at`), para no revelar al agente anterior de una alerta
  reasignada (`PLAN_ALERTA_COMO_NUEVA.md`).
- `complete_alert` (`POST /alerts/{id}/complete`, sin botón en la interfaz,
  no registra etapa) no se ha tocado: no es «Cerrado (éxito)».
