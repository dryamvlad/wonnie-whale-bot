"""init

Revision ID: 51b72b053c46
Revises: 
Create Date: 2024-05-29 17:56:47.833837

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "51b72b053c46"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "users",
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("balance", sa.Integer(), nullable=False),
        sa.Column("entry_balance", sa.Integer(), nullable=False),
        sa.Column("blacklisted", sa.Boolean(), nullable=False),
        sa.Column("banned", sa.Boolean(), nullable=False),
        sa.Column("invite_link", sa.String(), nullable=True),
        sa.Column("wallet", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tg_user_id"),
    )
    op.create_table(
        "history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("balance_delta", sa.Integer(), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("history")
    op.drop_table("users")
    # ### end Alembic commands ###
