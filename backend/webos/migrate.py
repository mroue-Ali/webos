from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def upgrade(database_url: str) -> None:
    """Bring the database schema up to date, creating the SQLite file's folder if needed."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    # configparser treats % as interpolation, so escape it.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
