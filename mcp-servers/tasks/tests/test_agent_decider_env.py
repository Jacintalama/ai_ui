"""The Jev settings reach the tasks container.

tasks has no env_file: compose hands it only what its environment list
names. A key saved in the server's .env and never named there is a key the
decider never sees, and every team message would quietly keep today's path.
"""
from test_agent_paid_env import _declared, _reaches_container


def test_the_typesafe_key_is_passed_and_blank_without_one():
    assert _declared("TYPESAFE_API_KEY") == (":-", "")
    assert _reaches_container("TYPESAFE_API_KEY", {}) == ""
    assert _reaches_container("TYPESAFE_API_KEY",
                              {"TYPESAFE_API_KEY": "apikey_x"}) == "apikey_x"


def test_the_confidence_bar_is_passed_with_the_designed_default():
    assert _reaches_container("JEV_MIN_CONFIDENCE", {}) == "0.8"
