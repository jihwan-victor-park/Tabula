"""cp2 review fixes

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-20 21:15:30.321360

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing audit rows were all written by people (CP1/CP2 had no agent or system actors).
    op.add_column('audit_events', sa.Column('actor_kind', sa.String(length=10), server_default='human', nullable=False))
    op.alter_column('audit_events', 'actor_kind', server_default=None)
    op.add_column('audit_events', sa.Column('actor_name', sa.String(length=80), nullable=True))
    op.create_check_constraint(op.f('ck_audit_events_actor_kind_valid'), 'audit_events', "actor_kind IN ('human', 'agent', 'system')")

    op.add_column('locations', sa.Column('inventory_write_owner', sa.String(length=20), server_default='tabula', nullable=False))
    op.create_check_constraint(
        op.f('ck_locations_write_owner_valid'), 'locations',
        "inventory_write_owner IN ('tabula', 'square', 'shopify', 'clover', 'lightspeed', 'other')",
    )

    op.add_column('outbox', sa.Column('lease_token', sa.UUID(), nullable=True))
    op.add_column('outbox', sa.Column('retry_safe', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.drop_constraint(op.f('ck_outbox_status_valid'), 'outbox', type_='check')
    op.create_check_constraint(
        op.f('ck_outbox_status_valid'), 'outbox', "status IN ('pending', 'in_flight', 'done', 'dead', 'unknown')"
    )

    op.add_column('suppliers', sa.Column('merchant_account_required', sa.Boolean(), server_default=sa.text('true'), nullable=False))

    # The approval checklist gained merchant account, minimum-order and freight terms.
    # Approved suppliers that do not meet it go back to `candidate` (fail safe), and
    # each demotion is audited as a system action.
    op.execute(
        """
        WITH demoted AS (
            UPDATE suppliers
               SET relationship_status = 'candidate', verified_at = NULL, verified_by_user_id = NULL,
                   version = version + 1, updated_at = now()
             WHERE relationship_status = 'approved'
               AND (merchant_account_number IS NULL
                    OR min_order_amount IS NULL
                    OR coalesce(btrim(freight_notes), '') = '')
         RETURNING id, tenant_id
        )
        INSERT INTO audit_events (id, tenant_id, actor_kind, actor_name, action, object_type, object_id, reason)
        SELECT gen_random_uuid(), tenant_id, 'system', 'migration-0003', 'supplier.candidate', 'supplier', id::text,
               'Approval checklist now requires merchant account, minimum-order and freight terms'
          FROM demoted
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('suppliers', 'merchant_account_required')
    op.execute("UPDATE outbox SET status = 'dead' WHERE status = 'unknown'")
    op.drop_constraint(op.f('ck_outbox_status_valid'), 'outbox', type_='check')
    op.create_check_constraint(op.f('ck_outbox_status_valid'), 'outbox', "status IN ('pending', 'in_flight', 'done', 'dead')")
    op.drop_column('outbox', 'retry_safe')
    op.drop_column('outbox', 'lease_token')
    op.drop_constraint(op.f('ck_locations_write_owner_valid'), 'locations', type_='check')
    op.drop_column('locations', 'inventory_write_owner')
    op.drop_constraint(op.f('ck_audit_events_actor_kind_valid'), 'audit_events', type_='check')
    op.drop_column('audit_events', 'actor_name')
    op.drop_column('audit_events', 'actor_kind')
