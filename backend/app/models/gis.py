from geoalchemy2 import Geometry
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    estimated_height: Mapped[int] = mapped_column(Integer, default=10)
    geom = mapped_column(Geometry("POLYGON", srid=4326, spatial_index=True))


class Forest(Base):
    __tablename__ = "forests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    estimated_height: Mapped[int] = mapped_column(Integer, default=30)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=True))