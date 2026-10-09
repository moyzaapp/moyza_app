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
        ("1", "US", "🇺🇸", "Estados Unidos"),
        ("44", "GB", "🇬🇧", "Reino Unido"),
        ("33", "FR", "🇫🇷", "Francia"),
        ("49", "DE", "🇩🇪", "Alemania"),
        ("39", "IT", "🇮🇹", "Italia"),
        ("351", "PT", "🇵🇹", "Portugal"),
        ("212", "MA", "🇲🇦", "Marruecos"),
    ]

    DEFAULT = "34"

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


class FollowUpActionType:
    # Etapas de progresión (avanzan la etapa visible del comprador)
    PRIMERA_LLAMADA = "PRIMERA_LLAMADA"
    CONTACTADO = "CONTACTADO"
    CALIFICADO = "CALIFICADO"
    VISITA_PROGRAMADA = "VISITA_PROGRAMADA"
    OFERTA = "OFERTA"

    # Acción repetible (no avanza etapa; indica intento fallido de contacto)
    SIN_RESPUESTA = "SIN_RESPUESTA"

    # Cierres: auto-completan la alerta (éxito o descarte)
    CERRADO = "CERRADO"
    SIN_INTERES = "SIN_INTERES"
    SIN_SOLVENCIA_ECONOMICA = "SIN_SOLVENCIA_ECONOMICA"
    NO_APTO_PROPIETARIO = "NO_APTO_PROPIETARIO"

    # Etapas que cierran la alerta automáticamente al registrarlas
    CLOSING_STAGES = {"CERRADO", "SIN_INTERES", "SIN_SOLVENCIA_ECONOMICA", "NO_APTO_PROPIETARIO"}

    # Acciones que no avanzan la etapa de progresión visible
    REPEATABLE_ACTIONS = {"SIN_RESPUESTA"}

    # Orden numérico de las etapas de progresión
    STAGE_ORDER = {
        "PRIMERA_LLAMADA": 1,
        "CONTACTADO": 2,
        "CALIFICADO": 3,
        "VISITA_PROGRAMADA": 4,
        "OFERTA": 5,
        "CERRADO": 6,
        "SIN_INTERES": 6,
        "SIN_SOLVENCIA_ECONOMICA": 6,
        "NO_APTO_PROPIETARIO": 6,
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
            # Etiquetas heredadas para registros antiguos
            "LLAMADA": "Llamada",
            "EMAIL_ENVIADO": "Email Enviado",
            "OFERTA_RECIBIDA": "Oferta Recibida",
            "NEGOCIACION": "Negociación",
            "OTRO": "Otro",
        }

    @classmethod
    def progression_stages(cls):
        """Etapas de progresión + acción repetible para el formulario."""
        return [
            (cls.PRIMERA_LLAMADA, "Primera Llamada"),
            (cls.SIN_RESPUESTA, "Sin Respuesta"),
            (cls.CONTACTADO, "Contactado"),
            (cls.CALIFICADO, "Calificado"),
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
        return set(cls.STAGE_ORDER.keys())

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
