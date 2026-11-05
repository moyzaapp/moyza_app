# Plan: baja lógica de usuarios y agentes (dar de baja, reasignar, reactivar)

Fecha: 2026-11-04 · Rama de trabajo: `63-agregar-moes`

## 1. Cómo funciona hoy

- **Usuario y agente son dos tablas unidas solo por email** (`get_agent_from_user`,
  `app/web/dependencies/auth.py:73`). No hay FK entre `users` y `agents`.
- **Borrado físico** en los dos sitios:
  - `POST /auth/users/delete/{id}` → `user_service.delete_user` borra la ficha de agente (por
    email) y el usuario. No captura `IntegrityError`: si el agente tiene propiedades, alertas u
    objetivos (FK `NO ACTION`), o el usuario creó interacciones, compradores, seguimientos…
    la petición acaba en **500**.
  - `POST /agents/delete/{id}` (`routes/agents.py:323`) bloquea solo si tiene propiedades en la
    empresa activa (`?error=in_use`); si el agente está en dos empresas lo quita de la activa
    (`remove_from_company`); si no, `db.delete(agent)` y puede fallar igual por las otras FK.
- `users.is_active` existe y se pinta en `/auth` (badge Activo/Inactivo), pero **nunca se pone a
  False y no se comprueba** ni en `authenticate_user`, ni en `AuthMiddleware`, ni en
  `get_current_web_user`, ni en `core/deps.get_current_user` (API). `agents` no tiene ningún
  campo de estado.
- `notification_service` ya filtra `User.is_active.isnot(False)`: un usuario inactivo no
  recibe notificaciones. Es el único sitio que respeta el campo.
- Si se borra el usuario pero la ficha sobrevive (usuario con rol no-agente, o borrado desde
  `/auth` fallido a medias), `create_user` con el mismo email **reutiliza la ficha**
  (`user_service.py:82-100`). Si la ficha se borró, el que vuelve empieza de cero.

## 2. Decisiones (acordadas 2026-11-04)

1. **Baja lógica en lugar de borrado.** Nadie con historial se borra. "Irse" y "volver" son
   dos estados de la misma ficha.
2. **Propiedades vivas bloquean la baja.** Si el agente tiene propiedades en estado `Activa`,
   `Reservada` o `Pausada` en cualquier empresa, no se puede dar de baja hasta que se reasignen
   desde Propiedades (es la fuente de verdad del captador; la app no reasigna propiedades en el
   modal de baja). `Vendida`, `Retirada` y `Archivada` se quedan a su nombre: son historial y
   alimentan resultados y captaciones de periodos pasados.
3. **Alertas abiertas se reasignan en el modal de baja.** Alertas en `PENDING` o `IN_PROGRESS`
   de cada empresa pasan al agente que elija el admin, usando la reasignación existente
   (`alert_assignment_service.assign` con `kind="reassigned"`, historial en
   `alert_assignment_logs`, seguimiento `REASIGNADA` y notificación al nuevo agente). Las
   cerradas no se tocan.
4. **Un inactivo no entra ni aparece para recibir trabajo.** Login rechazado con mensaje claro;
   sesión viva expulsada por el middleware; fuera de los selectores de asignación (alertas,
   propiedades, visitas, cesiones) y del equipo del Inicio y de los snapshots nuevos de
   desempeño. Su nombre sigue saliendo en visitas, cesiones, historial y resultados pasados.
5. **Reactivar** devuelve login, ficha, empresas e historial. Lo reasignado en la baja no vuelve
   solo. Crear un usuario con el email de uno inactivo no duplica: se avisa y se ofrece
   reactivar.
6. **Borrado físico solo sin historial** (alta equivocada). El botón solo se muestra si el
   usuario/agente no tiene nada asociado; el servidor además captura `IntegrityError`.
7. **Baja total desde Usuarios; por empresa desde Agentes.** "Quitar de esta empresa" en
   Agentes (multiempresa) sigue como está. La baja total vive en `/auth` (Usuarios). En
   Agentes, el botón "Eliminar" desaparece: las fichas con usuario enlazan a Usuarios; las
   fichas sin usuario (creadas desde "Nuevo Agente") tienen "Dar de baja" / "Reactivar" con el
   mismo servicio.
8. **No se tocan las FK** de la base de datos: con baja lógica ya no se borra nada con
   historial.

## 3. Modelo de datos (fase A)

Migración Alembic nueva `f5a6b7c8d9e0_user_agent_deactivation.py`,
`down_revision = 'e4f5a6b7c8d9'`:

```python
# users
op.add_column('users', sa.Column('deactivated_at', sa.DateTime(), nullable=True))
# agents
op.add_column('agents', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
op.add_column('agents', sa.Column('deactivated_at', sa.DateTime(), nullable=True))
op.create_index('ix_agents_is_active', 'agents', ['is_active'])
```

`users.is_active` ya existe (Boolean, nullable, default True): se deja; `NULL` se trata como
activo en todas las comprobaciones (`is_active.isnot(False)`), como hace `notification_service`.

Modelos:

```python
# app/models/user.py
deactivated_at = Column(DateTime, nullable=True)

# app/models/agent.py
is_active = Column(Boolean, nullable=False, default=True, server_default="true", index=True)
deactivated_at = Column(DateTime, nullable=True)
```

## 4. Acceso y selectores (fase A)

### 4.1 Bloqueo de acceso

| Sitio | Cambio |
|---|---|
| `services/auth_service.authenticate_user` | Si `user.is_active is False` devuelve el sentinel `INACTIVE` (constante del módulo) en vez del usuario. `routes/auth.login` muestra "Tu usuario está dado de baja. Contacta con un administrador." (mismo bloque de error de `auth/login.html`). |
| `web/middleware/auth.AuthMiddleware` | Tras cargar el usuario: si `is_active is False` → redirección a `/` borrando `access_token` (expulsa sesiones vivas). |
| `web/dependencies/auth.get_current_web_user` | Mismo check → redirección a `/`. |
| `web/dependencies/company.get_api_user` y `core/deps.get_current_user` | Inactivo = no autenticado (None / 401 "Usuario dado de baja"). |

### 4.2 Helper único de agentes activos

En `services/company_scope.py`:

```python
def active_agents(query):
    """Solo fichas activas (baja lógica, PLAN_BAJA_USUARIOS.md §4.2)."""
    return query.filter(Agent.is_active.is_(True))

def scope_active_agents(query, company_id: int):
    return active_agents(scope_agents(query, company_id))
```

`scope_agents` **no cambia** (listados e historial siguen viendo a todos).

### 4.3 Dónde se aplica `active_agents` (recibir trabajo nuevo)

| Sitio | Uso | Cambio |
|---|---|---|
| `services/visit_agents.get_agent_in_any_company` | lookup del agente asignable (alertas, visitas) | activos solo |
| `services/visit_agents.companion_agent_groups` | select de acompañante y de "Agente asignado" (`assignable_agents`) | activos solo |
| `services/alert_assignment_service.cession_agents` | select de cesión | activos solo |
| `routes/visits.py:127` | select de agente de la visita | activos + el agente fijado de la visita si está inactivo (opción "(baja)") |
| `routes/properties.py:256` | select de captador del formulario | activos + el captador actual si está inactivo (opción "(baja)", solo al editar) |
| `routes/alerts.py:681`, `:2980` (`agents` del alta/perfil) | selectores de alta | activos solo |
| `services/dashboard_service.company_agents` | equipo del Inicio | activos solo |
| `services/performance_report_service.freeze_all_for_period` | snapshots nuevos | activos solo |

### 4.4 Dónde se mantienen todos (historial y filtros de consulta)

`routes/alerts.py:1503` (filtro del historial de cesiones), `routes/commercial_results.py:89,121`,
`routes/report_logs.py:28`, `routes/agents.py:91` (listado), `buyer_reminder_service`,
`user_service`, `dependencies/auth.get_agent_from_user`, `dependencies/company.get_allowed_companies`.
En los filtros/listados que pintan el nombre, los inactivos llevan el sufijo " (baja)" en la
opción o el badge `ui.badge("Baja", "gray")` en la fila.

## 5. Servicio de baja (fase B): `app/services/offboarding_service.py`

```python
LIVE_PROPERTY_STATUSES = {PropertyStatus.ACTIVE, PropertyStatus.RESERVED, PropertyStatus.PAUSED}
OPEN_ALERT_STATUSES = REASSIGNABLE_STATUSES  # PENDING, IN_PROGRESS (alert_assignment_service)

@dataclass
class CompanyPending:
    company: Company
    live_properties: int          # bloquean
    open_alerts: int              # se reasignan
    targets: list[Agent]          # activos de esa empresa, sin el propio

@dataclass
class OffboardingSummary:
    user: Optional[User]
    agent: Optional[Agent]
    pending: list[CompanyPending]  # solo empresas del agente
    blocked: bool                  # any(live_properties > 0)
    has_history: bool              # para decidir si se puede borrar físicamente

class OffboardingError(Exception): ...

def summary_for_user(db, user) -> OffboardingSummary
def summary_for_agent(db, agent) -> OffboardingSummary          # ficha sin usuario
def deactivate(db, *, user=None, agent=None, by_user, reassign_to: dict[int, int], reason=None) -> OffboardingSummary
def reactivate(db, *, user=None, agent=None) -> None
def has_history(db, user=None, agent=None) -> bool
def find_agent(db, user) -> Optional[Agent]   # por email, como get_agent_from_user
```

Reglas de `deactivate`:

- `by_user.id == user.id` → `OffboardingError("No puedes darte de baja a ti mismo")`.
- `blocked` → `OffboardingError` con el detalle por empresa ("Tiene 3 propiedades activas en
  MOYZA. Reasígnalas desde Propiedades antes de dar de baja.").
- Por cada empresa con `open_alerts > 0`, `reassign_to[company.id]` es obligatorio y debe ser un
  agente **activo de esa empresa distinto del saliente** (`scope_active_agents` +
  `get_agent_in_company`); si falta o no vale → `OffboardingError`.
- Reasigna cada alerta abierta con `alert_assignment_service.validate_reassignment` +
  `assign(db, alert, target, by_user, reason or f"Baja de {nombre}", is_new=False)`. Solo
  `flush`; un único `commit` al final.
- Marca `user.is_active = False`, `user.deactivated_at = now` (si hay usuario) y
  `agent.is_active = False`, `agent.deactivated_at = now` (si hay ficha).
- Devuelve el resumen para el flash: "Juan Pérez dado de baja. 5 compradores reasignados a Ana
  (MOYZA)".

`has_history`: EXISTS sobre `properties.agent_id`, `property_alerts.agent_id`/`created_by`,
`alert_follow_ups.created_by`, `alert_assignment_logs.from/to_agent_id`, `property_visits`
(`agent_id`, `companion_agent_id`, `created_by`), `buyers.created_by`,
`property_interactions.created_by`, `reports.uploaded_by`, `agent_performance_targets` y
`agent_performance_reports` (por agente). Cualquiera → True.

`user_service`:

- `create_user`: si existe usuario con ese email y `is_active is False` →
  `HTTPException(400, "Ese usuario está dado de baja. Reactívalo desde la lista de usuarios.")`.
- `delete_user`: solo si `not has_history`; si hay historial →
  `HTTPException(400, "Tiene historial: dale de baja en lugar de eliminarlo.")`. Envuelve el
  `commit` en `try/except IntegrityError` → rollback + el mismo mensaje.

## 6. Rutas (fase B)

| Ruta | Quién | Qué |
|---|---|---|
| `GET /auth/users/{user_id}/offboarding` | admin | JSON del resumen (ver §6.1) para pintar el modal |
| `POST /auth/users/{user_id}/deactivate` | admin | form: `reason` (opcional) + `reassign_to_<company_id>` por empresa con alertas abiertas. Flash y redirect a `/auth`. |
| `POST /auth/users/{user_id}/reactivate` | admin | reactiva usuario y ficha. Flash. |
| `POST /auth/users/delete/{user_id}` | admin | ya existe; ahora solo sin historial |
| `GET /agents/{agent_id}/offboarding` | admin | mismo JSON para fichas **sin usuario** |
| `POST /agents/{agent_id}/deactivate`, `POST /agents/{agent_id}/reactivate` | admin | ídem para fichas sin usuario |
| `POST /agents/delete/{agent_id}` | admin | se mantiene **solo** el camino multiempresa ("quitar de esta empresa"); si el agente está en una sola empresa responde `?error=use_offboarding` ("Dale de baja en lugar de eliminarlo") salvo que no tenga historial, en cuyo caso borra. |

### 6.1 JSON del resumen

```json
{
  "name": "Juan Pérez",
  "blocked": true,
  "has_history": true,
  "companies": [
    {"id": 1, "code": "MOYZA", "name": "MOYZA", "live_properties": 3, "open_alerts": 5,
     "properties_url": "/properties?agent_id=12",
     "targets": [{"id": 7, "name": "Ana López"}]}
  ]
}
```

`properties_url` apunta al listado de propiedades filtrado por el agente en esa empresa
(comprobar el nombre real del parámetro en `routes/properties.py`; si el listado no admite
filtro por agente, añadir `agent_id` como filtro de query en esa ruta).

El admin ve todas las empresas, así que el modal pinta todas las del agente, no solo la activa.

## 7. Interfaz (fase C) — cargar el skill `moyza-ui-ux-pro`

### 7.1 `/auth` (Usuarios)

- Badge de estado con `ui.badge`: "Activo" (green) / "Baja" (gray) + fecha `deactivated_at` en
  `title`. Fila/tarjeta inactiva con `opacity-60`.
- Acciones por usuario (tabla y tarjetas móviles):
  - Activo: Editar · Contraseña · **Dar de baja** (abre `userDeactivateModal`) · Eliminar solo
    si `not has_history` (el listado recibe `history_by_user_id` del servicio).
  - Inactivo: **Reactivar** (form POST con `confirm`) · Eliminar solo sin historial.
  - El propio admin (`current_user.id == user.id`) no tiene Dar de baja ni Eliminar.
- Modal `userDeactivateModal` (`ui.modal`, size `lg`) en `auth/user_modals.html`:
  1. Al abrir, `fetch('/auth/users/{id}/offboarding')` y pinta por empresa una tarjeta con
     `live_properties`, `open_alerts` y, si `open_alerts > 0`, un `<select name="reassign_to_<id>">`
     con `targets` (obligatorio).
  2. Si `blocked`: `ui.banner` ámbar "Tiene N propiedades activas en MOYZA. Reasígnalas desde
     Propiedades antes de dar de baja" con enlace a `properties_url`; botón de confirmar
     deshabilitado.
  3. Si no está bloqueado: campo `reason` opcional y botón "Dar de baja" (variante `danger`),
     `data-once`.
  4. Estado de carga (skeleton) y de error de red.
- Flash de error de `create_user` cuando el email pertenece a un inactivo.

### 7.2 `/agents` (Agentes)

- `agents/table.html`: badge "Baja" para `not agent.is_active`; el botón "Eliminar" se sustituye
  por:
  - ficha con usuario (`agent.email` coincide con un `User`): enlace "Gestionar en Usuarios"
    (`/auth`);
  - ficha sin usuario: "Dar de baja" (mismo modal, alimentado por
    `/agents/{id}/offboarding`) o "Reactivar";
  - en multiempresa, además "Quitar de MOYZA/MOES" (lo que hoy hace `/agents/delete`).
- `agents/home.html`: nuevo texto para `error == "use_offboarding"`.

### 7.3 Login

`auth/login.html` ya pinta `error`; solo cambia el texto desde la ruta.

### 7.4 Después de tocar plantillas

`bash backend/scripts/build_css.sh` y `docker restart moyza_backend`; linter
`python .claude/skills/moyza-ui-ux-pro/scripts/ui_lint.py backend/app/web/templates`.

## 8. Pruebas (fase D)

- `tests/test_offboarding_service.py` (funciones puras y servicio con `SessionLocal` contra la
  BD del contenedor, con limpieza como `test_alert_assignment_routes.py`):
  - bloqueo con propiedad `Activa`; no bloqueo con `Vendida`;
  - reasignación de alertas abiertas con historial y notificación; cerradas intactas;
  - falta de destino → error; destino inactivo o de otra empresa → error;
  - `reactivate` restaura `is_active` y `deactivated_at`;
  - `has_history` True/False.
- `tests/test_offboarding_routes.py` (patrón HTTP de `test_alert_assignment_routes.py`):
  - login de inactivo → página de login con el mensaje; sesión viva → redirect a `/`;
  - `GET /auth/users/{id}/offboarding` devuelve el JSON; `POST deactivate` bloqueado /
    correcto; `POST reactivate`;
  - `create_user` con email inactivo → flash de error;
  - `delete` con historial → flash de error, sin 500;
  - el inactivo no aparece en `assignable_agents` ni en el select de captador; sí en el filtro
    del historial de cesiones con " (baja)".
- Ejecutar `docker exec moyza_backend python -m pytest tests -q` completo al final.

## 9. Orden de ejecución

| Fase | Contenido | Depende de |
|---|---|---|
| A | Migración + modelos + bloqueo de acceso + `active_agents` en los sitios de §4.3/§4.4 | — |
| B | `offboarding_service` + cambios en `user_service` + rutas de §6 | A (columnas) |
| C | Plantillas de §7 + CSS | contrato de §6 (puede ir en paralelo con B) |
| D | Tests de §8 + verificación en móvil (375 px) de los modales nuevos | A, B, C |

Fuera de alcance: baja por empresa desde Usuarios (se hace desde Agentes), reasignación de
propiedades en la app, cambios en las FK.
