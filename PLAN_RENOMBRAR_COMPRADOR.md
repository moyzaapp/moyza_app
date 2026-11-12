# Plan: cambiar el nombre de un comprador después de crearlo

Fecha: 2026-11-12. Rama `63-agregar-moes`. Petición: que los agentes puedan corregir el nombre
de un comprador registrado con un nombre provisional ("SN") una vez contactado.

## 1. Situación actual

- El nombre vive en dos sitios: `Buyer.name` (ficha del comprador) y `PropertyAlert.lead_name`
  (copia tomada al crear la alerta, `lead_name=buyer.name`). Listado, detalle, Inicio,
  notificaciones y resultados pintan `lead_name`.
- La ficha del comprador (`/buyers/{id}`) ya tiene "Editar contacto" (nombre, teléfono, correo),
  accesible para el admin y para los agentes con acceso al comprador (`can_access_buyer`: lo
  registró, es el agente de su perfil o tiene alguna alerta suya). Pero:
  - cambiar el nombre ahí **no actualiza las alertas**: el listado y el detalle siguen
    mostrando "SN";
  - desde el detalle de la alerta, donde trabaja el agente, no hay enlace a la ficha ni forma
    de editar el nombre.

## 2. Diseño

- **Un solo punto de verdad**: `services/buyer_rename.py::rename_buyer(db, buyer, name)` cambia
  `Buyer.name` y el `lead_name` de **todas** las alertas de ese comprador (abiertas y cerradas:
  es la misma persona). Lo usan la ficha ("Editar contacto") y la alerta.
- **En el detalle de la alerta**, junto al nombre en "Información del Interesado": botón
  "Editar nombre" (lápiz) que abre un modal con el nombre actual y la nota "Se actualiza en la
  ficha del comprador y en todas sus alertas". `POST /alerts/{id}/rename-buyer` con el mismo
  permiso que ver la alerta (admin o su agente). Alertas antiguas sin `buyer_id`: solo
  `lead_name`.
- Enlace "Ver ficha del comprador" en ese mismo bloque (hay `buyer_id`).
- Validación: nombre obligatorio, recortado, máximo 150 caracteres. Sin seguimiento del sistema
  (es una corrección de datos, no una gestión).

## 3. Decisiones tomadas sin preguntar

- Se actualizan todas las alertas del comprador, no solo la abierta: evita que la misma persona
  salga con dos nombres en el historial y en Resultados Comerciales.
- Lo puede hacer cualquier agente que pueda ver la alerta; no hace falta restringirlo al admin.
- El nombre antiguo no se guarda en ningún histórico (no existe para el resto de datos de contacto).

## 4. Estado

Hecho el 2026-11-12 (ver commit). Sin migración.
