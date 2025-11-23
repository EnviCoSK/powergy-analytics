from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from .settings import DATABASE_URL

# Definuj Base tu (žiadny import z models!)
Base = declarative_base()

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db():
    """Vytvorí tabuľky podľa modelov. Pokračuje aj keď tabuľky už existujú."""
    try:
    # vytvorí tabuľky podľa modelov, ktoré importujú Base z tohto modulu
    Base.metadata.create_all(bind=engine)

    # index na dátum – Postgres (bezpečné, IF NOT EXISTS)
        try:
    with engine.connect() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gsd_date ON gas_storage_daily(date);"))
        conn.commit()
        except Exception as idx_error:
            # Index možno už existuje alebo nie je dostupná databáza
            print(f"Note: Could not create index (may already exist): {idx_error}")
    except Exception as e:
        print(f"Warning: Database initialization error: {e}")
        raise
