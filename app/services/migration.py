from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import BACKEND_ROOT, settings


def run_db_migrations() -> None:
    alembic_ini = Path(BACKEND_ROOT) / "alembic.ini"
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(Path(BACKEND_ROOT) / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")
