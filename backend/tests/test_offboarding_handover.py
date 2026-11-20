"""
Reparto de compradores antes de la baja (pantalla "Repartir compradores",
`/agents/{id}/handover`; `offboarding_service.handover_*`).

En lugar de mandar todas las alertas abiertas a un solo agente desde el modal
de baja, el admin marca grupos y elige a quién va cada uno, o las elimina.
Mismos datos y ayudantes que tests/test_offboarding_service.py (contra la BD;
se omiten si no responde). La prueba HTTP se omite si la app no está levantada.

    docker exec moyza_backend python -m pytest tests/test_offboarding_handover.py -q
"""
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest

from tests.test_offboarding_service import (  # noqa: F401  (ctx y db son fixtures)
    _admin,
    _alert,
    _person,
    _property,
    ctx,
    db,
)

BASE_URL = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")


def _svc():
    from app.services import offboarding_service
    return offboarding_service


def _reload(db, alert):
    from app.models.property_alert import PropertyAlert
    db.expire_all()
    return db.get(PropertyAlert, alert.id)


# ---------------------------------------------------------------------------
# Listado por empresa
# ---------------------------------------------------------------------------

def test_grupos_por_empresa_con_carga_de_cada_destino(db, ctx):
    svc = _svc()
    _user, leaving = _person(db, ctx, "sale", codes=("MOYZA", "MOES"))
    _u, ana = _person(db, ctx, "ana")
    _u, bea = _person(db, ctx, "bea")
    _u, inactive = _person(db, ctx, "baja", active=False)
    mine = [_alert(db, ctx, leaving, "PENDING"), _alert(db, ctx, leaving, "IN_PROGRESS")]
    moes_alert = _alert(db, ctx, leaving, "PENDING", code="MOES")
    _alert(db, ctx, leaving, "COMPLETED")          # cerrada: no se reparte
    _alert(db, ctx, ana, "PENDING")
    _alert(db, ctx, ana, "IN_PROGRESS")
    _alert(db, ctx, ana, "COMPLETED")              # cerrada: no cuenta como carga

    groups = svc.handover_groups(db, leaving)
    assert [g.company.code for g in groups] == ["MOYZA", "MOES"]
    moyza, moes = groups
    assert [a.id for a in moyza.alerts] == [a.id for a in mine]
    assert [a.id for a in moes.alerts] == [moes_alert.id]

    load = {t.agent.id: t.open_alerts for t in moyza.targets}
    assert load[ana.id] == 2 and load[bea.id] == 0
    # Ni el propio ni los dados de baja son destino
    assert leaving.id not in load and inactive.id not in load

    assert svc.handover_groups(db, bea) == []      # sin compradores abiertos


def test_resumen_del_modal_enlaza_al_reparto(db, ctx):
    svc = _svc()
    user, leaving = _person(db, ctx, "enlace", codes=("MOYZA", "MOES"))
    _alert(db, ctx, leaving, "PENDING")
    data = svc.summary_to_dict(svc.summary_for_user(db, user))
    by_code = {c["code"]: c for c in data["companies"]}
    assert by_code["MOYZA"]["handover_url"] == f"/agents/{leaving.id}/handover"
    assert by_code["MOES"]["handover_url"] is None   # sin compradores abiertos en MOES


# ---------------------------------------------------------------------------
# Reasignar los marcados
# ---------------------------------------------------------------------------

def test_reparto_entre_dos_agentes_y_baja_sin_destino(db, ctx):
    from app.models.alert_assignment_log import AlertAssignmentLog
    svc = _svc()
    user, leaving = _person(db, ctx, "reparte")
    _u, ana = _person(db, ctx, "ana")
    _u, bea = _person(db, ctx, "bea")
    a1, a2, a3 = (_alert(db, ctx, leaving, "IN_PROGRESS") for _ in range(3))

    target, ids = svc.handover_reassign(db, leaving, company_id=ctx["moyza_id"],
                                        alert_ids=[str(a1.id), str(a2.id)], target_id=str(ana.id),
                                        by_user=_admin(db, ctx))
    assert target.id == ana.id and sorted(ids) == sorted([a1.id, a2.id])
    target, ids = svc.handover_reassign(db, leaving, company_id=ctx["moyza_id"],
                                        alert_ids=[a3.id], target_id=bea.id, by_user=_admin(db, ctx))
    assert ids == [a3.id]

    assert [_reload(db, a).agent_id for a in (a1, a2, a3)] == [ana.id, ana.id, bea.id]
    # Misma reasignación que en Compradores: pendiente, con historial y motivo
    moved = _reload(db, a1)
    assert moved.status == "PENDING" and moved.previous_agent_id == leaving.id
    log = db.query(AlertAssignmentLog).filter_by(alert_id=a1.id).one()
    assert (log.from_agent_id, log.to_agent_id) == (leaving.id, ana.id)
    assert log.reason == f"Reparto por baja de {leaving.name}"

    # Ya no le queda nada: la baja no pide destino
    assert svc.handover_groups(db, leaving) == []
    summary = svc.deactivate(db, user=user, by_user=_admin(db, ctx), reassign_to={})
    assert summary.reassigned == [] and user.is_active is False


def test_reasignar_rechazos_no_tocan_nada(db, ctx):
    svc = _svc()
    _user, leaving = _person(db, ctx, "rechazo")
    _u, ana = _person(db, ctx, "ana")
    _u, other = _person(db, ctx, "otro")
    _u, moes_agent = _person(db, ctx, "moes", codes=("MOES",))
    _u, inactive = _person(db, ctx, "baja", active=False)
    mine = _alert(db, ctx, leaving, "PENDING")
    foreign = _alert(db, ctx, other, "PENDING")      # de otro agente
    closed = _alert(db, ctx, leaving, "COMPLETED")
    admin = _admin(db, ctx)

    def reassign(alert_ids, target_id, company_id=None):
        return svc.handover_reassign(db, leaving, company_id=company_id or ctx["moyza_id"],
                                     alert_ids=alert_ids, target_id=target_id, by_user=admin)

    cases = [
        ([], ana.id, "Marca al menos un comprador"),
        ([mine.id], None, "Elige a qué agente"),
        ([mine.id], leaving.id, "no es un agente activo"),        # a sí mismo
        ([mine.id], inactive.id, "no es un agente activo"),
        ([mine.id], moes_agent.id, "no es un agente activo"),     # no es de la empresa
        ([foreign.id, closed.id], ana.id, "ya no están abiertos a su nombre"),
    ]
    for alert_ids, target_id, text in cases:
        with pytest.raises(svc.OffboardingError, match=text):
            reassign(alert_ids, target_id)
    # Empresa equivocada: la alerta es de MOYZA
    with pytest.raises(svc.OffboardingError, match="ya no están abiertos"):
        reassign([mine.id], moes_agent.id, company_id=ctx["moes_id"])

    assert _reload(db, mine).agent_id == leaving.id
    assert _reload(db, foreign).agent_id == other.id

    # Marcando una suya y una ajena, solo se mueve la suya
    _target, ids = reassign([mine.id, foreign.id], ana.id)
    assert ids == [mine.id] and _reload(db, foreign).agent_id == other.id


# ---------------------------------------------------------------------------
# Eliminar los marcados
# ---------------------------------------------------------------------------

def test_eliminar_solo_las_marcadas_y_suyas(db, ctx):
    from app.models.alert_follow_up import AlertFollowUp
    from app.models.property_alert import PropertyAlert
    svc = _svc()
    _user, leaving = _person(db, ctx, "borra")
    _u, other = _person(db, ctx, "otro")
    doomed, kept = _alert(db, ctx, leaving, "PENDING"), _alert(db, ctx, leaving, "PENDING")
    foreign = _alert(db, ctx, other, "PENDING")
    db.add(AlertFollowUp(alert_id=doomed.id, action_type="CONTACTADO", notes="x", created_by=ctx["admin_id"]))
    db.commit()
    doomed_id = doomed.id

    ids = svc.handover_delete(db, leaving, company_id=ctx["moyza_id"], alert_ids=[doomed_id, foreign.id])
    assert ids == [doomed_id]
    db.expire_all()
    assert db.get(PropertyAlert, doomed_id) is None
    assert db.query(AlertFollowUp).filter_by(alert_id=doomed_id).count() == 0
    assert db.get(PropertyAlert, kept.id) is not None and db.get(PropertyAlert, foreign.id) is not None

    with pytest.raises(svc.OffboardingError, match="Marca al menos un comprador"):
        svc.handover_delete(db, leaving, company_id=ctx["moyza_id"], alert_ids=[])


# ---------------------------------------------------------------------------
# Pantalla (HTTP contra la app levantada)
# ---------------------------------------------------------------------------

def _server_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=3)
        return True
    except Exception:
        return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _http(email, path, data=None):
    from app.core.security import create_access_token
    body = urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None
    request = urllib.request.Request(BASE_URL + path, data=body)
    request.add_header("Cookie", f"access_token={create_access_token({'sub': email})}; active_company=MOYZA")
    try:
        response = urllib.request.build_opener(_NoRedirect).open(request, timeout=20)
        return response.status, response.read().decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace"), error.headers.get("location", "")


@pytest.mark.skipif(not _server_up(), reason=f"La app no responde en {BASE_URL}")
def test_pantalla_lista_reparte_y_solo_admin(db, ctx):
    user, leaving = _person(db, ctx, "http")
    _u, ana = _person(db, ctx, "ana")
    prop = _property(db, ctx, ana, "Vendida")
    first, second = _alert(db, ctx, leaving, "PENDING", prop=prop), _alert(db, ctx, leaving, "IN_PROGRESS")
    path = f"/agents/{leaving.id}/handover"

    status, html, _ = _http(ADMIN_EMAIL, path)
    assert status == 200
    for text in ("Repartir compradores", leaving.name, first.lead_name, second.lead_name, prop.title,
                 "Búsqueda general", f'value="{first.id}"', f"{ana.name} · 0 abiertos",
                 "Reasignar marcados", "Eliminar marcados…", "Volver a Usuarios"):
        assert text in html, text

    # Un agente no entra ni reparte
    status, _html, location = _http(user.email, path)
    assert status in (302, 303) and "handover" not in location
    status, _html, _ = _http(user.email, path, {"company_id": ctx["moyza_id"], "alert_ids": [first.id],
                                                "target_agent_id": ana.id, "action": "reassign"})
    assert status in (302, 303) and _reload(db, first).agent_id == leaving.id

    # El admin reasigna una y la pantalla vuelve con la que queda
    status, _html, location = _http(ADMIN_EMAIL, path, {
        "company_id": ctx["moyza_id"], "alert_ids": [first.id], "target_agent_id": ana.id, "action": "reassign"})
    assert status == 303 and location == path
    assert _reload(db, first).agent_id == ana.id
    status, html, _ = _http(ADMIN_EMAIL, path)
    assert first.lead_name not in html and second.lead_name in html

    # Eliminar la otra: ya no queda nada
    status, _html, _ = _http(ADMIN_EMAIL, path, {
        "company_id": ctx["moyza_id"], "alert_ids": [second.id], "action": "delete"})
    assert status == 303
    status, html, _ = _http(ADMIN_EMAIL, path)
    assert "No le queda ningún comprador abierto" in html
