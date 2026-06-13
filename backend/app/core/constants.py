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
