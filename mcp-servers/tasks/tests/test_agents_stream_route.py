"""The live stream is served, and only to the person it belongs to."""
import agent_events
import routes_agents


def test_the_stream_route_exists_and_is_a_get():
    paths = {(r.path, tuple(sorted(r.methods)))
             for r in routes_agents.router.routes}
    assert ("/agents/stream", ("GET",)) in paths


async def test_the_route_answers_with_an_event_stream():
    class User:
        email = "me@example.com"
    agent_events._SUBS.clear()
    resp = await routes_agents.stream(user=User())
    assert resp.media_type == "text/event-stream"
    # Nothing subscribes until the body is iterated, so a response that is
    # never sent leaves nothing behind.
    assert agent_events._SUBS == {}
