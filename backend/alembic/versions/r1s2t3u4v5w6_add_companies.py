"""add companies (MOYZA / MOES PREMIUM)

Crea la tabla `companies`, asigna empresa a propiedades y compradores,
y crea las tablas de pertenencia para usuarios, agentes y clientes.
Todo lo existente se asigna a MOYZA.

Revision ID: r1s2t3u4v5w6
Revises: q0r1s2t3u4v5
Create Date: 2026-10-06 00:00:00.000000

"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'r1s2t3u4v5w6'
down_revision = 'q0r1s2t3u4v5'
branch_labels = None
depends_on = None


# Primer párrafo del bloque RGPD de la ficha de visita, tal cual estaba
# hardcodeado en el PDF. Los otros párrafos son fijos y viven en código.
MOYZA_RGPD = (
    "En nombre de la empresa Inmobiliaria MOYZA tratamos la información que nos facilita "
    "con el fin de prestarles el servicio solicitado y realizar la facturación del mismo. "
    "Los datos proporcionados se conservarán mientras se mantenga la relación comercial o "
    "durante los meses necesarios para cumplir con las obligaciones legales. Los datos no se "
    "cederán a terceros salvo en los casos en que exista una obligación legal. Usted tiene "
    "derecho a obtener confirmación sobre si en Inmobiliaria MOYZA estamos tratando sus datos "
    "personales, por tanto tiene derecho a acceder a sus datos personales, rectificar los datos "
    "inexactos o solicitar su supresión cuando los datos ya no sean necesarios."
)


def _seed_companies():
    companies = sa.table(
        'companies',
        sa.column('code', sa.String),
        sa.column('name', sa.String),
        sa.column('legal_name', sa.String),
        sa.column('tax_id', sa.String),
        sa.column('fiscal_address', sa.String),
        sa.column('phone', sa.String),
        sa.column('rgpd_text', sa.Text),
        sa.column('logo_path', sa.String),
        sa.column('primary_color', sa.String),
        sa.column('document_prefix', sa.String),
        sa.column('email_sender_name', sa.String),
        sa.column('whatsapp_phone', sa.String),
        sa.column('is_active', sa.Boolean),
        sa.column('created_at', sa.DateTime),
    )

    now = datetime.utcnow()

    op.bulk_insert(companies, [
        {
            # Datos que hasta ahora estaban hardcodeados en la ficha de visita
            'code': 'MOYZA',
            'name': 'MOYZA',
            'legal_name': 'Moyza 2012 S.L.',
            'tax_id': 'B16914012',
            'fiscal_address': 'Avda. Doctor Eduardo García Triviño López 9, 23009 (Jaén)',
            'phone': '642 497 955 / 953 940 956',
            'rgpd_text': MOYZA_RGPD,
            'logo_path': '/static/logo_moyza.png',
            'primary_color': '#000000',
            'document_prefix': 'MOYZA-VISIT',
            'email_sender_name': 'Sistema Moyza',
            'whatsapp_phone': None,
            'is_active': True,
            'created_at': now,
        },
        {
            # ATENCIÓN: datos legales PROVISIONALES copiados de MOYZA.
            # Deben sustituirse por los reales de MOES PREMIUM (razón social,
            # CIF, domicilio fiscal, teléfonos, texto RGPD y logo) en cuanto
            # se reciban:
            #   UPDATE companies SET legal_name=..., tax_id=..., ... WHERE code='MOES';
            'code': 'MOES',
            'name': 'MOES PREMIUM',
            'legal_name': 'Moyza 2012 S.L.',                         # TODO: real de MOES
            'tax_id': 'B16914012',                                   # TODO: real de MOES
            'fiscal_address': 'Avda. Doctor Eduardo García Triviño López 9, 23009 (Jaén)',  # TODO: real de MOES
            'phone': '642 497 955 / 953 940 956',                    # TODO: real de MOES
            'rgpd_text': MOYZA_RGPD.replace('MOYZA', 'MOES PREMIUM'),  # TODO: real de MOES
            'logo_path': '/static/logo_moyza.png',                   # TODO: logo de MOES
            'primary_color': '#8A6D1F',
            'document_prefix': 'MOES-VISIT',
            'email_sender_name': 'Sistema MOES Premium',
            'whatsapp_phone': None,
            'is_active': True,
            'created_at': now,
        },
    ])


def _add_company_fk(table_name: str):
    """Añade `company_id` NOT NULL a una tabla raíz, asignando MOYZA a lo existente."""
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


def _create_membership(table_name: str, owner_table: str, owner_col: str):
    op.create_table(
        table_name,
        sa.Column(
            owner_col,
            sa.Integer(),
            sa.ForeignKey(f'{owner_table}.id', ondelete='CASCADE'),
            primary_key=True
        ),
        sa.Column(
            'company_id',
            sa.Integer(),
            sa.ForeignKey('companies.id', ondelete='CASCADE'),
            primary_key=True
        ),
    )
    op.create_index(f'ix_{table_name}_company_id', table_name, ['company_id'])


def upgrade():
    # ---------------------------------------------------------
    # 1. Tabla de empresas
    # ---------------------------------------------------------
    op.create_table(
        'companies',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('legal_name', sa.String(), nullable=True),
        sa.Column('tax_id', sa.String(20), nullable=True),
        sa.Column('fiscal_address', sa.String(), nullable=True),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('rgpd_text', sa.Text(), nullable=True),
        sa.Column('logo_path', sa.String(), nullable=True),
        sa.Column('primary_color', sa.String(7), nullable=True),
        sa.Column('document_prefix', sa.String(20), nullable=True),
        sa.Column('email_sender_name', sa.String(), nullable=True),
        sa.Column('whatsapp_phone', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_companies_code', 'companies', ['code'], unique=True)

    _seed_companies()

    # ---------------------------------------------------------
    # 2. Entidades con una sola empresa
    # ---------------------------------------------------------
    _add_company_fk('properties')
    _add_company_fk('buyers')

    # ---------------------------------------------------------
    # 3. Pertenencia N:M (pueden estar en ambas empresas)
    # ---------------------------------------------------------
    _create_membership('user_companies', 'users', 'user_id')
    _create_membership('agent_companies', 'agents', 'agent_id')
    _create_membership('client_companies', 'clients', 'client_id')

    # Backfill: quien ya tenía "MOES..." en el texto libre `company` va a
    # MOES; el resto (incluido NULL y "Moyza"/"MOYZA") va a MOYZA.
    for table_name, owner_table, owner_col in [
        ('user_companies', 'users', 'user_id'),
        ('agent_companies', 'agents', 'agent_id'),
    ]:
        op.execute(f"""
            INSERT INTO {table_name} ({owner_col}, company_id)
            SELECT o.id, c.id
            FROM {owner_table} o
            JOIN companies c ON c.code = CASE
                WHEN o.company ILIKE 'MOES%' THEN 'MOES'
                ELSE 'MOYZA'
            END
        """)

    # Los clientes no tenían campo empresa: todos a MOYZA
    op.execute("""
        INSERT INTO client_companies (client_id, company_id)
        SELECT cl.id, c.id
        FROM clients cl
        JOIN companies c ON c.code = 'MOYZA'
    """)


def downgrade():
    for table_name in ['client_companies', 'agent_companies', 'user_companies']:
        op.drop_index(f'ix_{table_name}_company_id', table_name=table_name)
        op.drop_table(table_name)

    for table_name in ['buyers', 'properties']:
        op.drop_index(f'ix_{table_name}_company_id', table_name=table_name)
        op.drop_constraint(f'fk_{table_name}_company_id', table_name, type_='foreignkey')
        op.drop_column(table_name, 'company_id')

    op.drop_index('ix_companies_code', table_name='companies')
    op.drop_table('companies')
