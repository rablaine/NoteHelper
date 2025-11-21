"""modify_account_linking_fk_to_set_null_on_delete

Revision ID: 0651a34c13a4
Revises: 053c230e94fe
Create Date: 2025-11-20 19:07:39.154833

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0651a34c13a4'
down_revision = '053c230e94fe'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the existing foreign key constraint
    op.drop_constraint('account_linking_requests_requesting_user_id_fkey', 'account_linking_requests', type_='foreignkey')
    
    # Make requesting_user_id nullable
    op.alter_column('account_linking_requests', 'requesting_user_id',
                    existing_type=sa.INTEGER(),
                    nullable=True)
    
    # Recreate the foreign key with ON DELETE SET NULL
    op.create_foreign_key('account_linking_requests_requesting_user_id_fkey',
                          'account_linking_requests', 'users',
                          ['requesting_user_id'], ['id'],
                          ondelete='SET NULL')


def downgrade():
    # Drop the modified foreign key
    op.drop_constraint('account_linking_requests_requesting_user_id_fkey', 'account_linking_requests', type_='foreignkey')
    
    # Make requesting_user_id non-nullable again
    op.alter_column('account_linking_requests', 'requesting_user_id',
                    existing_type=sa.INTEGER(),
                    nullable=False)
    
    # Recreate the original foreign key without ON DELETE SET NULL
    op.create_foreign_key('account_linking_requests_requesting_user_id_fkey',
                          'account_linking_requests', 'users',
                          ['requesting_user_id'], ['id'])
