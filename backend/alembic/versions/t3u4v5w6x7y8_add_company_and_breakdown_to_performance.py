"""add company and sale/rent breakdown to performance reports and targets

PLAN_RESULTADOS_COMERCIALES.md §2.4 y §2.5:

- `company_id` (NOT NULL) en `agent_performance_targets` y
  `agent_performance_reports`. Lo existente se asigna a MOYZA, que es donde
  se calcularon hasta ahora (las métricas no filtraban por empresa y todos
  los datos anteriores a la separación son de MOYZA).
- La clave única pasa de (agent_id, period_type, period_start) a
  (agent_id, company_id, period_type, period_start): un agente en las dos
  empresas tiene objetivos y snapshots separados en cada una.
- 6 columnas de desglose venta / alquiler en los snapshots. Quedan NULL en
  los snapshots existentes: sus totales no se tocan.

Revision ID: t3u4v5w6x7y8
Revises: s2t3u4v5w6x7
Create Date: 2026-10-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 't3u4v5w6x7y8'
down_revision = 's2t3u4v5w6x7'
branch_labels = None
depends_on = None


TABLES = ['agent_performance_targets', 'agent_performance_reports']

BREAKDOWN_COLUMNS = [
    'captaciones_venta',
    'captaciones_alquiler',
    'bajadas_venta',
    'bajadas_alquiler',
    'cierres_venta',
    'cierres_alquiler',
]


def upgrade():
    for table_name in TABLES:
        op.add_column(
            table_name,
            sa.Column(
                'company_id',
                sa.Integer(),
                sa.ForeignKey('companies.id', name=f'fk_{table_name}_company_id'),
                nullable=True
            )
        )
        op.execute(
            f"UPDATE {table_name} "
            f"SET company_id = (SELECT id FROM companies WHERE code = 'MOYZA')"
        )
        op.alter_column(table_name, 'company_id', nullable=False)
        op.create_index(f'ix_{table_name}_company_id', table_name, ['company_id'])

        op.drop_index(f'ix_{table_name}_agent_period', table_name=table_name)
        op.create_index(
            f'ix_{table_name}_agent_company_period',
            table_name,
            ['agent_id', 'company_id', 'period_type', 'period_start'],
            unique=True
        )

    for column in BREAKDOWN_COLUMNS:
        op.add_column(
            'agent_performance_reports',
            sa.Column(column, sa.Integer(), nullable=True)
        )


def downgrade():
    for column in reversed(BREAKDOWN_COLUMNS):
        op.drop_column('agent_performance_reports', column)

    for table_name in reversed(TABLES):
        # La clave antigua no admite el mismo agente y período en dos
        # empresas: se conservan solo las filas de MOYZA.
        op.execute(
            f"DELETE FROM {table_name} "
            f"WHERE company_id <> (SELECT id FROM companies WHERE code = 'MOYZA')"
        )
        op.drop_index(f'ix_{table_name}_agent_company_period', table_name=table_name)
        op.create_index(
            f'ix_{table_name}_agent_period',
            table_name,
            ['agent_id', 'period_type', 'period_start'],
            unique=True
        )
        op.drop_index(f'ix_{table_name}_company_id', table_name=table_name)
        op.drop_constraint(f'fk_{table_name}_company_id', table_name, type_='foreignkey')
        op.drop_column(table_name, 'company_id')
