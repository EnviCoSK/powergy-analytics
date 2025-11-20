from sqlalchemy import Column, Date, Float, Integer, Index, String, Text
from .database import Base

class GasStorageDaily(Base):
    __tablename__ = "gas_storage_daily"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, index=True, unique=True, nullable=False)
    percent = Column(Float, nullable=False)
    delta = Column(Float)
    comment = Column(Text)

# 🔑 pridaj index aj explicitne (nie je nutné, ale odporúča sa)
Index("idx_gsd_date", GasStorageDaily.date)
