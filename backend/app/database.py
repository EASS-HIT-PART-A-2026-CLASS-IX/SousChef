import os

from sqlmodel import SQLModel, create_engine, Session

from app.observability import get_logger, trace_call

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./recipes.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


@trace_call
def create_db_and_tables() -> None:
    """Create all tables defined via SQLModel metadata."""
    logger.info("Creating database tables")
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency that yields a DB session."""
    logger.info("Opening database session")
    with Session(engine) as session:
        try:
            yield session
        finally:
            logger.info("Closing database session")
