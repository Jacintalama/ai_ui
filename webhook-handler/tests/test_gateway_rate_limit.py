"""The public terminal endpoint's only brake.

/webhook/gateway/cli is reachable from the internet without authentication:
Caddy sends /webhook/* straight here, past api-gateway's auth and its rate
limiter. An unpaired device mints a pairing-code row, and device ids are free to
generate, so without something here one host can write rows as fast as it can
open sockets.
"""
import pytest

from gateway.rate_limit import SlidingWindow, client_key


@pytest.fixture
def clock():
    """A hand-cranked clock, so these tests never sleep."""
    class Clock:
        def __init__(self):
            self.t = 1000.0

        def __call__(self):
            return self.t

        def advance(self, seconds):
            self.t += seconds
    return Clock()


def test_requests_under_the_limit_are_allowed(clock):
    w = SlidingWindow(limit=3, window_seconds=60, now=clock)
    assert [w.allow("a") for _ in range(3)] == [True, True, True]


def test_the_one_over_the_limit_is_refused(clock):
    w = SlidingWindow(limit=3, window_seconds=60, now=clock)
    for _ in range(3):
        w.allow("a")
    assert w.allow("a") is False


def test_one_key_cannot_spend_another_keys_budget(clock):
    # The whole point: keys are separate buckets. If they shared, a single
    # noisy host would lock out every other user.
    w = SlidingWindow(limit=2, window_seconds=60, now=clock)
    w.allow("a"); w.allow("a")
    assert w.allow("a") is False
    assert w.allow("b") is True


def test_the_window_slides_rather_than_resetting_on_a_boundary(clock):
    # A fixed bucket that resets on the minute lets a caller send 2x the limit
    # across the boundary. This must expire each hit individually.
    w = SlidingWindow(limit=2, window_seconds=60, now=clock)
    w.allow("a")
    clock.advance(59)
    w.allow("a")
    assert w.allow("a") is False
    clock.advance(1.1)          # the first hit is now older than the window
    assert w.allow("a") is True


def test_a_fully_expired_key_is_allowed_again(clock):
    w = SlidingWindow(limit=1, window_seconds=10, now=clock)
    assert w.allow("a") is True
    assert w.allow("a") is False
    clock.advance(11)
    assert w.allow("a") is True


def test_memory_cannot_grow_without_bound(clock):
    # Keys come from the internet, so an attacker choosing fresh keys must not
    # be able to grow this dict until the box runs out of memory.
    w = SlidingWindow(limit=5, window_seconds=60, max_keys=50, now=clock)
    for i in range(500):
        w.allow(f"key-{i}")
    assert len(w._hits) <= 50


def test_pruning_does_not_lose_an_active_caller(clock):
    # Eviction must drop stale keys, not whichever key happens to be busiest.
    w = SlidingWindow(limit=2, window_seconds=60, max_keys=3, now=clock)
    w.allow("busy")
    clock.advance(120)          # everything so far is now stale
    for i in range(10):
        w.allow(f"other-{i}")
    assert w.allow("busy") is True


def test_cloudflare_header_wins_because_caddy_is_the_direct_peer(clock):
    # request.client.host is Caddy's container address for every request, so
    # keying on it would throttle all users as one.
    key = client_key({"cf-connecting-ip": "203.0.113.7",
                      "x-forwarded-for": "203.0.113.7, 172.22.0.4"},
                     "172.22.0.4")
    assert key == "203.0.113.7"


def test_falls_back_to_the_first_forwarded_hop(clock):
    key = client_key({"x-forwarded-for": "198.51.100.9, 172.22.0.4"}, "172.22.0.4")
    assert key == "198.51.100.9"


def test_falls_back_to_the_peer_when_no_headers_are_present(clock):
    assert client_key({}, "172.22.0.4") == "172.22.0.4"


def test_header_names_are_matched_case_insensitively(clock):
    assert client_key({"CF-Connecting-IP": "203.0.113.7"}, "1.2.3.4") == "203.0.113.7"


def test_a_blank_header_does_not_become_the_key(clock):
    # An empty XFF would otherwise bucket every caller under "", which is one
    # shared limit for the whole internet.
    assert client_key({"x-forwarded-for": "   "}, "172.22.0.4") == "172.22.0.4"


# --- the route, because a correct limiter wired wrong protects nothing --------

DEVICE = "b" * 32


@pytest.fixture
def route_client(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    from gateway.platforms.cli import CliAdapter

    # The registry keeps the CLI dormant unless GATEWAY_CLI_ENABLED is set, so
    # the route would 503 here. Same stand-in the CLI route tests use.
    adapter = CliAdapter()
    adapter.name = "cli"
    adapter.max_message_length = 0
    monkeypatch.setattr(main.gateway_registry, "adapter",
                        lambda name: adapter if name == "cli" else None)

    async def fake_handle(event, adapter_):
        return "ok"

    monkeypatch.setattr(main.gateway_pipeline, "handle_event", fake_handle)
    return TestClient(main.app)


def post(client, ip, device=DEVICE, text="hi"):
    return client.post("/webhook/gateway/cli",
                       json={"device_id": device, "text": text},
                       headers={"X-Forwarded-For": f"{ip}, 172.22.0.4"})


def test_a_caller_within_budget_is_served(route_client):
    assert post(route_client, "203.0.113.10").status_code == 200


def test_a_flood_from_one_address_is_refused(route_client):
    codes = [post(route_client, "203.0.113.11", device=f"{i:032x}").status_code
             for i in range(35)]
    assert 429 in codes, "the public endpoint never refused a flood"
    assert codes[0] == 200, "the very first request should not be refused"


def test_one_flooder_does_not_lock_out_everyone_else(route_client):
    # The reason the key is the forwarded address and not the socket peer:
    # Caddy is the peer for every request, so a shared key would mean one
    # abusive caller takes the terminal channel down for all users.
    for i in range(35):
        post(route_client, "203.0.113.12", device=f"{i:032x}")
    assert post(route_client, "203.0.113.13").status_code == 200


def test_one_runaway_terminal_is_refused_on_its_own_device_budget(route_client):
    # Same address, same device: this is the per-device limit, which is
    # tighter than the per-IP one.
    codes = [post(route_client, "203.0.113.14").status_code for _ in range(25)]
    assert codes.count(429) > 0
    assert codes[0] == 200


def test_a_refused_request_never_reaches_the_pipeline(route_client, monkeypatch):
    import main
    seen = []

    async def counting_handle(event, adapter_):
        seen.append(event.text)
        return "ok"

    monkeypatch.setattr(main.gateway_pipeline, "handle_event", counting_handle)
    for i in range(40):
        post(route_client, "203.0.113.15", device=f"{i:032x}")
    # 30 per IP per minute is the budget; nothing past it may cost model work.
    assert len(seen) <= 30
