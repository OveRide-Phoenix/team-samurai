from sqlalchemy import create_engine

from samurai.config import Settings


def test_cloud_sql_socket_url_passes_host_to_psycopg() -> None:
    # Given a Cloud Run Cloud SQL Unix-socket URL accepted by the settings boundary.
    socket_path = "/cloudsql/project:asia-south1:samurai-postgres"
    settings = Settings.model_validate(
        {
            "database_url": (
                f"postgresql+psycopg://samurai:password@localhost/samurai?host={socket_path}"
            )
        }
    )

    # When SQLAlchemy builds psycopg's connection arguments without connecting.
    engine = create_engine(str(settings.database_url))
    _, connect_kwargs = engine.dialect.create_connect_args(engine.url)

    # Then psycopg receives the Unix socket directory as its host.
    assert connect_kwargs["host"] == socket_path
