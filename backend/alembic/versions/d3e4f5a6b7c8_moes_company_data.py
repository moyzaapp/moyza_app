"""datos legales reales de MOES PREMIUM y domicilio fiscal de ambas (solo datos)

La migración `r1s2t3u4v5w6_add_companies` sembró MOES con los datos legales de
MOYZA como provisionales. Esta pone los reales (recibidos el 2026-10-28) y
actualiza el domicilio fiscal, que es el mismo para las dos empresas:

- MOES PREMIUM: razón social, CIF, teléfono y logo (`/static/logo_moes.png`).
- MOYZA y MOES: domicilio fiscal "Avenida de Madrid 37, 23009 Jaén".

Idempotente (UPDATE por `code`). El downgrade repone los valores de la siembra.
Sin cambios de esquema.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None

FISCAL_ADDRESS = "Avenida de Madrid 37, 23009 Jaén"

MOES = {
    "legal_name": "MOES 2024 S.L.U.",
    "tax_id": "B70662390",
    "phone": "722 877 402",
    "logo_path": "/static/logo_moes.png",
    "fiscal_address": FISCAL_ADDRESS,
}

# Valores de la siembra (r1s2t3u4v5w6) a los que vuelve el downgrade
SEED_ADDRESS = "Avda. Doctor Eduardo García Triviño López 9, 23009 (Jaén)"
SEED_MOES = {
    "legal_name": "Moyza 2012 S.L.",
    "tax_id": "B16914012",
    "phone": "642 497 955 / 953 940 956",
    "logo_path": "/static/logo_moyza.png",
    "fiscal_address": SEED_ADDRESS,
}


def _update(code: str, values: dict) -> None:
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    op.execute(
        sa.text(f"UPDATE companies SET {assignments} WHERE code = :code").bindparams(code=code, **values)
    )


def upgrade() -> None:
    _update("MOES", MOES)
    _update("MOYZA", {"fiscal_address": FISCAL_ADDRESS})


def downgrade() -> None:
    _update("MOES", SEED_MOES)
    _update("MOYZA", {"fiscal_address": SEED_ADDRESS})
