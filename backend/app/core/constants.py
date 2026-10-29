class CompanyCode:
    """Claves estables de las empresas internas (columna `companies.code`).

    Se usan en código y en la cookie de empresa activa. Los datos de marca
    y legales viven en la tabla `companies`, no aquí.
    """

    MOYZA = "MOYZA"
    MOES = "MOES"

    # Empresa por defecto: todo lo anterior a la separación por empresa
    # pertenece a MOYZA.
    DEFAULT = MOYZA


class PhoneCountryCodes:
    """Indicativos telefónicos disponibles en el selector de país de teléfonos."""

    # (código, ISO, bandera, nombre)
    OPTIONS = [
        ("34", "ES", "🇪🇸", "España"),
        ("57", "CO", "🇨🇴", "Colombia"),
        ("52", "MX", "🇲🇽", "México"),
        ("54", "AR", "🇦🇷", "Argentina"),
        ("51", "PE", "🇵🇪", "Perú"),
        ("56", "CL", "🇨🇱", "Chile"),
        ("593", "EC", "🇪🇨", "Ecuador"),
        ("58", "VE", "🇻🇪", "Venezuela"),
        ("55", "BR", "🇧🇷", "Brasil"),
        ("1", "US", "🇺🇸", "Estados Unidos"),
        ("44", "GB", "🇬🇧", "Reino Unido"),
        ("33", "FR", "🇫🇷", "Francia"),
        ("49", "DE", "🇩🇪", "Alemania"),
        ("39", "IT", "🇮🇹", "Italia"),
        ("351", "PT", "🇵🇹", "Portugal"),
        ("212", "MA", "🇲🇦", "Marruecos"),
    ]

    DEFAULT = "34"

    # Valor de la opción "Otro…" del selector: el indicativo se escribe a mano
    # en `{prefix}country_code_other` y se valida contra ALL_CODES
    OTHER = "other"

    # Todos los indicativos de país de E.164 (1 a 3 dígitos), incluidos los
    # territorios y los servicios no geográficos. Los planes de numeración
    # compartidos van con su código común (NANP = 1, Rusia/Kazajistán = 7).
    # Es un código prefijo-libre: ninguno es el inicio de otro, así que el
    # emparejamiento "más largo que coincida" es inequívoco.
    ALL_CODES = frozenset("""
        1 7
        20 27 211 212 213 216 218
        220 221 222 223 224 225 226 227 228 229
        230 231 232 233 234 235 236 237 238 239
        240 241 242 243 244 245 246 247 248 249
        250 251 252 253 254 255 256 257 258
        260 261 262 263 264 265 266 267 268 269
        290 291 297 298 299
        30 31 32 33 34 36 39
        350 351 352 353 354 355 356 357 358 359
        370 371 372 373 374 375 376 377 378 379
        380 381 382 383 385 386 387 389
        40 41 43 44 45 46 47 48 49 420 421 423
        51 52 53 54 55 56 57 58
        500 501 502 503 504 505 506 507 508 509
        590 591 592 593 594 595 596 597 598 599
        60 61 62 63 64 65 66
        670 672 673 674 675 676 677 678 679
        680 681 682 683 685 686 687 688 689
        690 691 692
        81 82 84 86
        800 808 850 852 853 855 856 870 878 880 881 882 883 886 888
        90 91 92 93 94 95 98
        960 961 962 963 964 965 966 967 968
        970 971 972 973 974 975 976 977 979
        992 993 994 995 996 998
    """.split())

    @classmethod
    def short_codes(cls):
        """Indicativos del selector (los frecuentes)."""
        return {code for code, *_ in cls.OPTIONS}

    @classmethod
    def choices(cls):
        """Lista de (código, bandera, etiqueta) para renderizar el <select>."""
        return [(code, flag, f"{flag} +{code} {name}") for code, _, flag, name in cls.OPTIONS]

    @classmethod
    def split(cls, phone):
        """Separa un teléfono guardado en (código de país, número local).

        Empareja por el indicativo conocido más largo que coincida con el
        inicio del número. Si no encuentra ninguno (teléfonos guardados antes
        de existir este selector), asume España y deja el número completo tal
        cual para que el agente lo revise.
        """
        digits = "".join(ch for ch in (phone or "") if ch.isdigit())

        if not digits:
            return cls.DEFAULT, ""

        candidates = sorted((code for code, *_ in cls.OPTIONS), key=len, reverse=True)

        for code in candidates:
            if digits.startswith(code) and len(digits) - len(code) >= 6:
                return code, digits[len(code):]

        return cls.DEFAULT, digits


class PropertyStatus:
    ACTIVE = "Activa"
    RESERVED = "Reservada"
    PAUSED = "Pausada"
    SOLD = "Vendida"
    WITHDRAWN = "Retirada"
    ARCHIVED = "Archivada"

    @classmethod
    def values(cls):
        return {
            cls.ACTIVE,
            cls.RESERVED,
            cls.PAUSED,
            cls.SOLD,
            cls.WITHDRAWN,
            cls.ARCHIVED,
        }

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls.values()


class BusinessType:
    """Operación de una propiedad o de lo que busca un comprador.

    Valores tal cual se guardan en `properties.business_type` y
    `buyer_search_criteria.business_type`. En el alta y la edición de
    criterios de un comprador es obligatoria y solo admite estos dos.
    """
    VENTA = "Venta"
    ALQUILER = "Alquiler"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        # Tupla ordenada: es también el orden de las opciones en los selects
        return (cls.VENTA, cls.ALQUILER)

    @classmethod
    def is_valid(cls, value: str | None) -> bool:
        return value in cls.values()


class ElevatorPreference:
    """Ascensor en el perfil del comprador (PLAN_PERFIL_ZONAS.md, fase C).

    Valores del select "Ascensor" (opcional, "Indiferente" por defecto). En la
    base de datos `buyer_search_criteria.elevator` es NULL / True / False
    (`buyer_matching.parse_elevator` y `elevator_value` traducen).
    """
    ANY = ""
    YES = "yes"
    NO = "no"

    @classmethod
    def choices(cls) -> tuple[tuple[str, str], ...]:
        # Orden de las opciones del select
        return ((cls.ANY, "Indiferente"), (cls.YES, "Con ascensor"), (cls.NO, "Sin ascensor"))


class PropertyInteractionType:
    INQUIRY = "CONSULTA"
    VISIT = "VISITA"
    INTERESTED = "INTERESADO"
    OFFER = "OFERTA"

    @classmethod
    def values(cls):
        return {
            cls.INQUIRY,
            cls.VISIT,
            cls.INTERESTED,
            cls.OFFER,
        }

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls.values()


class ReportType:
    AUTOMATIC = "AUTOMATICO"
    GENERAL = "GENERAL"
    FOLLOW_UP = "SEGUIMIENTO"
    VALUATION = "VALORACION"

    @classmethod
    def upload_values(cls):
        return {
            cls.GENERAL,
            cls.FOLLOW_UP,
            cls.VALUATION,
        }

    @classmethod
    def values(cls):
        return cls.upload_values() | {cls.AUTOMATIC}

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls.values()

    @classmethod
    def is_valid_upload(cls, value: str) -> bool:
        return value in cls.upload_values()


class AlertType:
    LEAD_INTERES = "LEAD_INTERES"
    CAMBIO_PRECIO = "CAMBIO_PRECIO"
    VISITA_SOLICITADA = "VISITA_SOLICITADA"
    OTRO = "OTRO"

    @classmethod
    def values(cls):
        return {
            cls.LEAD_INTERES,
            cls.CAMBIO_PRECIO,
            cls.VISITA_SOLICITADA,
            cls.OTRO,
        }

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls.values()


class AlertPriority:
    ALTA = "ALTA"
    NORMAL = "NORMAL"
    BAJA = "BAJA"

    @classmethod
    def values(cls):
        return {
            cls.ALTA,
            cls.NORMAL,
            cls.BAJA,
        }

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls.values()


class AlertStatus:
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    @classmethod
    def values(cls):
        return {
            cls.PENDING,
            cls.IN_PROGRESS,
            cls.COMPLETED,
            cls.CANCELLED,
        }

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls.values()


class AlertOrigin:
    """Cómo nació una alerta de comprador (PLAN_ALERTA_SIN_REFERENCIA.md).

    - ``property``: creada con referencia (interés en un inmueble concreto).
    - ``search``: creada sin referencia (búsqueda general). La propiedad se
      asocia después, a la misma alerta.

    Desde PLAN_PERFIL_OBLIGATORIO.md el origen es solo un dato (cómo entró el
    comprador, para etiquetas y analítica): ya no condiciona el flujo. Todas
    las alertas tienen Perfil, Propuesta y "Cambiar propiedad".
    """
    PROPERTY = "property"
    SEARCH = "search"

    @classmethod
    def values(cls):
        return (cls.PROPERTY, cls.SEARCH)


class FollowUpActionType:
    # Etapas de progresión (avanzan la etapa visible del comprador)
    CONTACTADO = "CONTACTADO"
    VISITA_PROGRAMADA = "VISITA_PROGRAMADA"
    OFERTA = "OFERTA"

    # Etapas heredadas (PLAN_RECORDATORIO_SIN_RESPUESTA.md §3.3): ya no se
    # ofrecen en el formulario e `is_valid` las rechaza, pero los registros
    # antiguos se siguen mostrando con su etiqueta y color y ordenando.
    PRIMERA_LLAMADA = "PRIMERA_LLAMADA"
    CALIFICADO = "CALIFICADO"
    LEGACY_STAGES = {"PRIMERA_LLAMADA", "CALIFICADO"}

    # Acción repetible (no avanza etapa; indica intento fallido de contacto)
    SIN_RESPUESTA = "SIN_RESPUESTA"

    # Cierres: auto-completan la alerta (éxito o descarte)
    CERRADO = "CERRADO"
    SIN_INTERES = "SIN_INTERES"
    SIN_SOLVENCIA_ECONOMICA = "SIN_SOLVENCIA_ECONOMICA"
    NO_APTO_PROPIETARIO = "NO_APTO_PROPIETARIO"

    # Etapas que cierran la alerta automáticamente al registrarlas
    CLOSING_STAGES = {"CERRADO", "SIN_INTERES", "SIN_SOLVENCIA_ECONOMICA", "NO_APTO_PROPIETARIO"}

    # Nota automática del sistema (PLAN_ASIGNACION_ALERTAS.md §2.2): la escribe
    # la reasignación, nunca el formulario de seguimiento (no está en
    # STAGE_ORDER, así que `is_valid` la rechaza). No avanza etapa y no cuenta
    # como gestión del agente: no desbloquea la cola, no permite cerrar la
    # alerta ni marca actividad.
    REASIGNADA = "REASIGNADA"

    # Asociar o cambiar la propiedad de una búsqueda (PLAN_ALERTA_SIN_REFERENCIA.md).
    # Lo escribe la ruta /alerts/{id}/link-property, nunca el formulario de
    # seguimiento (no está en STAGE_ORDER). Es una gestión real: desbloquea la
    # cola y permite cerrar, pero no avanza la etapa visible.
    PROPIEDAD_ASOCIADA = "PROPIEDAD_ASOCIADA"

    # Guardar el perfil de búsqueda desde la alerta (PLAN_RECORDATORIO_SIN_RESPUESTA.md
    # §3.3). Lo escribe la ruta /alerts/{id}/search-profile, nunca el formulario
    # de seguimiento (no está en STAGE_ORDER). Gestión real: desbloquea la cola
    # y permite cerrar, pero no avanza la etapa visible. Sustituye al CALIFICADO
    # automático que se creaba antes. Desde PLAN_PERFIL_OBLIGATORIO.md solo
    # registra las EDICIONES del perfil: la primera vez que el perfil del
    # comprador queda completo se registra CONTACTADO (perfil = contactado).
    PERFIL_GUARDADO = "PERFIL_GUARDADO"

    # Etapas que exigen el perfil del comprador completo (PLAN_PERFIL_OBLIGATORIO.md,
    # decisión 2): sin los mínimos del perfil (buyer_matching.missing_profile_fields;
    # PLAN_PERFIL_ZONAS.md) no se pueden registrar. Sin respuesta y los cierres negativos sí se registran sin
    # perfil (decisión 3); Contactado lleva el perfil dentro.
    PROFILE_REQUIRED_STAGES = {"VISITA_PROGRAMADA", "OFERTA", "CERRADO"}

    # Acciones que no avanzan la etapa de progresión visible
    REPEATABLE_ACTIONS = {"SIN_RESPUESTA", "PROPIEDAD_ASOCIADA", "PERFIL_GUARDADO"}

    # Acciones del sistema: se muestran en el historial pero no son seguimientos
    SYSTEM_ACTIONS = {"REASIGNADA"}

    # Orden numérico de las etapas de progresión. Las heredadas conservan un
    # orden coherente para los historiales antiguos: Primera llamada por debajo
    # de Contactado y Calificado al mismo nivel que Contactado.
    STAGE_ORDER = {
        "PRIMERA_LLAMADA": 1,
        "CONTACTADO": 2,
        "CALIFICADO": 2,
        "VISITA_PROGRAMADA": 3,
        "OFERTA": 4,
        "CERRADO": 5,
        "SIN_INTERES": 5,
        "SIN_SOLVENCIA_ECONOMICA": 5,
        "NO_APTO_PROPIETARIO": 5,
        "SIN_RESPUESTA": 0,
    }

    @classmethod
    def labels(cls):
        return {
            cls.PRIMERA_LLAMADA: "Primera Llamada",
            cls.SIN_RESPUESTA: "Sin Respuesta",
            cls.CONTACTADO: "Contactado",
            cls.CALIFICADO: "Calificado",
            cls.VISITA_PROGRAMADA: "Visita Programada",
            cls.OFERTA: "Oferta/Negociación",
            cls.CERRADO: "Cerrado",
            cls.SIN_INTERES: "Sin Interés",
            cls.SIN_SOLVENCIA_ECONOMICA: "Sin Solvencia Económica",
            cls.NO_APTO_PROPIETARIO: "No apto para el propietario",
            cls.REASIGNADA: "Reasignada",
            cls.PROPIEDAD_ASOCIADA: "Propiedad asociada",
            cls.PERFIL_GUARDADO: "Perfil guardado",
            # Etiquetas heredadas para registros antiguos
            "LLAMADA": "Llamada",
            "EMAIL_ENVIADO": "Email Enviado",
            "OFERTA_RECIBIDA": "Oferta Recibida",
            "NEGOCIACION": "Negociación",
            "OTRO": "Otro",
        }

    @classmethod
    def progression_stages(cls):
        """Etapas de progresión + acción repetible para el formulario (sin las heredadas)."""
        return [
            (cls.SIN_RESPUESTA, "Sin Respuesta"),
            (cls.CONTACTADO, "Contactado"),
            (cls.VISITA_PROGRAMADA, "Visita Programada"),
            (cls.OFERTA, "Oferta/Negociación"),
        ]

    @classmethod
    def closing_stages(cls):
        """Etapas de cierre para el formulario."""
        return [
            (cls.CERRADO, "Cerrado (éxito)"),
            (cls.SIN_INTERES, "Sin Interés"),
            (cls.SIN_SOLVENCIA_ECONOMICA, "Sin Solvencia Económica"),
            (cls.NO_APTO_PROPIETARIO, "No apto para el propietario"),
        ]

    @classmethod
    def ordered_stages(cls):
        """Todas las etapas en orden para el formulario."""
        return cls.progression_stages() + cls.closing_stages()

    @classmethod
    def stage_badge_color(cls, value: str) -> str:
        colors = {
            "PRIMERA_LLAMADA": "bg-gray-100 text-gray-700",
            "SIN_RESPUESTA": "bg-amber-100 text-amber-700",
            "CONTACTADO": "bg-blue-100 text-blue-700",
            "CALIFICADO": "bg-indigo-100 text-indigo-700",
            "VISITA_PROGRAMADA": "bg-purple-100 text-purple-700",
            "OFERTA": "bg-orange-100 text-orange-700",
            "CERRADO": "bg-green-100 text-green-700",
            "SIN_INTERES": "bg-red-100 text-red-700",
            "SIN_SOLVENCIA_ECONOMICA": "bg-red-100 text-red-700",
            "NO_APTO_PROPIETARIO": "bg-red-100 text-red-700",
            # Nota del sistema: neutro, no es una etapa
            "REASIGNADA": "bg-gray-100 text-gray-700",
            # Gestión que no es etapa: informativo
            "PROPIEDAD_ASOCIADA": "bg-blue-100 text-blue-700",
            "PERFIL_GUARDADO": "bg-blue-100 text-blue-700",
            # Legados
            "LLAMADA": "bg-gray-100 text-gray-700",
            "EMAIL_ENVIADO": "bg-gray-100 text-gray-700",
            "OFERTA_RECIBIDA": "bg-orange-100 text-orange-700",
            "NEGOCIACION": "bg-orange-100 text-orange-700",
            "OTRO": "bg-gray-100 text-gray-700",
        }
        return colors.get(value, "bg-gray-100 text-gray-700")

    @classmethod
    def values(cls):
        """Valores que acepta el formulario de seguimiento (sin las etapas heredadas)."""
        return set(cls.STAGE_ORDER.keys()) - cls.LEGACY_STAGES

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls.values()


class PeriodType:
    """Tipos de período de los informes de rendimiento por agente."""

    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"

    DEFAULT = WEEKLY

    @classmethod
    def values(cls):
        return (cls.WEEKLY, cls.MONTHLY, cls.YEARLY)

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls.values()

    @classmethod
    def labels(cls):
        return {cls.WEEKLY: "Semana", cls.MONTHLY: "Mes", cls.YEARLY: "Año"}


class PerformanceObjectives:
    """Métricas con objetivo según el tipo de período (PLAN_RESULTADOS_COMERCIALES §2.3).

    Una sola fuente para formularios, barras de progreso y % de cumplimiento.
    El resto de métricas se muestran como resultado, sin objetivo. Los
    objetivos son totales: el desglose venta / alquiler es solo de resultados.
    """

    WEEKLY = ("captaciones_crm", "bajadas")
    MONTHLY = ("captaciones_crm", "bajadas", "cierres")
    YEARLY = ("captaciones_crm", "bajadas", "cierres")

    # Métrica -> columna de `agent_performance_targets`. Contactos y hojas de
    # visita conservan su columna como histórico (decisión §5-5).
    TARGET_FIELDS = {
        "contactos": "target_contactos",
        "bajadas": "target_bajadas",
        "captaciones_crm": "target_captaciones_crm",
        "cierres": "target_cierres",
        "hojas_visita": "target_hojas_visita",
    }

    LABELS = {
        "contactos": "Contactos",
        "bajadas": "Bajadas",
        "captaciones_crm": "Captaciones CRM",
        "cierres": "Cierres",
        "hojas_visita": "Hojas de Visita",
    }

    @classmethod
    def for_period(cls, period_type) -> tuple:
        return {
            PeriodType.WEEKLY: cls.WEEKLY,
            PeriodType.MONTHLY: cls.MONTHLY,
            PeriodType.YEARLY: cls.YEARLY,
        }.get(period_type, ())

    @classmethod
    def target_field(cls, metric_key: str) -> str:
        return cls.TARGET_FIELDS[metric_key]


class LocalHolidays:
    """Festivos locales de Jaén capital (PLAN_ALERTAS_DIAS_HABILES.md, decisión 2).

    Los fija el Ayuntamiento cada año y valen para las dos empresas. Los
    nacionales y los de Andalucía (con sus traslados al lunes) salen de la
    librería `holidays`; aquí solo van los dos locales. Si el Ayuntamiento los
    cambia, o para un año nuevo, se edita esta lista: un año que no aparece no
    tiene festivos locales.
    """

    # año -> [(mes, día, nombre)]
    BY_YEAR = {
        2026: [(6, 11, "Virgen de la Capilla"), (10, 18, "San Lucas")],
        2027: [(6, 11, "Virgen de la Capilla"), (10, 18, "San Lucas")],
        2028: [(6, 11, "Virgen de la Capilla"), (10, 18, "San Lucas")],
    }


# Atajo con el nombre del plan
LOCAL_HOLIDAYS = LocalHolidays.BY_YEAR


class DashboardThresholds:
    """Umbrales del Inicio (PLAN_DASHBOARD_INICIO.md §6-7).

    El aviso de compradores sin atender NO está aquí: reutiliza la regla de
    los recordatorios por email (`settings.BUYER_REMINDER_HOURS`, 48 h).
    """

    # Agente: compradores con último seguimiento "sin respuesta" hace más de N días
    NO_RESPONSE_DAYS = 3
    # Agente: propiedades activas sin ninguna visita en N días
    STALE_PROPERTY_DAYS = 30
    # Admin: compradores PENDING abandonados (misma regla que Resultados Comerciales)
    ABANDONED_BUYER_DAYS = 7
    # Admin: agente sin actividad (visita, seguimiento ni alerta leída) en N días
    INACTIVE_AGENT_DAYS = 5
    # Admin: fichas de visita con WhatsApp en ERROR en las últimas N horas
    WHATSAPP_ERROR_HOURS = 48

    # Semanas de las gráficas de tendencia
    AGENT_TREND_WEEKS = 8
    TEAM_TREND_WEEKS = 12

    # Elementos por bloque
    AGENDA_LIMIT = 8
    FEED_LIMIT = 20
    NEWS_LIMIT = 8

    # Admin: bloque "Cesiones recientes" (PLAN_CEDER_COMPRADORES.md §7-5)
    RECENT_CESSIONS_DAYS = 7
    RECENT_CESSIONS_LIMIT = 5
