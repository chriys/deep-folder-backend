"""Smoke tests — verify the package can be imported and basic invariants hold."""


def test_package_importable() -> None:
    import deepfolder  # noqa: F401
