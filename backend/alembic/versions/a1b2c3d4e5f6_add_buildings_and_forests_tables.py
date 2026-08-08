"""add buildings and forests tables

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-08-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'buildings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('estimated_height', sa.Integer(), server_default='10', nullable=False),
        sa.Column('geom', geoalchemy2.Geometry('POLYGON', srid=4326, spatial_index=False)),
    )
    op.create_index('ix_buildings_geom', 'buildings', ['geom'], postgresql_using='gist')
    op.create_table(
        'forests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('estimated_height', sa.Integer(), server_default='30', nullable=False),
        sa.Column('geom', geoalchemy2.Geometry('MULTIPOLYGON', srid=4326, spatial_index=False)),
    )
    op.create_index('ix_forests_geom', 'forests', ['geom'], postgresql_using='gist')


def downgrade() -> None:
    op.drop_table('forests')
    op.drop_table('buildings')