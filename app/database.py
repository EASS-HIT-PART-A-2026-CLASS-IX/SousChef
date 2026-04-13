from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = "sqlite:///./recipes.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


def create_db_and_tables() -> None:
    """Create all tables defined via SQLModel metadata."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency that yields a DB session."""
    with Session(engine) as session:
        yield session
