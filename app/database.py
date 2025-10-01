from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from .settings import DATABASE_URL

# Definuj Base tu (žiadny import z models!)
Base = declarative_base()

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db():
    # vytvorí tabuľky podľa modelov, ktoré importujú Base z tohto modulu
    Base.metadata.create_all(bind=engine)

    # index na dátum – Postgres (bezpečné, IF NOT EXISTS)
    with engine.connect() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gsd_date ON gas_storage_daily(date);"))
        conn.commit()
