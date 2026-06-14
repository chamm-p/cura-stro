"""initial — users

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    user_role = postgresql.ENUM("admin", "user", name="user_role")
    auth_method = postgresql.ENUM("local", "oidc", name="auth_method")
    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)
    auth_method.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column(
            "role",
            postgresql.ENUM("admin", "user", name="user_role", create_type=False),
            nullable=False,
            server_default="admin",
        ),
        sa.Column(
            "auth_method",
            postgresql.ENUM("local", "oidc", name="auth_method", create_type=False),
            nullable=False,
            server_default="local",
        ),
        sa.Column("oidc_subject", sa.String(255), nullable=True),
        sa.Column("first_name", sa.String(128), nullable=True),
        sa.Column("last_name", sa.String(128), nullable=True),
        sa.Column("full_name", sa.String(256), nullable=True),
        sa.Column("settings", postgresql.JSONB(), nullable=True),
        sa.Column("language", sa.String(8), nullable=False, server_default="de"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
    bind = op.get_bind()
    postgresql.ENUM(name="auth_method").drop(bind, checkfirst=True)
    postgresql.ENUM(name="user_role").drop(bind, checkfirst=True)
