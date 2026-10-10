import pytest

from usse.settings import Settings


def test_real_schema_and_location():
    s = Settings(lake_root="s3a://usse-lake/", schema_prefix="")
    assert s.schema("brz") == "brz"
    assert s.location("gld") == "s3a://usse-lake/gld"


def test_ci_schema_is_isolated():
    s = Settings(lake_root="s3a://usse-ci", schema_prefix="ci_")
    assert s.schema("slv") == "ci_slv"
    assert s.location("slv") == "s3a://usse-ci/ci_slv"


def test_unknown_layer_rejected():
    with pytest.raises(ValueError):
        Settings(lake_root="s3a://x", schema_prefix="").schema("silver")
