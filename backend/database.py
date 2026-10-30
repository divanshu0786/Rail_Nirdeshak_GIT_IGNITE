import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rail_nirdeshak.db")

# Fix Render PostgreSQL URL scheme compatibility with SQLAlchemy 2.0
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# connect_args={"check_same_thread": False} is required for SQLite in FastAPI
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def upgrade_database_schema(eng):
    """Ensure database schema is up-to-date with User columns (username, is_active, last_login)."""
    from sqlalchemy import text
    try:
        with eng.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(users)"))
            cols = [row[1] for row in result.fetchall()]
            if cols:
                if "username" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR"))
                    conn.execute(text("UPDATE users SET username = email WHERE username IS NULL"))
                if "railway_id" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN railway_id VARCHAR(12)"))
                if "is_active" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1"))
                    conn.execute(text("UPDATE users SET is_active = 1 WHERE is_active IS NULL"))
                if "last_login" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN last_login DATETIME"))
                conn.commit()
    except Exception:
        pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
