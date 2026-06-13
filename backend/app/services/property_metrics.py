from datetime import datetime
from typing import Dict, Iterable, Optional

from sqlalchemy.orm import Session

from app.core.constants import PropertyInteractionType
from app.models.property import Property
from app.models.property_interaction import PropertyInteraction
from app.models.property_price_history import PropertyPriceHistory
from app.models.property_visit import PropertyVisit


class PropertyMetricsService:
    """Calcula métricas compartidas para detalle de propiedad y reportes."""

    def __init__(self, db: Session):
        self.db = db

    def days_on_market(self, property_item: Property) -> int:
        if not property_item.market_entry_date:
            return 0

        return (datetime.utcnow() - property_item.market_entry_date).days

    def price_gap(self, property_item: Property) -> Optional[float]:
        if property_item.price is None or property_item.fair_price is None:
            return None

        return float(property_item.price) - float(property_item.fair_price)

    def price_reductions_count(self, property_id: int) -> int:
        return (
            self.db.query(PropertyPriceHistory)
            .filter(PropertyPriceHistory.property_id == property_id)
            .count()
        )

    def interaction_count(self, property_id: int, interaction_type: str) -> int:
        return (
            self.db.query(PropertyInteraction)
            .filter(
                PropertyInteraction.property_id == property_id,
                PropertyInteraction.interaction_type == interaction_type
            )
            .count()
        )

    def report_data(
        self,
        property_item: Property,
        reductions_count: Optional[int] = None
    ) -> Dict:
        property_id = property_item.id
        if reductions_count is None:
            reductions_count = self.price_reductions_count(property_id)

        return {
            "days_on_market": self.days_on_market(property_item),
            "reductions": reductions_count,
            "consultas": self.interaction_count(
                property_id,
                PropertyInteractionType.INQUIRY
            ),
            "visitas": self.interaction_count(
                property_id,
                PropertyInteractionType.VISIT
            ),
            "interesados": self.interaction_count(
                property_id,
                PropertyInteractionType.INTERESTED
            ),
            "ofertas": self.interaction_count(
                property_id,
                PropertyInteractionType.OFFER
            ),
        }

    def visit_summary(self, visits: Iterable[PropertyVisit]) -> Dict:
        visits = list(visits)
        interest_values = []

        for visit in visits:
            if visit.interest_level is None:
                continue

            try:
                interest_values.append(int(visit.interest_level))
            except (TypeError, ValueError):
                continue

        interest_avg = None
        if interest_values:
            interest_avg = round(sum(interest_values) / len(interest_values), 2)

        price_high_count = sum(
            1
            for visit in visits
            if visit.price_feedback == "ALTO"
        )

        return {
            "interest_avg": interest_avg,
            "price_high_count": price_high_count,
        }
