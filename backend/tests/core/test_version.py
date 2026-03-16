from app.core.version import APP_NAME, APP_VERSION


def test_app_name_constant() -> None:
    assert APP_NAME == "mission-control"


def test_app_version_semver_format() -> None:
    parts = APP_VERSION.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
