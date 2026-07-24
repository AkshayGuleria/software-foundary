import pytest

from foundry.drivers.codex import CodexDriver
from foundry.drivers.factory import make_driver
from foundry.drivers.fake import FakeDriver
from foundry.playbook.schema import PlaybookSpec, StepSpec


def test_make_driver_fake_builds_a_scripted_fake_driver():
    playbook = PlaybookSpec(id="x", steps=[StepSpec(id="a", role="developer")])
    driver = make_driver("fake", playbook)
    assert isinstance(driver, FakeDriver)


def test_make_driver_codex_builds_a_codex_driver():
    driver = make_driver("codex")
    assert isinstance(driver, CodexDriver)


def test_make_driver_rejects_unknown_names():
    with pytest.raises(ValueError, match="unknown driver"):
        make_driver("not-a-real-driver")
