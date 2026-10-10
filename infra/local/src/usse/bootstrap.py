"""Create the layer schemas (brz/slv/gld) at their lake locations. Idempotent.

Run: python -m usse.bootstrap
"""

from usse.settings import LAYERS, load_settings
from usse.spark import get_spark


def main() -> None:
    settings = load_settings()
    spark = get_spark("usse-bootstrap")
    for layer in LAYERS:
        schema = settings.schema(layer)
        location = settings.location(layer)
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema} LOCATION '{location}'")
        print(f"schema {schema} -> {location}")
    spark.stop()


if __name__ == "__main__":
    main()
