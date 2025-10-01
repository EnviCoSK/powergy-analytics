from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .settings import DATABASE_URL
from .models import Base

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db():
    # vytvorí tabuľky ak neexistujú
    Base.metadata.create_all(bind=engine)

    # vytvorí index ak neexistuje
    with engine.connect() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gsd_date ON gas_storage_daily(date);"))
        conn.commit()
