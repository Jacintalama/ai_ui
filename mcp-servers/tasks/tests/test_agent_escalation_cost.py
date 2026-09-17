"""What a turn on the paid model costs, and the settings that switch the move
to the paid model on and off. No model, no database."""
import pytest

import agent_escalation as esc


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(esc, "PAID_MODEL", "gpt-5.5")
    monkeypatch.setattr(esc, "DAILY_CAP", 40)
    monkeypatch.setattr(esc, "PRICES", {"gpt-5.5": (5.0, 30.0)})


def test_prices_parse_and_a_malformed_entry_is_skipped():
    assert esc.parse_prices("gpt-5.5=5:30, gpt-5-mini=0.25:2,broken=x:1,=1:2,nocolon=5") == {
        "gpt-5.5": (5.0, 30.0), "gpt-5-mini": (0.25, 2.0)}


def test_the_shipped_default_prices_gpt_5_5_at_5_and_30():
    assert esc.parse_prices("gpt-5.5=5:30") == {"gpt-5.5": (5.0, 30.0)}


def test_a_free_model_costs_nothing_and_an_unpriced_one_is_unknown():
    assert esc.cost_of("nvidia/nemotron-3-super-120b-a12b:free", 9000, 900) == 0.0
    assert esc.cost_of("gpt-4o-mini", 1000, 100) is None
    assert esc.cost_of("gpt-5.5", 1_000_000, 0) == pytest.approx(5.0)
    assert esc.cost_of("gpt-5.5", 0, 1_000_000) == pytest.approx(30.0)


def test_usage_sums_every_completion_and_prices_it():
    u = esc.TurnUsage(run_id="r1")
    u.add("gpt-5.5", {"prompt_tokens": 1000, "completion_tokens": 100})
    u.add("gpt-5.5", {"prompt_tokens": 1000, "completion_tokens": 100})
    assert (u.prompt_tokens, u.completion_tokens) == (2000, 200)
    assert u.cost_usd == pytest.approx((2000 * 5 + 200 * 30) / 1_000_000)
    assert u.model == "gpt-5.5"


def test_a_paid_reply_without_usage_makes_the_cost_unknown_not_zero():
    u = esc.TurnUsage()
    u.add("gpt-5.5", None)
    assert u.cost_usd is None


def test_a_free_reply_without_usage_still_costs_nothing():
    u = esc.TurnUsage()
    u.add("nex-agi/nex-n2.5-pro:free", None)
    assert u.cost_usd == 0.0


@pytest.mark.parametrize("usage", [
    {"prompt_tokens": "lots", "completion_tokens": True},
    {},
    {"prompt_tokens": None, "completion_tokens": None},
    # Another provider's names for the same counts. Nothing here reads them,
    # so the cost is unknown rather than priced at nothing.
    {"input_tokens": 7000, "output_tokens": 500},
])
def test_a_paid_reply_with_no_usable_token_counts_is_unknown_not_free(usage):
    # The design: a paid reply without usage records NULL cost, never 0. A
    # usage dict with no number in it says as little as no usage at all.
    u = esc.TurnUsage()
    u.add("gpt-5.5", usage)
    assert (u.prompt_tokens, u.completion_tokens, u.cost_usd) == (0, 0, None)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), -5])
def test_a_count_that_is_not_a_finite_number_of_tokens_is_junk_not_a_crash(bad):
    # json.loads accepts NaN, Infinity and 1e999, and int() raises on the
    # first two, which would fail the whole agent turn over one number.
    u = esc.TurnUsage()
    u.add("gpt-5.5", {"prompt_tokens": bad, "completion_tokens": bad})
    assert (u.prompt_tokens, u.completion_tokens, u.cost_usd) == (0, 0, None)


def test_a_price_that_is_not_a_finite_amount_of_dollars_is_skipped():
    assert esc.parse_prices("gpt-5.5=nan:30,a=5:inf,b=-5:30,c=5:-1,d=0:0") == {
        "d": (0.0, 0.0)}


def test_one_usable_count_is_enough_to_price_a_paid_reply():
    u = esc.TurnUsage()
    u.add("gpt-5.5", {"prompt_tokens": 1000, "completion_tokens": None})
    assert (u.prompt_tokens, u.completion_tokens) == (1000, 0)
    assert u.cost_usd == pytest.approx(1000 * 5 / 1_000_000)


def test_a_free_reply_with_junk_token_counts_still_costs_nothing():
    u = esc.TurnUsage()
    u.add("nex-agi/nex-n2.5-pro:free", {"prompt_tokens": "lots"})
    assert (u.prompt_tokens, u.completion_tokens, u.cost_usd) == (0, 0, 0.0)


def test_blank_model_or_zero_cap_switches_it_off(monkeypatch):
    assert esc.enabled()
    monkeypatch.setattr(esc, "DAILY_CAP", 0)
    assert not esc.enabled()
    monkeypatch.setattr(esc, "DAILY_CAP", 40)
    monkeypatch.setattr(esc, "PAID_MODEL", "")
    assert not esc.enabled()


def test_a_paid_completion_gets_at_least_the_paid_timeout(monkeypatch):
    monkeypatch.setattr(esc, "PAID_TIMEOUT_SECONDS", 90)
    assert esc.paid_timeout(60) == 90
    assert esc.paid_timeout(240) == 240


def test_a_bad_number_in_the_environment_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("AGENT_PAID_DAILY_CAP", "forty")
    assert esc._int_env("AGENT_PAID_DAILY_CAP", 40) == 40
    monkeypatch.setenv("AGENT_PAID_DAILY_CAP", "")
    assert esc._int_env("AGENT_PAID_DAILY_CAP", 40) == 40
    monkeypatch.setenv("AGENT_PAID_DAILY_CAP", "7")
    assert esc._int_env("AGENT_PAID_DAILY_CAP", 40) == 7
