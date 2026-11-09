"""make_video says which video it started, in the line the page reads
(2026-11-09). Run through the real tool, and checked with the same pattern
the service uses to keep the line, so the two cannot drift apart."""
import asyncio
import importlib.util
import os

import agent_artifacts

TOOL = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                    "open-webui-functions", "video_tool.py")
JOB = "55785e0a-a4e4-4d4c-a2d5-5747c8899019"


def _tool():
    spec = importlib.util.spec_from_file_location("video_tool_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tool = module.Tools()

    async def call(method, path, email, body=None):
        if path.endswith("/queue"):
            return True, {"queue_position": 0}
        return True, {"id": JOB}

    tool._call = call
    return tool


def test_the_reply_declares_the_video_on_a_line_of_its_own():
    said = asyncio.run(_tool().make_video(
        url="https://example.com", __user__={"email": "r@example.com"}))
    assert said.endswith("\n\n[aiui-artifact]: #video/" + JOB)
    convo = [{"role": "user", "content": "make a video"},
             {"role": "tool", "content": said}]
    assert agent_artifacts.declared_this_turn(convo) == [
        "[aiui-artifact]: #video/" + JOB]


def test_a_job_just_queued_is_not_said_to_be_rendering():
    """All that has happened when the tool answers is that the job joined
    the queue, and the worker leaves it there while the server is short of
    memory."""
    said = asyncio.run(_tool().make_video(
        url="https://example.com", __user__={"email": "r@example.com"}))
    assert "rendering" not in said.lower()
    assert "in the queue" in said
    assert "in this chat" in said


def test_the_model_is_told_the_same():
    """The docstring is what a model reads, and it was telling it to say
    rendering whatever the tool answered."""
    doc = " ".join(_tool().make_video.__doc__.split())
    assert "Tell them it is rendering" not in doc
    assert "Tell them it is queued" in doc


def test_the_skill_says_the_same():
    skill = os.path.join(os.path.dirname(__file__), "..", "agent_skills",
                         "make-a-video", "SKILL.md")
    with open(skill, encoding="utf-8") as fh:
        text = fh.read()
    assert "Say it is rendering" not in text
    assert "Say it is in the queue" in text


def test_the_older_sentence_is_still_written():
    """Chats already saved were read by it, and the page still reads it."""
    said = asyncio.run(_tool().make_video(
        url="https://example.com", __user__={"email": "r@example.com"}))
    assert "Its id is " + JOB in said
