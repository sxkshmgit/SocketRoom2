from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# SQL Server connection settings.
# No username or password is given, so the mssql+pyodbc dialect automatically
# uses Windows Authentication (Trusted Connection).
SQL_SERVER = r".\SQLEXPRESS"
DATABASE_NAME = "SocketRoomDB"
ODBC_DRIVER = "ODBC Driver 17 for SQL Server"

DATABASE_URL = URL.create(
    drivername="mssql+pyodbc",
    host=SQL_SERVER,
    database=DATABASE_NAME,
    query={"driver": ODBC_DRIVER},
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()