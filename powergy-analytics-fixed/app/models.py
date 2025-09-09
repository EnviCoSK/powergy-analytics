from sqlalchemy.orm import declarative_base, mapped_column
from sqlalchemy import Integer, Float, Date, Text, UniqueConstraint

Base = declarative_base()

class GasStorageDaily(Base):
    __tablename__ = "gas_storage_daily"
    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    date = mapped_column(Date, nullable=False, unique=True)
    percent = mapped_column(Float, nullable=False)
    delta = mapped_column(Float, nullable=True)
    comment = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("date", name="uq_gs_date"),)
