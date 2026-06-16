"""add legal visit fields

Revision ID: g5h6i7j8k9l0
Revises: c2c34d595013
Create Date: 2026-06-15 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'g5h6i7j8k9l0'
down_revision = 'c2c34d595013'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar campos de consentimiento de datos
    op.add_column('property_visits',
        sa.Column('data_consent_accepted', sa.Boolean(),
                  nullable=False, server_default='false'))
    op.add_column('property_visits',
        sa.Column('data_consent_accepted_at', sa.DateTime(), nullable=True))
    op.add_column('property_visits',
        sa.Column('data_consent_ip', sa.String(), nullable=True))
    op.add_column('property_visits',
        sa.Column('data_consent_user_agent', sa.String(), nullable=True))

    # Agregar campos de firma digital
    op.add_column('property_visits',
        sa.Column('signature_filename', sa.String(), nullable=True))
    op.add_column('property_visits',
        sa.Column('signature_filepath', sa.String(), nullable=True))
    op.add_column('property_visits',
        sa.Column('signature_captured_at', sa.DateTime(), nullable=True))
    op.add_column('property_visits',
        sa.Column('signature_ip', sa.String(), nullable=True))

    # Agregar campo de estado del proceso
    op.add_column('property_visits',
        sa.Column('visit_status', sa.String(),
                  nullable=False, server_default='completed'))

    # Agregar audit trail como JSON
    op.add_column('property_visits',
        sa.Column('audit_trail', postgresql.JSON(astext_type=sa.Text()),
                  nullable=True))

    # Crear tabla de audit logs para trazabilidad detallada
    op.create_table('visit_audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('visit_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('event_data', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('ip_address', sa.String(), nullable=True),
        sa.Column('user_agent', sa.String(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['visit_id'], ['property_visits.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_visit_audit_logs_id'), 'visit_audit_logs', ['id'], unique=False)
    op.create_index(op.f('ix_visit_audit_logs_visit_id'), 'visit_audit_logs', ['visit_id'], unique=False)

    # Crear tabla OTP para preparación futura (no se usará de inmediato)
    op.create_table('visit_otp_verifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('visit_id', sa.Integer(), nullable=False),
        sa.Column('phone_number', sa.String(), nullable=False),
        sa.Column('otp_code', sa.String(), nullable=False),
        sa.Column('otp_sent_at', sa.DateTime(), nullable=False),
        sa.Column('otp_verified_at', sa.DateTime(), nullable=True),
        sa.Column('otp_expires_at', sa.DateTime(), nullable=False),
        sa.Column('verification_method', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.ForeignKeyConstraint(['visit_id'], ['property_visits.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_visit_otp_verifications_id'),
                    'visit_otp_verifications', ['id'], unique=False)


def downgrade():
    # Eliminar tablas
    op.drop_index(op.f('ix_visit_otp_verifications_id'),
                  table_name='visit_otp_verifications')
    op.drop_table('visit_otp_verifications')

    op.drop_index(op.f('ix_visit_audit_logs_visit_id'),
                  table_name='visit_audit_logs')
    op.drop_index(op.f('ix_visit_audit_logs_id'),
                  table_name='visit_audit_logs')
    op.drop_table('visit_audit_logs')

    # Eliminar columnas de property_visits
    op.drop_column('property_visits', 'audit_trail')
    op.drop_column('property_visits', 'visit_status')
    op.drop_column('property_visits', 'signature_ip')
    op.drop_column('property_visits', 'signature_captured_at')
    op.drop_column('property_visits', 'signature_filepath')
    op.drop_column('property_visits', 'signature_filename')
    op.drop_column('property_visits', 'data_consent_user_agent')
    op.drop_column('property_visits', 'data_consent_ip')
    op.drop_column('property_visits', 'data_consent_accepted_at')
    op.drop_column('property_visits', 'data_consent_accepted')
