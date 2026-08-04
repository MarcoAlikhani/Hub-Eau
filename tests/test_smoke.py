"""Smoke tests: verify the package is correctly installed and importable.

These are deliberately trivial. Their job is to catch packaging failures --
a missing __init__.py, a broken src layout, a subpackage left out of the
wheel -- before any real logic exists to obscure the cause.
"""

import importlib

import pytest

# Every subpackage that must be importable. If one is missing from the
# built wheel, this list is what tells us which one.
SUBPACKAGES = [
    "flood_etl",
    "flood_etl.extract",
    "flood_etl.transform",
    "flood_etl.load",
]


@pytest.mark.parametrize("module_name", SUBPACKAGES)
def test_subpackage_is_importable(module_name: str) -> None:
    """Each subpackage imports without error."""
    # import_module() imports by string name, so we can drive it from a list
    # instead of writing four near-identical test functions.
    assert importlib.import_module(module_name) is not None


@pytest.mark.parametrize("module_name", SUBPACKAGES)
def test_subpackage_is_a_real_package(module_name: str) -> None:
    """Each subpackage is a regular package, not a PEP 420 namespace package.

    A namespace package (a directory with no __init__.py) still imports
    successfully, which makes a plain import test a false positive. Regular
    packages have __file__ set; namespace packages do not.
    """
    module = importlib.import_module(module_name)
    assert getattr(module, "__file__", None) is not None, (
        f"{module_name} is a namespace package -- its __init__.py is missing"
    )