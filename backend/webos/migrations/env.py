from alembic import context
from sqlalchemy import create_engine, pool

from webos.config import Settings
from webos.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # `webos-admin migrate` passes the URL in; the bare `alembic` CLI falls back to settings.
    return config.get_main_option("sqlalchemy.url") or Settings().database_url


def run_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        # Batch mode: SQLite can't ALTER most things, so Alembic rebuilds tables instead.
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
