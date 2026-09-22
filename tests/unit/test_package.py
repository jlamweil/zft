"""C-01: package is importable and exposes its public surface (plan §2)."""


def test_package_imports():
    import zft

    assert zft.__version__


