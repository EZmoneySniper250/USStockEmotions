"""Environment-driven settings. Switching local S3 -> AWS S3 or real -> CI is config only."""

import os
from dataclasses import dataclass

LAYERS = ("brz", "slv", "gld")


@dataclass(frozen=True)
class Settings:
    lake_root: str      # e.g. s3a://usse-lake (real) or s3a://usse-ci (CI)
    schema_prefix: str  # "" (real) or "ci_" (CI)

    def schema(self, layer: str) -> str:
        if layer not in LAYERS:
            raise ValueError(f"unknown layer: {layer}")
        return f"{self.schema_prefix}{layer}"

    def location(self, layer: str) -> str:
        return f"{self.lake_root.rstrip('/')}/{self.schema(layer)}"


def load_settings() -> Settings:
    return Settings(
        lake_root=os.environ.get("USSE_LAKE_ROOT", "s3a://usse-lake"),
        schema_prefix=os.environ.get("USSE_SCHEMA_PREFIX", ""),
    )
