"""A platform stays dark until its environment is supplied.

Same dormant-by-default shape as the Google sign-in wiring: the code ships,
nothing appears, and deploying changes nothing visible until someone sets a
token. That is what makes it safe to merge this before a bot exists.
"""
from gateway.base import BasePlatformAdapter
from gateway.registry import PlatformEntry, PlatformRegistry


class FakeAdapter(BasePlatformAdapter):
    name = "fake"

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        pass

    def parse_inbound(self, payload, headers):
        return None

    async def send(self, chat_id: str, text: str) -> None:
        pass


def _entry(**over) -> PlatformEntry:
    base = dict(name="fake", label="Fake", adapter_factory=FakeAdapter,
                required_env=["FAKE_TOKEN"], max_message_length=100)
    base.update(over)
    return PlatformEntry(**base)


def test_a_platform_with_unset_env_is_not_enabled(monkeypatch):
    monkeypatch.delenv("FAKE_TOKEN", raising=False)
    reg = PlatformRegistry()
    reg.register(_entry())
    assert reg.is_enabled("fake") is False
    assert reg.enabled() == []
    assert reg.adapter("fake") is None


def test_a_blank_env_value_does_not_count_as_set(monkeypatch):
    monkeypatch.setenv("FAKE_TOKEN", "   ")
    reg = PlatformRegistry()
    reg.register(_entry())
    assert reg.is_enabled("fake") is False


def test_every_required_var_must_be_present(monkeypatch):
    monkeypatch.setenv("FAKE_TOKEN", "t")
    monkeypatch.delenv("FAKE_SECRET", raising=False)
    reg = PlatformRegistry()
    reg.register(_entry(required_env=["FAKE_TOKEN", "FAKE_SECRET"]))
    assert reg.is_enabled("fake") is False


def test_an_enabled_platform_yields_one_cached_adapter(monkeypatch):
    monkeypatch.setenv("FAKE_TOKEN", "t")
    reg = PlatformRegistry()
    reg.register(_entry())
    first = reg.adapter("fake")
    assert isinstance(first, FakeAdapter)
    assert reg.adapter("fake") is first, "a new client per message would leak sockets"


def test_the_adapter_is_told_its_message_limit(monkeypatch):
    monkeypatch.setenv("FAKE_TOKEN", "t")
    reg = PlatformRegistry()
    reg.register(_entry())
    assert reg.adapter("fake").max_message_length == 100


def test_a_platform_with_no_required_env_is_always_enabled():
    reg = PlatformRegistry()
    reg.register(_entry(name="cli", required_env=[]))
    assert reg.is_enabled("cli") is True


def test_an_unknown_platform_is_not_enabled_and_has_no_adapter():
    reg = PlatformRegistry()
    assert reg.is_enabled("nope") is False
    assert reg.adapter("nope") is None


def test_registering_twice_replaces_rather_than_duplicates(monkeypatch):
    monkeypatch.setenv("FAKE_TOKEN", "t")
    reg = PlatformRegistry()
    reg.register(_entry())
    reg.register(_entry(label="Fake 2"))
    assert reg.all_names() == ["fake"]
    assert reg.enabled()[0].label == "Fake 2"
