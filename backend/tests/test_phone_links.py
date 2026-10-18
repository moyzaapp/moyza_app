"""
Botón de WhatsApp en el detalle de la alerta (PLAN_WHATSAPP_ALERTA.md).

- Función pura `app.core.phone.whatsapp_url`: tabla de casos del plan.
- Filtro Jinja registrado en el entorno de plantillas de la app.
- Render de `alerts/detail.html` con objetos falsos (SimpleNamespace): sin base
  de datos ni app levantada.

    cd backend && python -m pytest tests/test_phone_links.py -q
"""
import re
from datetime import datetime
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.core.constants import AlertStatus, AlertType, FollowUpActionType
from app.core.phone import whatsapp_url


# ---------------------------------------------------------------------------
# Función pura
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phone, expected", [
    ("600123456", "https://wa.me/34600123456"),
    ("+34 600 12 34 56", "https://wa.me/34600123456"),
    ("34600123456", "https://wa.me/34600123456"),
    ("0034 600123456", "https://wa.me/34600123456"),
    ("+57 300 123 4567", "https://wa.me/573001234567"),
    ("953 94 09 56", "https://wa.me/34953940956"),  # fijo español
    ("12345", None),
    ("", None),
    (None, None),
    ("sin teléfono", None),
])
def test_tabla_de_casos_del_plan(phone, expected):
    assert whatsapp_url(phone) == expected


@pytest.mark.parametrize("phone, expected", [
    # Con + o 00 se respeta el indicativo aunque no esté en el selector de país
    ("+41 79 123 45 67", "https://wa.me/41791234567"),
    ("0041 79 123 45 67", "https://wa.me/41791234567"),
    ("(+34) 600-123-456", "https://wa.me/34600123456"),
    # Indicativo explícito con la parte local incompleta
    ("+34 12345", None),
    # Dos teléfonos en el mismo campo: más de 15 dígitos (E.164), no se adivina
    ("600123456 / 611222333", None),
    # El teléfono puede llegar como número
    (600123456, "https://wa.me/34600123456"),
])
def test_casos_limite(phone, expected):
    assert whatsapp_url(phone) == expected


def test_sin_mensaje_prellenado():
    assert "?" not in whatsapp_url("600123456")


def test_filtro_registrado_en_plantillas():
    from app.web.template_env import templates
    assert templates.env.filters["whatsapp_url"] is whatsapp_url
    rendered = templates.env.from_string("{{ phone | whatsapp_url }}").render(phone="+34 600 12 34 56")
    assert rendered == "https://wa.me/34600123456"


# ---------------------------------------------------------------------------
# Render de alerts/detail.html
# ---------------------------------------------------------------------------

def _render_detail(lead_phone, lead_name="Ana López"):
    """Renderiza el detalle como la ruta `alert_detail`, con objetos falsos."""
    from app.web.template_env import company_context, templates

    company = SimpleNamespace(name="MOYZA", code="MOYZA", primary_color="#000000")
    user = SimpleNamespace(
        id=1, email="admin@example.com", full_name="Admin", role=SimpleNamespace(name="admin"),
    )
    request = Request({
        "type": "http", "method": "GET", "scheme": "http", "server": ("testserver", 80),
        "path": "/alerts/7", "root_path": "", "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "state": {"user": user, "company": company, "allowed_companies": [company]},
    })
    agent = SimpleNamespace(id=3, name="Agente Uno")
    alert = SimpleNamespace(
        id=7, lead_name=lead_name, lead_phone=lead_phone, lead_email=None, source=None,
        alert_type=None, message=None, status=AlertStatus.PENDING, priority="NORMAL",
        created_at=datetime(2026, 10, 1, 10, 0), read_at=None, completed_at=None,
        agent_id=agent.id, agent=agent, assigned_by_user=None, assigned_at=None,
        previous_agent=None, assignment_reason=None, assignment_logs=[],
        property=SimpleNamespace(id=5, title="Piso Centro", address="Calle Real 1", price=None, agent=agent),
    )
    context = {
        "request": request,
        "alert": alert,
        "follow_ups": [],
        "current_user": user,
        "alert_locked": False,
        "is_admin": True,
        "can_complete": False,
        "can_reassign": False,
        "assignable_groups": [],
        "FollowUpActionType": FollowUpActionType,
        "follow_up_labels": FollowUpActionType.labels(),
        "AlertStatus": AlertStatus,
        "stage_badge_color": FollowUpActionType.stage_badge_color,
        "follow_up_users": {},
        "alert_type_labels": {AlertType.OTRO: "Otro"},
        **company_context(request),
    }
    return templates.env.get_template("alerts/detail.html").render(context)


def _whatsapp_links(html):
    return re.findall(r'<a href="https://wa\.me/[^"]*"[^>]*>', html)


def test_detalle_con_telefono_muestra_boton():
    html = _render_detail("600123456")

    # El número sigue igual, con su enlace tel:
    assert re.search(r'<a href="tel:600123456"[^>]*>\s*600123456\s*</a>', html)

    links = _whatsapp_links(html)
    assert len(links) == 1
    link = links[0]
    assert 'href="https://wa.me/34600123456"' in link
    assert 'target="_blank"' in link
    assert 'rel="noopener noreferrer"' in link
    assert 'aria-label="Abrir chat de WhatsApp con Ana López"' in link
    # Botón secundario del sistema de diseño (macro ui.button), nada de verde
    assert "bg-white border border-gray-300" in link
    assert "py-2.5" in link
    assert "green" not in link

    # Icono Heroicons decorativo + texto visible
    button = html[html.index(link):]
    button = button[:button.index("</a>")]
    assert '<svg class="w-5 h-5" aria-hidden="true"' in button
    assert 'stroke-width="1.5"' in button
    assert button.rstrip().endswith("WhatsApp")


def test_detalle_escapa_el_nombre_en_aria_label():
    html = _render_detail("600123456", lead_name='Ana "La Jefa" <b>')
    link = _whatsapp_links(html)[0]
    assert 'aria-label="Abrir chat de WhatsApp con Ana &#34;La Jefa&#34; &lt;b&gt;"' in link


def test_detalle_con_telefono_incompleto_sin_boton():
    html = _render_detail("12345")
    assert re.search(r'<a href="tel:12345"[^>]*>\s*12345\s*</a>', html)
    assert "wa.me" not in html
    assert "WhatsApp" not in html


def test_detalle_sin_telefono_sin_bloque():
    html = _render_detail(None)
    assert "Teléfono</label>" not in html
    assert 'href="tel:' not in html
    assert "wa.me" not in html
