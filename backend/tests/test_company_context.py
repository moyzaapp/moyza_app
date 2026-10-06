"""
Tests unitarios del soporte multiempresa (MOYZA / MOES PREMIUM).

No necesitan base de datos: cubren la resolución de la empresa activa,
la identidad de marca con valores por defecto, la validación de la
redirección del selector y los helpers de pertenencia.
"""
from types import SimpleNamespace

import pytest

from app.core.constants import CompanyCode
from app.services.company_service import branding_for
from app.services.company_service import companies_label
from app.services.company_service import company_ids_from_form
from app.services.company_scope import child_in_company
from app.services.company_scope import in_company
from app.services.company_scope import property_in_company
from app.web.dependencies.company import resolve_active_company
from app.web.routes.company import _safe_next


def company(code="MOYZA", name="MOYZA", id=1, **extra):
    base = dict(
        id=id,
        code=code,
        name=name,
        legal_name=None,
        tax_id=None,
        fiscal_address=None,
        phone=None,
        rgpd_text=None,
        logo_path=None,
        primary_color=None,
        document_prefix=None,
        email_sender_name=None,
        whatsapp_phone=None,
        is_active=True,
    )
    base.update(extra)
    return SimpleNamespace(**base)


MOYZA = company()
MOES = company(code="MOES", name="MOES PREMIUM", id=2, primary_color="#8A6D1F")


# ---------------------------------------------------------------------------
# Empresa activa (cookie + permitidas)
# ---------------------------------------------------------------------------

class TestResolveActiveCompany:

    def test_cookie_valida_gana(self):
        assert resolve_active_company([MOYZA, MOES], "MOES") is MOES

    def test_cookie_no_permitida_cae_a_moyza(self):
        assert resolve_active_company([MOYZA, MOES], "NOPE") is MOYZA

    def test_sin_cookie_cae_a_moyza(self):
        assert resolve_active_company([MOYZA, MOES], None) is MOYZA

    def test_usuario_solo_moes_ignora_cookie_moyza(self):
        """La cookie no puede abrir una empresa a la que el usuario no pertenece."""
        assert resolve_active_company([MOES], "MOYZA") is MOES

    def test_sin_empresas_devuelve_none(self):
        assert resolve_active_company([], "MOYZA") is None


# ---------------------------------------------------------------------------
# Redirección segura del selector
# ---------------------------------------------------------------------------

class TestSafeNext:

    @pytest.mark.parametrize("url", [
        "https://evil.com/x",
        "//evil.com/x",
        "javascript:alert(1)",
        "properties",          # relativa sin barra inicial
        "",
        None,
        "/switch-company",     # evitar bucle sobre el propio endpoint
    ])
    def test_rechaza_destinos_no_locales(self, url):
        assert _safe_next(url) == "/properties"

    def test_acepta_ruta_local_con_query(self):
        assert _safe_next("/alerts?tab=buyers") == "/alerts?tab=buyers"


# ---------------------------------------------------------------------------
# Identidad de marca con valores por defecto
# ---------------------------------------------------------------------------

class TestBranding:

    def test_none_devuelve_identidad_moyza(self):
        brand = branding_for(None)
        assert brand.code == CompanyCode.DEFAULT
        assert brand.name == "MOYZA"
        assert brand.legal_name == "Moyza 2012 S.L."
        assert brand.document_prefix == "MOYZA-VISIT"

    def test_campos_vacios_caen_a_defaults_pero_el_nombre_manda(self):
        brand = branding_for(MOES)
        assert brand.name == "MOES PREMIUM"
        assert brand.primary_color == "#8A6D1F"
        # Sin datos legales propios se reutilizan los de MOYZA (provisional)
        assert brand.legal_name == "Moyza 2012 S.L."
        # El texto RGPD se genera con el nombre de la empresa
        assert "Inmobiliaria MOES PREMIUM" in brand.rgpd_text
        assert "MOYZA" not in brand.rgpd_text
        assert "Inmobiliaria MOES PREMIUM" in brand.rgpd_consent_text

    def test_prefijo_por_defecto_deriva_del_codigo(self):
        assert branding_for(MOES).document_prefix == "MOES-VISIT"
        assert branding_for(MOES).document_id(7, 3) == "MOES-VISIT-7-3"

    def test_rgpd_personalizado_se_respeta(self):
        custom = company(code="MOES", name="MOES PREMIUM", id=2, rgpd_text="Texto propio")
        assert branding_for(custom).rgpd_text == "Texto propio"

    def test_logo_url_se_traduce_a_ruta_de_disco(self):
        brand = branding_for(company(logo_path="/static/logo_moyza.png"))
        path = brand.logo_fs_path
        assert path is None or path.endswith("app/static/logo_moyza.png")

    def test_logo_inexistente_devuelve_none(self):
        assert branding_for(company(logo_path="/static/no_existe.png")).logo_fs_path is None


# ---------------------------------------------------------------------------
# Pertenencia y helpers de formulario
# ---------------------------------------------------------------------------

class TestMembershipHelpers:

    def test_in_company_con_company_id(self):
        assert in_company(SimpleNamespace(company_id=2), 2)
        assert not in_company(SimpleNamespace(company_id=1), 2)

    def test_in_company_con_relacion_n_a_m(self):
        agent = SimpleNamespace(companies=[MOYZA, MOES])
        assert in_company(agent, 2)
        assert not in_company(SimpleNamespace(companies=[MOYZA]), 2)

    def test_in_company_none(self):
        assert not in_company(None, 1)

    def test_child_in_company_usa_la_propiedad(self):
        visit = SimpleNamespace(property=SimpleNamespace(company_id=2))
        assert child_in_company(visit, 2)
        assert not child_in_company(visit, 1)
        assert not child_in_company(SimpleNamespace(property=None), 1)
        assert not property_in_company(None, 1)

    def test_companies_label(self):
        assert companies_label([MOYZA, MOES]) == "MOYZA, MOES PREMIUM"
        assert companies_label([]) == ""

    def test_company_ids_from_form_ignora_basura(self):
        class Form:
            def getlist(self, key):
                return ["1", "x", "", "2"]

        assert company_ids_from_form(Form()) == [1, 2]
