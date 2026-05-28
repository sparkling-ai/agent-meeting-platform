"""Add RBAC fields: room visibility, max_participants; update member default role

Revision ID: rbac_phase2
Revises: ce67480fa092
Create Date: 2026-05-28

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "rbac_phase2"
down_revision = "ce67480fa092"
branch_labels = None
depends_on = None

SCHEMA = "agent_meeting_dev"


def upgrade() -> None:
    # Add visibility column to rooms
    op.add_column(
        "rooms",
        sa.Column("visibility", sa.String(20), nullable=False, server_default="unlisted"),
        schema=SCHEMA,
    )
    # Add max_participants column to rooms
    op.add_column(
        "rooms",
        sa.Column("max_participants", sa.Integer(), nullable=False, server_default="20"),
        schema=SCHEMA,
    )
    # Update existing room_members.role from 'participant' to 'member'
    op.execute(
        f"UPDATE {SCHEMA}.room_members SET role = 'member' WHERE role = 'participant'"
    )


def downgrade() -> None:
    op.drop_column("rooms", "max_participants", schema=SCHEMA)
    op.drop_column("rooms", "visibility", schema=SCHEMA)
    # Revert member roles
    op.execute(
        f"UPDATE {SCHEMA}.room_members SET role = 'participant' WHERE role IN ('member', 'owner', 'moderator', 'observer')"
    )
