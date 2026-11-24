"""Datos de prueba coherentes para MOYZA y MOES PREMIUM.

Crea agentes (con usuario para entrar, clave 123456), propietarios,
propiedades con direcciones españolas, compradores con perfil de búsqueda,
alertas en distintos estados (sin gestionar, volver a llamar, contactado,
visita programada, oferta, cerrada), seguimientos, visitas, bajadas de
precio, cierres, objetivos del período y avisos de campana.

Todo lo que crea lleva una marca (dominios ``@demo-...`` en correos,
referencias ``DEMO-``) para poder borrarlo y volver a cargarlo sin tocar
nada más.

Uso (dentro del contenedor):

    python scripts/seed_demo_data.py            # carga (borra antes lo demo)
    python scripts/seed_demo_data.py --reset    # solo borra lo demo
    python scripts/seed_demo_data.py --keep     # carga sin borrar lo demo previo

Solo para entornos de prueba: nunca en producción.
"""
import argparse
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import or_, text  # noqa: E402

import app.db.base  # noqa: E402,F401  (carga todos los modelos antes de importarlos sueltos)

from app.core.constants import (  # noqa: E402
    AlertOrigin,
    AlertStatus,
    BusinessType,
    FollowUpActionType,
    PeriodType,
    PropertyStatus,
)
from app.core.password import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.agent import Agent  # noqa: E402
from app.models.agent_performance_target import AgentPerformanceTarget  # noqa: E402
from app.models.alert_assignment_log import AlertAssignmentLog  # noqa: E402
from app.models.alert_follow_up import AlertFollowUp  # noqa: E402
from app.models.alert_property import AlertProperty  # noqa: E402
from app.models.buyer import Buyer  # noqa: E402
from app.models.buyer_search_criteria import BuyerSearchCriteria  # noqa: E402
from app.models.client import Client  # noqa: E402
from app.models.closing import Closing  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.notification import Notification  # noqa: E402
from app.models.property import Property  # noqa: E402
from app.models.property_alert import PropertyAlert  # noqa: E402
from app.models.property_price_history import PropertyPriceHistory  # noqa: E402
from app.models.property_visit import PropertyVisit  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.company_service import companies_label  # noqa: E402
from app.services.notification_service import NotificationKind, notify, users_for_agent  # noqa: E402
from app.services.performance_report_service import PerformanceReportService  # noqa: E402

PASSWORD = "123456"

AGENT_DOMAINS = ("@demo-moyza.es", "@demo-moes.es", "@demo-ambas.es")
CLIENT_DOMAIN = "@demo-propietarios.es"
BUYER_DOMAIN = "@demo-compradores.es"
REF_PREFIX = "DEMO-"
DEMO_TAG = "[DEMO]"

NOW = datetime.utcnow()


def days_ago(days: float, hour: int = 10) -> datetime:
    """Fecha UTC naive a las `hour` de hace `days` días (horas hábiles de mañana)."""
    base = NOW - timedelta(days=days)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0)


def hours_ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Catálogo de datos
# ---------------------------------------------------------------------------

# (nombre, email, teléfono, zona, empresas, empresa principal)
AGENTS = [
    ("Lucía Fernández García", "lucia.fernandez@demo-moyza.es", "34611100101", "Jaén centro y Bulevar", ["MOYZA"], "MOYZA"),
    ("Carlos Ruiz Molina", "carlos.ruiz@demo-moyza.es", "34611100102", "Jaén norte y Granada", ["MOYZA"], "MOYZA"),
    ("Marta López Serrano", "marta.lopez@demo-moyza.es", "34611100103", "Comarcas de Jaén", ["MOYZA"], "MOYZA"),
    ("Javier Martínez Ortega", "javier.martinez@demo-moes.es", "34622200201", "Jaén premium", ["MOES"], "MOES"),
    ("Elena Sánchez Navarro", "elena.sanchez@demo-moes.es", "34622200202", "Costa y Sevilla", ["MOES"], "MOES"),
    ("Pablo Jiménez Cano", "pablo.jimenez@demo-moes.es", "34622200203", "Madrid y Málaga", ["MOES"], "MOES"),
    ("Andrés Moreno Vega", "andres.moreno@demo-ambas.es", "34633300301", "Jaén y Granada", ["MOYZA", "MOES"], "MOYZA"),
]

# (nombre, email, teléfono, empresas)
CLIENTS = [
    ("Antonio Garrido Peña", "antonio.garrido", "34953220101", ["MOYZA"]),
    ("María del Carmen Ruiz Delgado", "mcarmen.ruiz", "34600111222", ["MOYZA"]),
    ("José Luis Montoro Cabrera", "joseluis.montoro", "34600111333", ["MOYZA"]),
    ("Inmaculada Torres Vílchez", "inmaculada.torres", "34600111444", ["MOYZA", "MOES"]),
    ("Francisco Javier Ortega Lara", "fjavier.ortega", "34600222111", ["MOES"]),
    ("Rosario Medina Cobo", "rosario.medina", "34600222333", ["MOES"]),
    ("Herederos de Ramón Quesada, S.L.", "herederos.quesada", "34953222444", ["MOES"]),
    ("Pilar Castellano Nieto", "pilar.castellano", "34600111555", ["MOYZA"]),
]

# Propiedades: dict por campo. `agent` y `client` son índices de AGENTS / CLIENTS.
# `entry` = días atrás de la fecha de alta (market_entry_date / fecha_alta).
PROPERTIES = [
    # ---------------- MOYZA ----------------
    dict(ref="DEMO-MOY-001", company="MOYZA", agent=0, client=0, title="Piso de 3 dormitorios en el Bulevar",
         address="Calle Fuente del Alamillo 12, 3ºB, 23009 Jaén", city="Jaén", zona="Bulevar", cp="23009",
         type="Piso", op="Venta", price=189000, m2=110, m2c=118, dorm=3, banos=2, salones=1, terrazas=1,
         armarios=3, garaje=0, asc=1, estado="Buen estado", situacion="Libre", planta="3", entry=250,
         public_url="https://example.com/moyza/DEMO-MOY-001",
         desc="Piso exterior muy luminoso en pleno Bulevar, junto al Corte Inglés. Cocina amueblada y calefacción central."),
    dict(ref="DEMO-MOY-002", company="MOYZA", agent=1, client=1, title="Casa adosada en Expansión Norte",
         address="Calle Arquitecto Berges 8, 23007 Jaén", city="Jaén", zona="Expansión Norte", cp="23007",
         type="Casa", op="Venta", price=245000, m2=160, m2c=185, dorm=4, banos=3, salones=2, terrazas=1,
         armarios=4, garaje=1, asc=0, estado="Reformado", situacion="Libre", planta="", entry=228,
         desc="Adosado reformado en 2023 con patio y garaje. Zona tranquila junto al parque."),
    dict(ref="DEMO-MOY-003", company="MOYZA", agent=2, client=2, title="Ático con dos terrazas en el Centro",
         address="Calle Bernabé Soriano 21, Ático, 23001 Jaén", city="Jaén", zona="Centro", cp="23001",
         type="Ático", op="Venta", price=320000, m2=140, m2c=155, dorm=3, banos=2, salones=1, terrazas=2,
         armarios=3, garaje=1, asc=1, estado="Nuevo", situacion="Libre", planta="6", entry=185,
         public_url="https://example.com/moyza/DEMO-MOY-003",
         desc="Ático a estrenar con vistas a la Catedral. Dos terrazas, plaza de garaje y trastero."),
    dict(ref="DEMO-MOY-004", company="MOYZA", agent=0, client=3, title="Piso en alquiler en Peñamefécit",
         address="Avenida de Barcelona 34, 1ºA, 23008 Jaén", city="Jaén", zona="Peñamefécit", cp="23008",
         type="Piso", op="Alquiler", price=650, m2=85, m2c=92, dorm=2, banos=1, salones=1, terrazas=0,
         armarios=2, garaje=0, asc=0, estado="Buen estado", situacion="Libre", planta="1", entry=170,
         desc="Piso amueblado, sin ascensor, ideal para pareja. Gastos de comunidad incluidos."),
    dict(ref="DEMO-MOY-005", company="MOYZA", agent=1, client=0, title="Local comercial en Avenida de Andalucía",
         address="Avenida de Andalucía 55, bajo, 23006 Jaén", city="Jaén", zona="Avenida de Andalucía", cp="23006",
         type="Local", op="Alquiler", price=1200, m2=120, m2c=120, dorm=0, banos=1, salones=0, terrazas=0,
         armarios=0, garaje=0, asc=0, locales=1, estado="Buen estado", situacion="Libre", planta="Bajo", entry=151,
         desc="Local diáfano con dos escaparates a la avenida. Salida de humos."),
    dict(ref="DEMO-MOY-006", company="MOYZA", agent=6, client=7, title="Chalet con piscina en Las Fuentezuelas",
         address="Calle Mirasierra 4, 23005 Jaén", city="Jaén", zona="Fuentezuelas", cp="23005",
         type="Chalet", op="Venta", price=395000, m2=240, m2c=280, dorm=5, banos=3, salones=2, terrazas=2,
         armarios=5, garaje=2, asc=0, estado="Buen estado", situacion="Libre", planta="", entry=133,
         public_url="https://example.com/moyza/DEMO-MOY-006",
         desc="Chalet independiente con parcela de 600 m², piscina y barbacoa."),
    dict(ref="DEMO-MOY-007", company="MOYZA", agent=2, client=1, title="Piso a reformar en Linares",
         address="Calle Corredera de San Marcos 18, 2ºC, 23700 Linares", city="Linares", zona="Centro", cp="23700",
         type="Piso", op="Venta", price=98000, m2=95, m2c=102, dorm=3, banos=1, salones=1, terrazas=0,
         armarios=1, garaje=0, asc=1, estado="A reformar", situacion="Libre", planta="2", entry=98,
         desc="Piso céntrico para reformar a su gusto. Edificio con ascensor."),
    dict(ref="DEMO-MOY-008", company="MOYZA", agent=0, client=2, title="Casa en el casco histórico de Úbeda",
         address="Calle Real 40, 23400 Úbeda", city="Úbeda", zona="Casco Histórico", cp="23400",
         type="Casa", op="Venta", price=210000, m2=180, m2c=200, dorm=4, banos=2, salones=2, terrazas=1,
         armarios=2, garaje=0, asc=0, estado="Reformado", situacion="Libre", planta="", entry=76,
         desc="Casa de dos plantas con patio andaluz a dos calles de la Plaza Vázquez de Molina."),
    dict(ref="DEMO-MOY-009", company="MOYZA", agent=1, client=3, title="Piso de 3 dormitorios en el Zaidín",
         address="Calle Palencia 17, 4ºD, 18007 Granada", city="Granada", zona="Zaidín", cp="18007",
         type="Piso", op="Venta", price=175000, m2=90, m2c=98, dorm=3, banos=1, salones=1, terrazas=1,
         armarios=2, garaje=0, asc=1, estado="Buen estado", situacion="Libre", planta="4", entry=54,
         desc="Piso junto al Campus de la Salud, muy demandado para inversión."),
    dict(ref="DEMO-MOY-010", company="MOYZA", agent=2, client=7, title="Piso en alquiler en San Felipe",
         address="Calle Millán de Priego 72, 1ºB, 23004 Jaén", city="Jaén", zona="San Felipe", cp="23004",
         type="Piso", op="Alquiler", price=550, m2=70, m2c=76, dorm=2, banos=1, salones=1, terrazas=0,
         armarios=1, garaje=0, asc=0, estado="Buen estado", situacion="Libre", planta="1", entry=35,
         status=PropertyStatus.RESERVED,
         desc="Piso amueblado y equipado. Reservado con contrato de alquiler en firma."),
    dict(ref="DEMO-MOY-011", company="MOYZA", agent=6, client=0, title="Plaza de garaje en el Bulevar",
         address="Calle Doctor Eduardo Arroyo 9, plaza 14, 23009 Jaén", city="Jaén", zona="Bulevar", cp="23009",
         type="Garaje", op="Venta", price=14000, m2=12, m2c=12, dorm=0, banos=0, salones=0, terrazas=0,
         armarios=0, garaje=1, asc=1, estado="Buen estado", situacion="Libre", planta="-1", entry=21,
         desc="Plaza amplia para coche grande, acceso con mando."),
    dict(ref="DEMO-MOY-012", company="MOYZA", agent=0, client=1, title="Piso reservado en Martos",
         address="Avenida de la Paz 3, 2ºA, 23600 Martos", city="Martos", zona="Centro", cp="23600",
         type="Piso", op="Venta", price=120000, m2=100, m2c=108, dorm=3, banos=2, salones=1, terrazas=1,
         armarios=3, garaje=1, asc=1, estado="Buen estado", situacion="Libre", planta="2", entry=13,
         status=PropertyStatus.RESERVED,
         desc="Piso con garaje y trastero. Señal entregada, pendiente de notaría."),
    dict(ref="DEMO-MOY-013", company="MOYZA", agent=1, client=2, title="Piso reformado en Ciudad Jardín",
         address="Calle Antonio Maura 25, 5ºB, 14004 Córdoba", city="Córdoba", zona="Ciudad Jardín", cp="14004",
         type="Piso", op="Venta", price=230000, m2=115, m2c=125, dorm=3, banos=2, salones=1, terrazas=1,
         armarios=3, garaje=0, asc=1, estado="Reformado", situacion="Libre", planta="5", entry=6,
         desc="Captación reciente. Piso reformado íntegramente, orientación sur."),
    dict(ref="DEMO-MOY-014", company="MOYZA", agent=2, client=3, title="Piso vendido en el Centro",
         address="Calle Roldán y Marín 6, 2ºA, 23001 Jaén", city="Jaén", zona="Centro", cp="23001",
         type="Piso", op="Venta", price=150000, m2=88, m2c=95, dorm=2, banos=1, salones=1, terrazas=0,
         armarios=2, garaje=0, asc=1, estado="Buen estado", situacion="Libre", planta="2", entry=270,
         status=PropertyStatus.SOLD,
         desc="Vendido en noviembre. Operación cerrada por Marta y Lucía."),
    # ---------------- MOES PREMIUM ----------------
    dict(ref="DEMO-MOES-001", company="MOES", agent=3, client=4, title="Ático de lujo en el Bulevar",
         address="Paseo de España 15, Ático A, 23009 Jaén", city="Jaén", zona="Bulevar", cp="23009",
         type="Ático", op="Venta", price=450000, m2=180, m2c=200, dorm=4, banos=3, salones=2, terrazas=1,
         armarios=4, garaje=2, asc=1, estado="Nuevo", situacion="Libre", planta="8", entry=240,
         public_url="https://example.com/moes/DEMO-MOES-001",
         desc="Ático en la mejor zona de Jaén, acabados de alta gama, domótica y dos plazas de garaje."),
    dict(ref="DEMO-MOES-002", company="MOES", agent=4, client=5, title="Chalet independiente en Los Villares",
         address="Urbanización La Garza 12, 23160 Los Villares", city="Los Villares", zona="La Garza", cp="23160",
         type="Chalet", op="Venta", price=520000, m2=320, m2c=360, dorm=5, banos=4, salones=2, terrazas=3,
         armarios=6, garaje=2, asc=0, estado="Buen estado", situacion="Libre", planta="", entry=214,
         desc="Chalet con 2.000 m² de parcela, piscina de sal y vistas a Sierra Sur."),
    dict(ref="DEMO-MOES-003", company="MOES", agent=3, client=6, title="Villa en Nueva Andalucía",
         address="Calle Sierra Blanca 7, Urbanización Nueva Andalucía, 29660 Marbella", city="Marbella",
         zona="Nueva Andalucía", cp="29660", type="Chalet", op="Venta", price=1250000, m2=410, m2c=480,
         dorm=5, banos=5, salones=3, terrazas=4, armarios=7, garaje=3, asc=0, estado="Nuevo", situacion="Libre",
         planta="", entry=172, public_url="https://example.com/moes/DEMO-MOES-003",
         desc="Villa de obra nueva en el Valle del Golf, piscina infinita y vistas al mar."),
    dict(ref="DEMO-MOES-004", company="MOES", agent=5, client=4, title="Piso señorial en el barrio de Salamanca",
         address="Calle Velázquez 88, 4º Izq, 28006 Madrid", city="Madrid", zona="Salamanca", cp="28006",
         type="Piso", op="Venta", price=980000, m2=165, m2c=180, dorm=3, banos=2, salones=1, terrazas=0,
         armarios=4, garaje=0, asc=1, estado="Reformado", situacion="Libre", planta="4", entry=157,
         desc="Finca clásica con portero físico, techos altos y suelos de madera restaurados."),
    dict(ref="DEMO-MOES-005", company="MOES", agent=4, client=5, title="Ático en Los Remedios",
         address="Calle Asunción 40, Ático, 41011 Sevilla", city="Sevilla", zona="Los Remedios", cp="41011",
         type="Ático", op="Venta", price=540000, m2=150, m2c=165, dorm=3, banos=2, salones=1, terrazas=1,
         armarios=3, garaje=1, asc=1, estado="Buen estado", situacion="Libre", planta="7", entry=122,
         desc="Terraza de 40 m² con vistas al río. Garaje en la misma finca."),
    dict(ref="DEMO-MOES-006", company="MOES", agent=5, client=3, title="Piso en alquiler en la Plaza de la Constitución",
         address="Plaza de la Constitución 4, 3ºA, 23001 Jaén", city="Jaén", zona="Centro", cp="23001",
         type="Piso", op="Alquiler", price=950, m2=120, m2c=130, dorm=3, banos=2, salones=1, terrazas=0,
         armarios=3, garaje=0, asc=1, estado="Reformado", situacion="Libre", planta="3", entry=83,
         desc="Piso reformado en pleno centro, sin amueblar, calefacción individual de gas."),
    dict(ref="DEMO-MOES-007", company="MOES", agent=3, client=6, title="Casa señorial en Baeza",
         address="Calle San Pablo 22, 23440 Baeza", city="Baeza", zona="Casco Histórico", cp="23440",
         type="Casa", op="Venta", price=380000, m2=260, m2c=300, dorm=5, banos=3, salones=2, terrazas=1,
         armarios=3, garaje=1, asc=0, estado="A reformar", situacion="Libre", planta="", entry=64,
         desc="Casa palacio del XVIII con patio de columnas. Ideal para hotel boutique."),
    dict(ref="DEMO-MOES-008", company="MOES", agent=4, client=4, title="Oficina en Avenida de Madrid",
         address="Avenida de Madrid 37, 2ª planta, 23009 Jaén", city="Jaén", zona="Expansión Norte", cp="23009",
         type="Oficina", op="Alquiler", price=1400, m2=140, m2c=150, dorm=0, banos=2, salones=0, terrazas=0,
         armarios=0, garaje=0, asc=1, despachos=4, estado="Buen estado", situacion="Libre", planta="2", entry=43,
         desc="Oficina con cuatro despachos, sala de reuniones y aire acondicionado por conductos."),
    dict(ref="DEMO-MOES-009", company="MOES", agent=6, client=5, title="Dúplex en el Realejo",
         address="Cuesta del Realejo 9, 18009 Granada", city="Granada", zona="Realejo", cp="18009",
         type="Dúplex", op="Venta", price=365000, m2=130, m2c=142, dorm=3, banos=2, salones=1, terrazas=1,
         armarios=3, garaje=0, asc=0, estado="Reformado", situacion="Libre", planta="2", entry=27,
         desc="Dúplex con terraza y vistas a la Alhambra. Reforma de diseño."),
    dict(ref="DEMO-MOES-010", company="MOES", agent=5, client=6, title="Piso de diseño en el Soho",
         address="Calle Casas de Campos 11, 2ºB, 29001 Málaga", city="Málaga", zona="Soho", cp="29001",
         type="Piso", op="Venta", price=410000, m2=105, m2c=112, dorm=2, banos=2, salones=1, terrazas=1,
         armarios=2, garaje=0, asc=1, estado="Nuevo", situacion="Libre", planta="2", entry=8,
         desc="Captación reciente. Piso a estrenar a 5 minutos del puerto."),
    dict(ref="DEMO-MOES-011", company="MOES", agent=3, client=4, title="Chalet vendido en Las Fuentezuelas",
         address="Calle Peñas de Castro 3, 23005 Jaén", city="Jaén", zona="Fuentezuelas", cp="23005",
         type="Chalet", op="Venta", price=340000, m2=210, m2c=250, dorm=4, banos=3, salones=2, terrazas=2,
         armarios=4, garaje=2, asc=0, estado="Buen estado", situacion="Libre", planta="", entry=262,
         status=PropertyStatus.SOLD,
         desc="Vendido este mes. Operación cerrada por Javier."),
]

# Compradores: (nombre, email local, teléfono, empresa, perfil)
# El perfil cumple los mínimos nuevos (tipo, precio máx., dormitorios máx.,
# población concreta, zona si procede) salvo donde se indica.
BUYERS = [
    dict(name="Alberto Jiménez Roldán", email="alberto.jimenez", phone="34655010101", company="MOYZA",
         criteria=dict(type="Piso", op="Venta", min_price=120000, max_price=200000, min_bed=2, max_bed=3,
                       min_bath=1, elevator=True, cities=["Jaén"], zones=["Bulevar", "Centro"],
                       notes="Busca piso con ascensor cerca del Bulevar. Financiación preaprobada.")),
    dict(name="Raquel Ortiz Peralta", email="raquel.ortiz", phone="34655010102", company="MOYZA",
         criteria=dict(type="Casa", op="Venta", min_price=None, max_price=260000, min_bed=3, max_bed=4,
                       min_bath=2, elevator=None, cities=["Jaén"], zones=["Expansión Norte", "Fuentezuelas"],
                       notes="Familia con dos niños, quiere patio o jardín.")),
    dict(name="Daniel Moya Fernández", email="daniel.moya", phone="34655010103", company="MOYZA",
         criteria=dict(type="Ático", op="Venta", min_price=200000, max_price=350000, min_bed=2, max_bed=3,
                       min_bath=2, elevator=True, cities=["Jaén", "Córdoba"], zones=["Centro", "Ciudad Jardín"],
                       notes="Prefiere terraza grande. Vende su piso actual.")),
    dict(name="Nuria Castro Expósito", email="nuria.castro", phone="34655010104", company="MOYZA",
         criteria=dict(type="Piso", op="Alquiler", min_price=None, max_price=700, min_bed=2, max_bed=2,
                       min_bath=1, elevator=None, cities=["Jaén"], zones=["Peñamefécit", "San Felipe"],
                       notes="Entrada en enero. Tiene gato.")),
    dict(name="Sergio Lara Montiel", email="sergio.lara", phone="34655010105", company="MOYZA",
         criteria=dict(type="Chalet", op="Venta", min_price=250000, max_price=420000, min_bed=4, max_bed=5,
                       min_bath=2, elevator=None, cities=["Jaén"], zones=["Fuentezuelas"],
                       notes="Quiere piscina. Visita programada esta semana.")),
    dict(name="Carmen Aguilar Hidalgo", email="carmen.aguilar", phone="34655010106", company="MOYZA",
         criteria=dict(type="Piso", op="Venta", min_price=150000, max_price=190000, min_bed=3, max_bed=3,
                       min_bath=1, elevator=True, cities=["Granada"], zones=["Zaidín"],
                       notes="Inversión para alquilar a estudiantes. Ha hecho oferta.")),
    dict(name="Miguel Ángel Ramos Cruz", email="miguelangel.ramos", phone="34655010107", company="MOYZA",
         criteria=dict(type="Piso", op="Venta", min_price=None, max_price=160000, min_bed=2, max_bed=2,
                       min_bath=1, elevator=True, cities=["Jaén"], zones=["Centro"],
                       notes="Operación cerrada: compró Roldán y Marín 6.")),
    dict(name="Lorena Vílchez Marín", email="lorena.vilchez", phone="34655010108", company="MOYZA",
         criteria=dict(type="Piso", op="Venta", min_price=None, max_price=110000, min_bed=3, max_bed=3,
                       min_bath=1, elevator=True, cities=["Linares"], zones=["Centro"],
                       notes="Descartó: no quiere reformar.")),
    dict(name="Francisco Cano Robles", email="francisco.cano", phone="34655010109", company="MOYZA",
         criteria=dict(type="Casa", op="Venta", min_price=None, max_price=230000, min_bed=3, max_bed=4,
                       min_bath=2, elevator=None, cities=["Úbeda", "Baeza"], zones=["Casco Histórico"],
                       notes="Segunda residencia. Contactó por Idealista.")),
    dict(name="Beatriz Serrano Luque", email="beatriz.serrano", phone="34655010110", company="MOYZA",
         criteria=dict(type="Piso", op="Venta", min_price=None, max_price=200000, min_bed=2, max_bed=3,
                       min_bath=1, elevator=True, cities=["Jaén"], zones=["Bulevar", "Centro", "Expansión Norte"],
                       notes="Búsqueda general sin referencia. Primera vivienda.")),
    dict(name="Isabel Navarrete Gómez", email="isabel.navarrete", phone="34666020201", company="MOES",
         criteria=dict(type="Ático", op="Venta", min_price=350000, max_price=500000, min_bed=3, max_bed=4,
                       min_bath=2, elevator=True, cities=["Jaén"], zones=["Bulevar"],
                       notes="Busca ático con garaje. Llamó por la web.")),
    dict(name="Rodrigo Palomares Vega", email="rodrigo.palomares", phone="34666020202", company="MOES",
         criteria=dict(type="Chalet", op="Venta", min_price=900000, max_price=1400000, min_bed=4, max_bed=5,
                       min_bath=4, elevator=None, cities=["Marbella"], zones=["Nueva Andalucía"],
                       notes="Cliente internacional, contacto por WhatsApp.")),
    dict(name="Ana Belén Cuesta Marchal", email="anabelen.cuesta", phone="34666020203", company="MOES",
         criteria=dict(type="Piso", op="Alquiler", min_price=None, max_price=1000, min_bed=3, max_bed=3,
                       min_bath=2, elevator=True, cities=["Jaén"], zones=["Centro"],
                       notes="Traslado laboral a Jaén en diciembre.")),
    dict(name="Jorge Lendínez Ruiz", email="jorge.lendinez", phone="34666020204", company="MOES",
         criteria=dict(type="Piso", op="Venta", min_price=700000, max_price=1000000, min_bed=3, max_bed=3,
                       min_bath=2, elevator=True, cities=["Madrid"], zones=["Salamanca"],
                       notes="Oferta presentada por debajo del precio.")),
    dict(name="Sofía Herrera Campos", email="sofia.herrera", phone="34666020205", company="MOES",
         criteria=dict(type="Chalet", op="Venta", min_price=None, max_price=360000, min_bed=4, max_bed=4,
                       min_bath=3, elevator=None, cities=["Jaén"], zones=["Fuentezuelas"],
                       notes="Operación cerrada: compró Peñas de Castro 3.")),
    dict(name="Tomás Ibáñez Soler", email="tomas.ibanez", phone="34666020206", company="MOES",
         criteria=dict(type="Dúplex", op="Venta", min_price=None, max_price=380000, min_bed=3, max_bed=3,
                       min_bath=2, elevator=None, cities=["Granada"], zones=["Realejo"],
                       notes="Quiere vistas a la Alhambra.")),
]

# Alertas: buyer (índice), ref de propiedad (None = búsqueda general), agente,
# estado, días desde la asignación y seguimientos [(tipo, días atrás, nota, next_action_days)]
ALERTS = [
    # --- MOYZA ---
    dict(buyer=0, ref="DEMO-MOY-001", agent=0, status=AlertStatus.PENDING, assigned_days=6, source="Idealista",
         message="Quiere visitar el piso del Bulevar este fin de semana.", follow_ups=[]),
    dict(buyer=1, ref="DEMO-MOY-002", agent=1, status=AlertStatus.PENDING, assigned_hours=3, source="Web",
         message="Pregunta si el adosado tiene patio y si admite mascotas.", follow_ups=[]),
    dict(buyer=2, ref="DEMO-MOY-003", agent=2, status=AlertStatus.IN_PROGRESS, assigned_days=7, source="Fotocasa",
         message="Interesado en el ático, quiere saber gastos de comunidad.",
         follow_ups=[("CONTACTADO", 5, "Hablamos por teléfono, envío documentación."),
                     ("SIN_RESPUESTA", 4, "Llamo para concertar visita, no contesta.")]),
    dict(buyer=2, ref="DEMO-MOY-013", agent=1, status=AlertStatus.PENDING, assigned_days=1, source="Web",
         message="También le interesa el piso de Córdoba para su hijo.", follow_ups=[]),
    dict(buyer=3, ref="DEMO-MOY-004", agent=0, status=AlertStatus.IN_PROGRESS, assigned_days=10, source="Idealista",
         message="Busca alquiler en Peñamefécit, entrada en enero.",
         follow_ups=[("SIN_RESPUESTA", 9, "Primer intento, buzón de voz."),
                     ("SIN_RESPUESTA", 7, "Segundo intento, no contesta."),
                     ("SIN_RESPUESTA", 4, "Tercer intento, sigue sin contestar.")]),
    dict(buyer=4, ref="DEMO-MOY-006", agent=6, status=AlertStatus.IN_PROGRESS, assigned_days=6, source="Recomendación",
         message="Quiere ver el chalet de Fuentezuelas y comparar con otros.",
         extra_refs=["DEMO-MOY-002", "DEMO-MOY-003"],
         follow_ups=[("CONTACTADO", 5, "Perfil completo, le envío el chalet y el adosado."),
                     ("VISITA_PROGRAMADA", 1, "Visita confirmada con el propietario.", 2)]),
    dict(buyer=5, ref="DEMO-MOY-009", agent=1, status=AlertStatus.IN_PROGRESS, assigned_days=14, source="Web",
         message="Inversora, pregunta rentabilidad del piso del Zaidín.",
         follow_ups=[("CONTACTADO", 12, "Llamada, muy interesada."),
                     ("VISITA_PROGRAMADA", 9, "Visita el jueves a las 18:00.", -7),
                     ("OFERTA", 3, "Oferta de 165.000 €, pendiente de respuesta del propietario.")]),
    dict(buyer=6, ref="DEMO-MOY-014", agent=2, status=AlertStatus.COMPLETED, assigned_days=40, source="Cartel",
         message="Vio el cartel en Roldán y Marín.",
         follow_ups=[("CONTACTADO", 38, "Primera llamada, quiere visitar."),
                     ("VISITA_PROGRAMADA", 30, "Visita realizada, le encanta.", -29),
                     ("OFERTA", 20, "Oferta de 148.000 € aceptada."),
                     ("CERRADO", 5, "Firma en notaría. Enhorabuena.")]),
    dict(buyer=7, ref="DEMO-MOY-007", agent=2, status=AlertStatus.COMPLETED, assigned_days=18, source="Idealista",
         message="Pregunta por el piso de Linares.",
         follow_ups=[("CONTACTADO", 16, "Le explico el estado del piso."),
                     ("SIN_INTERES", 8, "No quiere reformar, descarta.")]),
    dict(buyer=8, ref="DEMO-MOY-008", agent=0, status=AlertStatus.PENDING, assigned_days=12, source="Idealista",
         message="Interesado en la casa de Úbeda como segunda residencia.", follow_ups=[]),
    dict(buyer=9, ref=None, agent=1, status=AlertStatus.IN_PROGRESS, assigned_days=3, source="Oficina",
         message="Vino a la oficina, busca primera vivienda en Jaén hasta 200.000 €.",
         follow_ups=[("CONTACTADO", 1, "Perfil completo. Le propongo tres pisos del Bulevar.")]),
    # --- MOES PREMIUM ---
    dict(buyer=10, ref="DEMO-MOES-001", agent=3, status=AlertStatus.PENDING, assigned_days=6, source="Web",
         message="Pide información y visita del ático del Paseo de España.", follow_ups=[]),
    dict(buyer=11, ref="DEMO-MOES-003", agent=4, status=AlertStatus.IN_PROGRESS, assigned_days=8, source="WhatsApp",
         message="Cliente internacional interesado en la villa de Marbella.",
         follow_ups=[("CONTACTADO", 6, "Videollamada, pide dossier completo."),
                     ("SIN_RESPUESTA", 4, "Llamo para cerrar fecha de visita, no contesta.")]),
    dict(buyer=12, ref="DEMO-MOES-006", agent=5, status=AlertStatus.IN_PROGRESS, assigned_days=2, source="Idealista",
         message="Busca alquiler en el centro para diciembre.",
         follow_ups=[("CONTACTADO", 0.2, "Hablamos, visita el sábado.")]),
    dict(buyer=13, ref="DEMO-MOES-004", agent=3, status=AlertStatus.IN_PROGRESS, assigned_days=20, source="Recomendación",
         message="Interesado en el piso de Velázquez.",
         follow_ups=[("CONTACTADO", 18, "Primera llamada."),
                     ("VISITA_PROGRAMADA", 12, "Visita en Madrid con Pablo.", -10),
                     ("OFERTA", 4, "Oferta de 920.000 €. Propietario lo está pensando.")]),
    dict(buyer=14, ref="DEMO-MOES-011", agent=3, status=AlertStatus.COMPLETED, assigned_days=45, source="Web",
         message="Pregunta por el chalet de Peñas de Castro.",
         follow_ups=[("CONTACTADO", 43, "Llamada, quiere visitar."),
                     ("VISITA_PROGRAMADA", 36, "Visita con toda la familia.", -35),
                     ("OFERTA", 25, "Oferta de 335.000 € aceptada."),
                     ("CERRADO", 10, "Firmado en notaría.")]),
    dict(buyer=15, ref="DEMO-MOES-009", agent=6, status=AlertStatus.PENDING, assigned_days=1, source="Fotocasa",
         message="Quiere ver el dúplex del Realejo.", follow_ups=[]),
]

# Visitas completadas: (ref, comprador, agente, acompañante, días atrás, interés, empresa de la visita)
VISITS = [
    ("DEMO-MOY-006", 4, 6, 0, 1, 5, "MOYZA"),
    ("DEMO-MOY-009", 5, 1, None, 9, 4, "MOYZA"),
    ("DEMO-MOY-014", 6, 2, 0, 30, 5, "MOYZA"),
    ("DEMO-MOY-003", 2, 2, None, 3, 3, "MOYZA"),
    ("DEMO-MOY-001", 0, 0, None, 2, 4, "MOYZA"),
    ("DEMO-MOY-002", 1, 1, 2, 5, 3, "MOYZA"),
    ("DEMO-MOY-008", 8, 0, None, 8, 2, "MOYZA"),
    ("DEMO-MOY-012", 9, 0, None, 11, 4, "MOYZA"),
    ("DEMO-MOES-001", 10, 3, None, 4, 4, "MOES"),
    ("DEMO-MOES-004", 13, 5, 3, 12, 4, "MOES"),
    ("DEMO-MOES-011", 14, 3, None, 36, 5, "MOES"),
    ("DEMO-MOES-006", 12, 5, None, 0.5, 3, "MOES"),
    ("DEMO-MOES-009", 15, 6, None, 6, 4, "MOES"),
    # Visita cruzada: un agente de MOYZA enseña una propiedad de MOES
    ("DEMO-MOES-008", 9, 1, None, 7, 2, "MOYZA"),
]

# Bajadas de precio: (ref, precio anterior, días atrás)
PRICE_DROPS = [
    ("DEMO-MOY-001", 199000, 15),
    ("DEMO-MOES-007", 420000, 20),
    ("DEMO-MOY-009", 185000, 3),
    ("DEMO-MOES-005", 560000, 9),
]

# Cierres: (empresa, agentes, operación, días atrás, ref, nota)
CLOSINGS = [
    ("MOYZA", [2, 0], "Venta", 5, "DEMO-MOY-014", "Cierre compartido Marta y Lucía."),
    ("MOYZA", [2], "Alquiler", 8, "DEMO-MOY-010", "Contrato de alquiler firmado."),
    ("MOES", [3], "Venta", 10, "DEMO-MOES-011", "Chalet de Peñas de Castro."),
]

TARGETS = {
    PeriodType.WEEKLY: dict(target_captaciones_crm=2, target_bajadas=1, target_contactos=8, target_hojas_visita=3),
    PeriodType.MONTHLY: dict(target_captaciones_crm=6, target_bajadas=3, target_cierres=1, target_contactos=25,
                             target_hojas_visita=10),
}

FEEDBACK = {
    5: ("JUSTO", "BUENA", "BUENO", "BUENA", "BUENO", "TIENE"),
    4: ("JUSTO", "BUENA", "BUENO", "BUENA", "NO_APLICA", "NO_APLICA"),
    3: ("ALTO", "BUENA", "REGULAR", "REGULAR", "NO_TIENE", "NO_TIENE"),
    2: ("ALTO", "REGULAR", "MALO", "REGULAR", "NO_APLICA", "NO_TIENE"),
    1: ("ALTO", "MALA", "MALO", "MALA", "NO_TIENE", "NO_TIENE"),
}


# ---------------------------------------------------------------------------
# Borrado
# ---------------------------------------------------------------------------

_FK_QUERY = """
SELECT tc.table_name, kcu.column_name, ccu.table_name AS ref, c.is_nullable
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name
JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
JOIN information_schema.columns c ON c.table_name = tc.table_name AND c.column_name = kcu.column_name
WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
  AND ccu.table_name IN ('users', 'agents')
"""

# Tablas N:M: caen en cascada al borrar, no se reapuntan
_CASCADE_TABLES = {"user_companies", "agent_companies"}


def _detach_foreign_rows(db, demo_agent_ids: list, demo_user_ids: list) -> None:
    """Desengancha de los agentes/usuarios demo las filas que aún los referencien.

    Se ejecuta después de borrar todo lo demo, así que lo que queda son datos
    reales creados o asignados con una cuenta demo. Columna opcional → NULL;
    obligatoria hacia `users` → el primer admin; obligatoria hacia `agents` →
    se deja (el borrado fallará con un mensaje claro).
    """
    admin_id = db.execute(text(
        "SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id "
        "WHERE r.name = 'admin' AND u.is_active IS NOT FALSE ORDER BY u.id LIMIT 1"
    )).scalar()
    targets = {"agents": demo_agent_ids or [0], "users": demo_user_ids or [0]}
    for table, column, ref, nullable in db.execute(text(_FK_QUERY)).all():
        if table in _CASCADE_TABLES:
            continue
        params = {"ids": targets[ref]}
        count = db.execute(text(f"SELECT count(*) FROM {table} WHERE {column} = ANY(:ids)"), params).scalar()
        if not count:
            continue
        if nullable == "YES":
            db.execute(text(f"UPDATE {table} SET {column} = NULL WHERE {column} = ANY(:ids)"), params)
            print(f"Aviso: {count} filas de {table}.{column} apuntaban a un {ref[:-1]} demo; quedan vacías.")
        elif ref == "users" and admin_id is not None:
            db.execute(text(f"UPDATE {table} SET {column} = :admin WHERE {column} = ANY(:ids)"),
                       dict(params, admin=admin_id))
            print(f"Aviso: {count} filas de {table}.{column} eran de un usuario demo; pasan al admin {admin_id}.")
        else:
            print(f"Aviso: {count} filas de {table}.{column} apuntan a un {ref[:-1]} demo y no se pueden desenganchar.")


def reset(db) -> None:
    """Borra todo lo creado por este script, en orden de dependencias."""
    agent_email_clause = or_(*[Agent.email.like(f"%{d}") for d in AGENT_DOMAINS])
    user_email_clause = or_(*[User.email.like(f"%{d}") for d in AGENT_DOMAINS])

    demo_agent_ids = [a.id for a in db.query(Agent).filter(agent_email_clause)]
    demo_user_ids = [u.id for u in db.query(User).filter(user_email_clause)]
    demo_property_ids = [p.id for p in db.query(Property).filter(Property.referencia.like(f"{REF_PREFIX}%"))]
    demo_buyer_ids = [b.id for b in db.query(Buyer).filter(Buyer.email.like(f"%{BUYER_DOMAIN}"))]
    demo_client_ids = [c.id for c in db.query(Client).filter(Client.email.like(f"%{CLIENT_DOMAIN}"))]

    alert_filter = or_(
        PropertyAlert.buyer_id.in_(demo_buyer_ids or [0]),
        PropertyAlert.agent_id.in_(demo_agent_ids or [0]),
        PropertyAlert.property_id.in_(demo_property_ids or [0]),
    )
    demo_alert_ids = [a.id for a in db.query(PropertyAlert).filter(alert_filter)]

    def ids(values):
        return values or [0]

    # Hijos de alertas
    db.execute(text("DELETE FROM alert_reminder_logs WHERE alert_id = ANY(:ids)"), {"ids": ids(demo_alert_ids)})
    db.query(AlertFollowUp).filter(AlertFollowUp.alert_id.in_(ids(demo_alert_ids))).delete(synchronize_session=False)
    db.query(AlertProperty).filter(AlertProperty.alert_id.in_(ids(demo_alert_ids))).delete(synchronize_session=False)
    db.query(AlertAssignmentLog).filter(AlertAssignmentLog.alert_id.in_(ids(demo_alert_ids))).delete(synchronize_session=False)
    db.query(Notification).filter(
        Notification.entity_type == "alert", Notification.entity_id.in_(ids(demo_alert_ids))
    ).delete(synchronize_session=False)
    db.query(PropertyAlert).filter(PropertyAlert.id.in_(ids(demo_alert_ids))).delete(synchronize_session=False)

    # Compradores
    db.query(BuyerSearchCriteria).filter(BuyerSearchCriteria.buyer_id.in_(ids(demo_buyer_ids))).delete(synchronize_session=False)
    db.query(Buyer).filter(Buyer.id.in_(ids(demo_buyer_ids))).delete(synchronize_session=False)

    # Hijos de propiedades (las visitas por ORM: arrastran auditoría, OTP y logs de WhatsApp)
    visit_filter = or_(
        PropertyVisit.property_id.in_(ids(demo_property_ids)),
        PropertyVisit.agent_id.in_(ids(demo_agent_ids)),
        PropertyVisit.companion_agent_id.in_(ids(demo_agent_ids)),
    )
    for visit in db.query(PropertyVisit).filter(visit_filter):
        db.delete(visit)
    db.flush()

    for table in ("report_job_logs", "ai_analysis_logs", "property_price_history", "property_status_history", "property_change_logs",
                  "property_interactions", "reports", "alert_follow_ups"):
        exists = db.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = 'property_id'"
        ), {"t": table}).first()
        if exists:
            db.execute(text(f"DELETE FROM {table} WHERE property_id = ANY(:ids)"), {"ids": ids(demo_property_ids)})

    db.query(Closing).filter(or_(
        Closing.property_id.in_(ids(demo_property_ids)),
        Closing.agent_id.in_(ids(demo_agent_ids)),
        Closing.shared_with_agent_id.in_(ids(demo_agent_ids)),
    )).delete(synchronize_session=False)

    db.query(Property).filter(Property.id.in_(ids(demo_property_ids))).delete(synchronize_session=False)
    db.query(Client).filter(Client.id.in_(ids(demo_client_ids))).delete(synchronize_session=False)

    # Agentes y usuarios (las tablas N:M y las notificaciones caen en cascada)
    db.query(AgentPerformanceTarget).filter(AgentPerformanceTarget.agent_id.in_(ids(demo_agent_ids))).delete(synchronize_session=False)
    db.execute(text("DELETE FROM agent_performance_reports WHERE agent_id = ANY(:ids)"), {"ids": ids(demo_agent_ids)})
    db.execute(text("DELETE FROM alert_reminder_logs WHERE agent_id = ANY(:ids)"), {"ids": ids(demo_agent_ids)})
    db.query(Notification).filter(Notification.user_id.in_(ids(demo_user_ids))).delete(synchronize_session=False)
    db.execute(text("DELETE FROM user_activity_logs WHERE user_id = ANY(:ids)"), {"ids": ids(demo_user_ids)})

    # Datos no demo que apuntan a un agente o usuario demo (una propiedad asignada
    # a mano, una captación creada entrando como agente demo, etc.), en cualquier
    # tabla, también las de otras ramas: no se borran. Las columnas opcionales se
    # vacían y las obligatorias hacia `users` pasan al primer admin.
    _detach_foreign_rows(db, demo_agent_ids, demo_user_ids)

    db.query(Agent).filter(Agent.id.in_(ids(demo_agent_ids))).delete(synchronize_session=False)
    db.query(User).filter(User.id.in_(ids(demo_user_ids))).delete(synchronize_session=False)

    db.commit()
    print(f"Borrado: {len(demo_user_ids)} usuarios, {len(demo_agent_ids)} agentes, {len(demo_client_ids)} propietarios, "
          f"{len(demo_property_ids)} propiedades, {len(demo_buyer_ids)} compradores, {len(demo_alert_ids)} alertas.")


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------

def seed(db) -> None:
    companies = {c.code: c for c in db.query(Company).all()}
    if "MOYZA" not in companies or "MOES" not in companies:
        raise SystemExit("Faltan las empresas MOYZA y MOES en la tabla companies.")

    agent_role = db.query(Role).filter(Role.name == "agent").first()
    if agent_role is None:
        raise SystemExit("Falta el rol 'agent'.")

    admin = (
        db.query(User).join(Role).filter(Role.name == "admin", User.is_active.isnot(False))
        .order_by(User.id).first()
    )
    if admin is None:
        raise SystemExit("Falta un usuario admin activo (crea el admin antes de cargar los datos de prueba).")

    # ---- Agentes con usuario ----
    agents = []
    for name, email, phone, zone, codes, primary in AGENTS:
        comps = [companies[c] for c in codes]
        label = companies_label(comps)
        user = User(
            email=email, full_name=name, hashed_password=hash_password(PASSWORD), phone=phone,
            role_id=agent_role.id, company=label, is_active=True,
            primary_company_id=companies[primary].id,
        )
        user.companies = comps
        db.add(user)
        agent = Agent(name=name, email=email, phone=phone, zone=zone, company=label, is_active=True)
        agent.companies = comps
        db.add(agent)
        agents.append(agent)
    db.flush()

    # ---- Propietarios ----
    clients = []
    for name, local, phone, codes in CLIENTS:
        client = Client(name=name, email=f"{local}{CLIENT_DOMAIN}", phone=phone, status="Activo")
        client.companies = [companies[c] for c in codes]
        db.add(client)
        clients.append(client)
    db.flush()

    # ---- Propiedades ----
    props = {}
    for p in PROPERTIES:
        entry = days_ago(p["entry"])
        prop = Property(
            referencia=p["ref"], codigo=p["ref"], title=p["title"], address=p["address"], city=p["city"],
            zona=p["zona"], cod_postal=p["cp"], pais="España", property_type=p["type"], business_type=p["op"],
            price=Decimal(p["price"]), moneda="EUR", status=p.get("status", PropertyStatus.ACTIVE),
            description=p["desc"], market_entry_date=entry, fecha_alta=entry.date(),
            estado_inmueble=p["estado"], situacion=p["situacion"], planta=p["planta"] or None,
            m2_utiles=Decimal(p["m2"]), m2_construidos=Decimal(p["m2c"]),
            num_dormitorios=p["dorm"], num_banos_aseos=p["banos"], num_salones=p["salones"],
            num_terrazas=p["terrazas"], num_armarios=p["armarios"], num_garaje_aparcam=p["garaje"],
            num_ascensores=p["asc"], num_despachos=p.get("despachos"), num_locales=p.get("locales"),
            public_url=p.get("public_url"), company_id=companies[p["company"]].id,
            client_id=clients[p["client"]].id, agent_id=agents[p["agent"]].id,
            llaves="En oficina", mandato_acuerdo="Exclusiva 6 meses" if p["op"] == "Venta" else None,
        )
        db.add(prop)
        props[p["ref"]] = prop
    db.flush()

    # ---- Compradores con perfil ----
    buyers = []
    for b in BUYERS:
        c = b["criteria"]
        buyer = Buyer(
            name=b["name"], phone=b["phone"], email=f"{b['email']}{BUYER_DOMAIN}",
            notes=f"{DEMO_TAG} {c['notes']}", created_by=admin.id, company_id=companies[b["company"]].id,
            created_at=days_ago(30),
        )
        db.add(buyer)
        db.flush()
        criteria = BuyerSearchCriteria(
            buyer_id=buyer.id, country="España", province=None,
            cities=c["cities"], zones=c["zones"], property_type=c["type"], business_type=c["op"],
            min_price=c["min_price"], max_price=c["max_price"], min_bedrooms=c["min_bed"],
            max_bedrooms=c["max_bed"], min_bathrooms=c["min_bath"], elevator=c["elevator"], notes=c["notes"],
            created_at=days_ago(30), updated_at=days_ago(30),
        )
        db.add(criteria)
        buyers.append(buyer)
    db.flush()

    # Provincia según la población principal (solo informativa en el perfil)
    province_by_city = {"Jaén": "Jaén", "Linares": "Jaén", "Úbeda": "Jaén", "Baeza": "Jaén", "Martos": "Jaén",
                        "Los Villares": "Jaén", "Granada": "Granada", "Córdoba": "Córdoba", "Sevilla": "Sevilla",
                        "Málaga": "Málaga", "Marbella": "Málaga", "Madrid": "Madrid"}
    for buyer in buyers:
        crit = buyer.search_criteria
        crit.province = province_by_city.get((crit.cities or [None])[0])
    db.flush()

    # ---- Alertas, seguimientos y propiedades de interés ----
    alerts = []
    for a in ALERTS:
        buyer = buyers[a["buyer"]]
        agent = agents[a["agent"]]
        prop = props[a["ref"]] if a["ref"] else None
        if "assigned_hours" in a:
            assigned_at = hours_ago(a["assigned_hours"])
        else:
            assigned_at = days_ago(a["assigned_days"])
        crit = buyer.search_criteria
        in_progress = a["status"] != AlertStatus.PENDING
        alert = PropertyAlert(
            property_id=prop.id if prop else None,
            company_id=buyer.company_id,
            origin=AlertOrigin.PROPERTY if prop else AlertOrigin.SEARCH,
            agent_id=agent.id, lead_name=buyer.name, lead_phone=buyer.phone, lead_email=buyer.email,
            source=a["source"], alert_type="LEAD_INTERES", message=a["message"], priority="NORMAL",
            status=a["status"], created_at=assigned_at, assigned_at=assigned_at, assigned_by=admin.id,
            created_by=admin.id, buyer_id=buyer.id, business_type=crit.business_type,
            read_at=assigned_at + timedelta(minutes=30) if in_progress else None,
        )
        db.add(alert)
        db.flush()

        db.add(AlertAssignmentLog(
            alert_id=alert.id, from_agent_id=None, to_agent_id=agent.id, assigned_by=admin.id,
            reason=None, kind="created", created_at=assigned_at,
        ))

        for ref in a.get("extra_refs", []):
            db.add(AlertProperty(alert_id=alert.id, property_id=props[ref].id,
                                 added_at=assigned_at + timedelta(days=1), added_by=admin.id))

        last_created = None
        for fu in a["follow_ups"]:
            action, back, note = fu[0], fu[1], fu[2]
            created = days_ago(back, hour=11)
            next_action = None
            if len(fu) > 3 and fu[3] is not None:
                next_action = (NOW + timedelta(days=fu[3])).replace(hour=18, minute=0, second=0, microsecond=0)
            db.add(AlertFollowUp(alert_id=alert.id, action_type=action, notes=note, next_action_date=next_action,
                                 created_at=created, created_by=admin.id))
            last_created = created
            if action in FollowUpActionType.CLOSING_STAGES:
                alert.completed_at = created
        alerts.append(alert)

        # Aviso de campana "alerta asignada" al agente (leído si ya la abrió)
        if alert.status != AlertStatus.COMPLETED:
            created = notify(
                db, users=users_for_agent(db, agent), company_id=alert.company_id,
                kind=NotificationKind.ALERT_ASSIGNED, title=f"Nueva alerta: {buyer.name}",
                body=prop.title if prop else f"Búsqueda general · {crit.business_type}",
                url=f"/alerts/{alert.id}", entity=("alert", alert.id), now=assigned_at,
            )
            if in_progress:
                for n in created:
                    n.read_at = alert.read_at
    db.flush()

    # ---- Visitas ----
    for ref, buyer_idx, agent_idx, companion_idx, back, interest, company_code in VISITS:
        buyer = buyers[buyer_idx]
        prop = props[ref]
        fb = FEEDBACK[interest]
        when = days_ago(back, hour=16)
        visit = PropertyVisit(
            property_id=prop.id, company_id=companies[company_code].id, visitor_name=buyer.name,
            dni=f"{45000000 + buyer_idx * 1234:08d}X", phone=buyer.phone, email=buyer.email,
            purchase_fees="3%" if prop.business_type == "Venta" else "1 mes",
            interest_level=interest, price_feedback=fb[0], location_feedback=fb[1], condition_feedback=fb[2],
            lighting_feedback=fb[3], elevator_feedback=fb[4], garage_feedback=fb[5],
            notes=f"{DEMO_TAG} Visita de prueba. Interés {interest}/5.",
            data_consent_accepted=True, data_consent_accepted_at=when, data_consent_ip="127.0.0.1",
            signature_captured_at=when + timedelta(minutes=25), signature_ip="127.0.0.1",
            visit_status="completed", created_by=admin.id, agent_id=agents[agent_idx].id,
            companion_agent_id=agents[companion_idx].id if companion_idx is not None else None,
            agent_signatures_confirmed_at=when + timedelta(minutes=30) if companion_idx is not None else None,
            agent_signatures_confirmed_by=admin.id if companion_idx is not None else None,
            created_at=when,
        )
        if prop.business_type != "Venta":
            visit.purchase_fees = "500"
        db.add(visit)
    db.flush()

    # ---- Bajadas de precio ----
    for ref, old_price, back in PRICE_DROPS:
        prop = props[ref]
        db.add(PropertyPriceHistory(property_id=prop.id, old_price=float(old_price), new_price=float(prop.price),
                                    reason="Bajada acordada con el propietario", created_at=days_ago(back),
                                    created_by=admin.id))

    # ---- Cierres ----
    import uuid
    for company_code, agent_idxs, op, back, ref, note in CLOSINGS:
        pair_key = str(uuid.uuid4()) if len(agent_idxs) == 2 else None
        created_at = days_ago(back)
        for i, idx in enumerate(agent_idxs):
            partner = agents[agent_idxs[1 - i]] if len(agent_idxs) == 2 else None
            db.add(Closing(
                company_id=companies[company_code].id, agent_id=agents[idx].id,
                shared_with_agent_id=partner.id if partner else None, pair_key=pair_key,
                business_type=op, closed_on=(NOW - timedelta(days=back)).date(), property_id=props[ref].id,
                notes=f"{DEMO_TAG} {note}", created_by=admin.id, created_at=created_at,
            ))

    # ---- Objetivos de la semana y del mes en curso ----
    for agent in agents:
        for company in agent.companies:
            for period_type, values in TARGETS.items():
                start = PerformanceReportService.current_period_start(period_type, NOW)
                db.add(AgentPerformanceTarget(agent_id=agent.id, company_id=company.id, period_type=period_type,
                                              period_start=start, created_by=admin.id, **values))

    db.commit()

    print("Datos de prueba cargados.\n")
    print("Agentes (clave 123456):")
    for name, email, _, _, codes, _ in AGENTS:
        print(f"  {email:36s} {name:28s} {' + '.join(codes)}")
    print(f"\nPropietarios: {len(CLIENTS)} · Propiedades: {len(PROPERTIES)} · Compradores: {len(BUYERS)} · "
          f"Alertas: {len(ALERTS)} · Visitas: {len(VISITS)} · Cierres: {len(CLOSINGS)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="solo borra los datos de prueba")
    parser.add_argument("--keep", action="store_true", help="carga sin borrar los datos de prueba anteriores")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if not args.keep:
            reset(db)
        if not args.reset:
            seed(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
