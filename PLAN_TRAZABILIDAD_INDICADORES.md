# Plan: trazabilidad de los indicadores de agente (solo admin)

Fecha: 2026-10-26 · Rama `63-agregar-moes`

## 1. Qué hay hoy

| Indicador | Cómo se cuenta (una sola definición en `PerformanceReportService._indicator_spec`) | Dónde se ve |
|---|---|---|
| Contactos (venta / alquiler) | Alertas de comprador con `agent_id` = agente, `company_id` = empresa activa, `created_at` dentro del período, tipo por `business_type` de la alerta. | Resultados Comerciales → Rendimiento, Inicio admin |
| Captaciones CRM | Propiedades con `agent_id` = agente, empresa activa, `market_entry_date` dentro del período, tipo por `business_type` de la propiedad. | Igual |
| Bajadas | Filas de `property_price_history` con `new_price < old_price` cuya propiedad es del agente y de la empresa, `created_at` en el período. | Igual |
| Cierres | Seguimientos `CERRADO` de alertas del agente y de la empresa, `created_at` del seguimiento en el período; tipo por la alerta o, si falta, por la propiedad. | Igual |
| Hojas de visita | Visitas donde el agente es principal o acompañante, propiedad de la empresa, `created_at` en el período. | Igual |

- Período en curso: se calcula en vivo. Período cerrado: se lee del **snapshot** congelado
  (`agent_performance_reports`), que puede diferir de lo que daría la consulta hoy (datos corregidos después).
- Las tarjetas muestran solo el número, el desglose V/A y el objetivo. No hay forma de saber **qué** registros
  componen el número.

## 2. Propuesta: "ver de dónde sale" sin añadir pantallas

### 2.1 Un panel lateral por métrica, bajo demanda

- En **Resultados Comerciales → Rendimiento**, solo para admin, el número de cada tarjeta pasa a ser un botón
  discreto (icono de lupa al lado, `aria-label="Ver el detalle de Captaciones de Laura"`). Nada cambia a simple
  vista: ni columnas nuevas ni tablas abiertas.
- Al pulsar, se abre un **panel lateral** (drawer, macro `ui.drawer` del skill o modal ancho en móvil) que carga
  por `fetch` un parcial HTML desde `GET /commercial-results/{agent_id}/metric/{key}?period_type=…&period_start=…`.
  El resto de la página no se recarga ni se recalcula.
- Contenido del panel, de arriba abajo:
  1. **Regla en una frase**, generada desde el servicio, no escrita a mano en la plantilla:
     "Captaciones = propiedades de MOYZA cuyo agente es Laura y cuya *fecha de entrada al mercado* está entre
     el 1 y el 31 de octubre de 2026." Así el admin sabe exactamente qué se está contando.
  2. **Totales**: "5 · venta 4 · alquiler 1". Si el período está **cerrado**: "Congelado el 1/11: 5 ·
     Recalculado ahora: 6" con aviso ámbar si difieren (es justo la evidencia de que algo cambió después).
  3. **Tabla de filas**, una por registro contado, con enlace al origen:
     - Contactos: fecha, comprador, propiedad o "búsqueda general", tipo, origen → enlace a la alerta.
     - Captaciones: fecha de entrada, referencia/título, dirección (sin número), tipo, precio → enlace a la propiedad.
     - Bajadas: fecha, propiedad, precio anterior → nuevo, motivo → enlace a la propiedad.
     - Cierres: fecha, comprador, propiedad, tipo, nota del cierre → enlace a la alerta.
     - Hojas de visita: fecha, visitante, propiedad, "principal" o "acompañante", estado → enlace a la visita/PDF.
  4. **Descargar CSV** de esa tabla (misma consulta), para pegarlo en un informe o guardarlo como evidencia.
- Paginación simple dentro del panel (50 filas, "ver más") por si un año tiene cientos de contactos.

### 2.2 Garantía de coherencia (lo importante)

El panel usa **la misma función** que el contador: `_indicator_spec` monta la consulta y, en vez de
`count()`, devuelve las filas. Un test por indicador comprueba que `len(filas) == número de la tarjeta`
para el mismo agente y período. Si alguien cambia una regla, cambia en los dos sitios a la vez. Es lo que
convierte el panel en evidencia y no en "otra cifra".

### 2.3 Inicio del admin

En "Cumplimiento del equipo" cada barra ya enlaza a Resultados Comerciales. No se añade nada más al Inicio
para no cargarlo: el detalle vive en Resultados Comerciales. (Opcional, §4-1: la misma lupa en las barras
del Inicio, abriendo el mismo panel.)

### 2.4 Qué NO se hace

- Nada para agentes (decisión del usuario: solo admin).
- No se guardan "explicaciones" en base de datos ni se cambia el snapshot: el panel es consulta en vivo.
- Ninguna columna ni tabla nueva en las pantallas existentes.

## 3. Implementación

### Fase 1 · Servicio
- [ ] `PerformanceReportService.indicator_rows(indicator, agent_id, period_start, period_end, limit, offset)`
      reutilizando `_indicator_spec` (+ `hojas_visita` con `visits_for_agent`), con `joinedload` de lo que
      pinta cada fila. `indicator_rule_text(indicator, agent, period, company)` para la frase.
- [ ] `tests/test_indicator_rows.py`: para cada indicador, `len(rows) == calculate_metrics()[indicador]`
      con datos de prueba (venta y alquiler, dentro y fuera del período, otra empresa, otro agente); la frase
      contiene agente, empresa y fechas.

### Fase 2 · Ruta, panel y CSV
- [ ] `GET /commercial-results/{agent_id}/metric/{key}` (admin, agente de la empresa activa) → parcial
      `commercial_results/_metric_detail.html`; `?format=csv` → descarga.
- [ ] Lupa en `metric_card` (solo si `is_admin`), drawer accesible (`role="dialog"`, Escape, foco), carga con
      `fetch`, estado "cargando" y error en el propio panel. JS en `static/js/commercial_results.js`.
- [ ] Período cerrado: mostrar snapshot y recálculo.
- [ ] Tests de ruta: 403 para agente; parcial contiene las filas; CSV con cabecera y N filas; aislamiento por empresa.

### Fase 3 · QA
- [ ] `ui_lint.py`; revisión a 375 px (el panel ocupa toda la pantalla en móvil); `fetch_page.py`.
- [ ] Nota breve en `MULTIEMPRESA_MOYZA_MOES.md`: sin migración, sin variables.

## 4. Decisiones tomadas (2026-10-26)

| # | Pregunta | Decisión |
|---|---|---|
| 1 | ¿Lupa también en el Inicio? | **Solo en Resultados Comerciales.** El Inicio sigue enlazando allí. |
| 2 | ¿Descarga CSV? | **Sí.** |
| 3 | Períodos cerrados: ¿congelado + recálculo con aviso? | **Sí.** |
| 4 | ¿Nombre del comprador en las filas? | **Sí** (solo admin). |

Nota de implementación: la columna de dirección en las filas de captaciones/bajadas se muestra como
título/referencia y ciudad, **sin la dirección**, hasta que se cierre el cambio de "dirección sin número"
que está en curso en otra tarea (evita tocar el mismo filtro a la vez).
