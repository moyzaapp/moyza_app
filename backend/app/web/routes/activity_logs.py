from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from app.web.template_env import templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, case, or_

from app.db.deps import get_db
from app.models.user_activity_log import UserActivityLog
from app.models.user import User
from app.services import activity_log_view as view

router = APIRouter()


def _count_if(condition):
    """Suma condicional portable (PostgreSQL y SQLite)."""
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


@router.get("/activity-logs", response_class=HTMLResponse)
async def activity_logs(
    request: Request,
    period: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    module: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Actividad de usuarios (solo admin).

    El registro guarda una fila por petición; aquí se enseña traducido a
    acciones (`app.services.activity_log_view`), filtrable por período,
    usuario, tipo, módulo y texto, y paginado. Por defecto: últimos 7 días y
    sin ruido técnico. El resumen por usuario y los indicadores se calculan
    sobre el período elegido (no dependen del resto de filtros).
    """
    from app.web.dependencies.auth import require_admin_role

    admin_user = require_admin_role(request, db)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    span = view.resolve_period(period, date_from, date_to)
    kind = kind if kind in dict(view.KINDS) else view.DEFAULT_KIND
    module = module if module in view.MODULES else ""
    q = (q or "").strip()
    try:
        selected_user_id = int(user_id) if user_id else None
    except ValueError:
        selected_user_id = None

    in_period = [
        UserActivityLog.created_at >= span["start"],
        UserActivityLog.created_at < span["end"],
    ]

    # ----- Indicadores y resumen por usuario: todo el período -----
    is_view, is_change = view.view_clause(), view.change_clause()
    is_phone, is_error = view.phone_clause(), view.error_clause()
    is_login = (UserActivityLog.path == "/login") & (UserActivityLog.method == "POST") \
        & (UserActivityLog.status_code >= 300) & (UserActivityLog.status_code < 400)

    user_stats = (
        db.query(
            UserActivityLog.user_id,
            User.full_name,
            User.email,
            _count_if(is_view).label("views"),
            _count_if(is_change).label("changes"),
            _count_if(is_phone).label("phone_checks"),
            _count_if(is_error).label("errors"),
            func.max(UserActivityLog.created_at).label("last_seen"),
        )
        .join(User, User.id == UserActivityLog.user_id)
        .filter(*in_period, ~view.noise_clause())
        .group_by(UserActivityLog.user_id, User.full_name, User.email)
        .order_by(desc("last_seen"))
        .all()
    )

    totals = db.query(
        _count_if(is_change), _count_if(is_phone), _count_if(is_error), _count_if(is_login),
    ).filter(*in_period).one()

    kpis = {
        "active_users": len(user_stats),
        "changes": int(totals[0]),
        "phone_checks": int(totals[1]),
        "errors": int(totals[2]),
        "logins": int(totals[3]),
    }

    # ----- Registro filtrado y paginado -----
    logs_query = db.query(UserActivityLog).filter(*in_period)

    kind_condition = view.kind_clause(kind)
    if kind_condition is not None:
        logs_query = logs_query.filter(kind_condition)

    module_condition = view.module_clause(module)
    if module_condition is not None:
        logs_query = logs_query.filter(module_condition)

    if selected_user_id is not None:
        logs_query = logs_query.filter(UserActivityLog.user_id == selected_user_id)

    if q:
        pattern = f"%{q}%"
        logs_query = logs_query.outerjoin(User, User.id == UserActivityLog.user_id).filter(or_(
            UserActivityLog.path.ilike(pattern),
            UserActivityLog.ip_address.ilike(pattern),
            User.full_name.ilike(pattern),
            User.email.ilike(pattern),
        ))

    pagination = view.paginate(page, logs_query.count())

    logs = (
        logs_query
        .options(joinedload(UserActivityLog.user))
        .order_by(desc(UserActivityLog.created_at), desc(UserActivityLog.id))
        .offset(pagination["offset"])
        .limit(pagination["per_page"])
        .all()
    )

    rows = []
    for log in logs:
        info = view.describe(log.method, log.path, log.status_code)
        rows.append({
            "log": log,
            "module": info["module"],
            "label": info["label"],
            "detail": info["detail"],
            "href": info["href"],
            "kind_badge": view.KIND_BADGES[info["kind"]],
            "outcome": view.outcome(log.status_code),
        })

    # Selector de usuario: todos los que tienen actividad registrada alguna vez
    users = (
        db.query(User.id, User.full_name, User.email)
        .filter(User.id.in_(db.query(UserActivityLog.user_id).filter(UserActivityLog.user_id.isnot(None))))
        .order_by(User.full_name)
        .all()
    )

    filters = {
        "period": span["period"],
        "date_from": span["date_from"].isoformat(),
        "date_to": span["date_to"].isoformat(),
        "user_id": selected_user_id,
        "kind": kind,
        "module": module,
        "q": q,
    }
    # Query string de los filtros activos, para que los enlaces los conserven
    base_qs = {}
    if span["period"] == "custom":
        base_qs.update(date_from=filters["date_from"], date_to=filters["date_to"])
    elif span["period"] != view.DEFAULT_PERIOD:
        base_qs["period"] = span["period"]
    if selected_user_id is not None:
        base_qs["user_id"] = selected_user_id
    if kind != view.DEFAULT_KIND:
        base_qs["kind"] = kind
    if module:
        base_qs["module"] = module
    if q:
        base_qs["q"] = q

    has_filters = bool(
        selected_user_id is not None or module or q
        or kind != view.DEFAULT_KIND or span["period"] != view.DEFAULT_PERIOD
    )

    return templates.TemplateResponse(
        request=request,
        name="activity_logs/list.html",
        context={
            "request": request,
            "rows": rows,
            "pagination": pagination,
            "user_stats": user_stats,
            "kpis": kpis,
            "users": users,
            "filters": filters,
            "base_qs": base_qs,
            "has_filters": has_filters,
            "span": span,
            "kinds": view.KINDS,
            "periods": view.PERIODS,
            "modules": [(key, label) for key, (label, _prefixes) in view.MODULES.items()],
            "current_user": request.state.user,
        },
    )
