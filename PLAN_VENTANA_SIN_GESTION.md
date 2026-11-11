# Plan: ventana de inicio del admin solo con compradores sin gestionar

Fecha: 2026-11-10. Rama `63-agregar-moes`. Petición: el admin, al entrar, no quiere ver todo
en "Compradores que requieren atención"; quiere ver solo los que no se han gestionado para
reasignarlos. Además se queja de que "siguen saliendo gestiones sin atender muy antiguas"
aunque las va reasignando.

## 1. Cómo funciona hoy

- La ventana (`dashboard/_admin.html`, modal `pendingBuyersModal`) se abre una vez por inicio
  de sesión (cookie `moyza_welcome`) y lista **por agente** la suma de dos avisos distintos
  (`buyer_attention_service`):
  - **Volver a llamar** (R3): el agente ya llamó, el último seguimiento es «Sin respuesta» y
    han pasado 24 h hábiles. Es trabajo del agente (rellamar o cerrar al tercer intento).
  - **Sin gestión** (R1): han pasado 48 h hábiles desde el último seguimiento real o, si no
    hay ninguno desde la asignación, desde la asignación. Mezcla dos situaciones:
    (a) **nunca gestionada** desde que se asignó y (b) **gestionada pero parada** (hubo
    llamada o visita, y luego nada en más de 48 h hábiles).
- "El más antiguo, 13 d 22 h hábiles" es el máximo de los dos relojes (1 d = 24 h hábiles,
  es decir, horas de reloj de días laborables). 13–14 días hábiles atrás es justo el corte
  `BUYER_ATTENTION_SINCE` (20/10): son alertas asignadas desde el corte y sin tocar desde
  entonces, no alertas de hace meses.
- **Reasignar reinicia el reloj** (`alert_assignment_service.assign`: `assigned_at = ahora`,
  estado Pendiente, sin leer). Si el nuevo agente tampoco hace nada, a las 48 h hábiles la
  alerta vuelve a salir, ahora a nombre del nuevo agente. Es el comportamiento esperado, pero
  para el admin parece "la misma de siempre". Nada en la ventana ni en el listado dice
  "ya la reasignaste el día X y sigue sin gestión".
- El botón **Ver compradores** lleva a `/alerts?agent_id=X`: **todas** las alertas abiertas
  de ese agente, ordenadas por fecha de asignación, con un badge en las que requieren
  atención. No hay filtro "solo las que requieren atención" ni "solo sin gestión"; el admin
  tiene que localizarlas a ojo entre las demás y reasignarlas una a una con el botón de fila.

## 2. Propuesta

1. **La ventana solo muestra "sin gestionar"** (R1, situación (a): ninguna gestión desde la
   asignación). Por agente: "N sin gestionar · el más antiguo, X d hábiles". Los "volver a
   llamar" y las "paradas" (b) dejan de contarse en la ventana; siguen en la sección
   "Requiere atención" del Inicio y en los badges del listado, que no cambian.
   - El servicio distingue (a) de (b): nuevo campo `never_managed` en `BuyerAttention`
     (ningún seguimiento real en la ventana de asignación).
2. **Ver compradores lleva al listado ya filtrado**: nuevo parámetro `attention=sin_gestion`
   en `/alerts` (solo admin) que deja solo las alertas de ese agente que están sin gestionar,
   ordenadas de más a menos antigua, con el botón **Reasignar** de cada fila a mano. Chip
   visible "Sin gestionar" para quitar el filtro. Así el flujo es: ventana → agente →
   lista corta → reasignar una a una.
3. **Marca de "ya reasignada"**: en la ventana y en el listado filtrado, las alertas que ya
   tuvieron una reasignación después del corte muestran "reasignada el dd/mm (de Nombre)".
   El admin ve de un vistazo que reasignar a ese agente no sirvió y puede decidir otra cosa
   (otro agente, cerrarla o hablar con el agente).
4. Subtítulo de la ventana: "N compradores sin gestionar · más de 48 h hábiles desde que se
   asignaron". Si no hay ninguno sin gestionar, la ventana no se abre.

Fuera de alcance: el email diario y la campana de los agentes (siguen con las dos reglas).

## 3. Decisiones (respuestas del usuario, 2026-11-10)

1. "Sin gestionar" = **ninguna gestión desde la asignación**, incluidas las reasignadas (su
   ventana empieza en la reasignación). Las paradas tras una gestión quedan fuera de la ventana.
2. **Sí**: los "volver a llamar" salen de la ventana de inicio.
3. Reasignación múltiple: "como sea más útil". Decisión: **sí**, casillas en el listado
   filtrado y un agente destino, porque con cientos de compradores el botón de fila es lento.
4. La marca "reasignada el dd/mm (de Nombre)" **vale así** por ahora.

## 4. Fases

- **Fase A — servicio y ventana**: `never_managed` en `BuyerAttention`, ventana de inicio solo
  con sin gestionar (y cuántas de ellas ya reasignadas), tests.
- **Fase B — listado filtrado**: parámetro `attention=sin_gestion` en `/alerts` (solo admin),
  chip, orden de más antigua a más nueva, enlace desde la ventana, marca de reasignación en la
  fila, el Reasignar de fila vuelve al listado filtrado, tests de ruta.
- **Fase C — reasignación múltiple**: casillas + barra "N seleccionadas · Reasignar", modal con
  agente destino y motivo, `POST /alerts/reassign-bulk` que valida cada alerta como la
  reasignación individual, flash con el resultado, tests.

## 5. Estado

En ejecución con un agente Opus 5.5 high (tres commits, uno por fase).
