import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

URL = os.getenv("DATABASE_URL", "sqlite:///./studypulse.db")
engine = create_engine(URL, connect_args={"check_same_thread": False} if URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
