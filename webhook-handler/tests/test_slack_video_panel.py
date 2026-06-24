"""Tests for Slack Block Kit builders for the Video Studio panel, modals,
and result/list blocks. Pure (no I/O)."""
import pytest

from handlers.slack_video_panel import (
    build_video_panel,
    build_video_modal,
    parse_video_modal,
    build_result_blocks,
    build_refine_modal,
    build_proposal_blocks,
    build_list_blocks,
    NEW_ID,
    LIST_ID,
    CREATE_CALLBACK,
    REFINE_PREFIX,
    REFINE_CALLBACK,
    APPLY_PREFIX,
    STYLES,
    VOICES,
    MODES,
    DEFAULT_STYLE,
    DEFAULT_VOICE,
    DEFAULT_MODE,
    is_vid_new,
    is_vid_list,
    is_vid_refine,
    is_vid_apply,
    job_from_refine,
    job_from_apply,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _action_ids(blocks: list[dict]) -> list[str]:
    ids: list[str] = []
    for b in blocks:
        if b.get("type") == "actions":
            for el in b.get("elements", []):
                if "action_id" in el:
                    ids.append(el["action_id"])
    return ids


def _block_ids(blocks: list[dict]) -> set[str]:
    return {b.get("block_id") for b in blocks if b.get("block_id")}


def _section_text(blocks: list[dict]) -> str:
    return " ".join(
        b.get("text", {}).get("text", "")
        for b in blocks
        if b.get("type") == "section"
    )


# ---------------------------------------------------------------------------
# build_video_panel
# ---------------------------------------------------------------------------

def test_video_panel_returns_dict_with_blocks():
    panel = build_video_panel()
    assert isinstance(panel, dict)
    assert "blocks" in panel


def test_video_panel_has_two_buttons():
    panel = build_video_panel()
    ids = _action_ids(panel["blocks"])
    assert NEW_ID in ids
    assert LIST_ID in ids


def test_video_panel_new_button_is_primary():
    panel = build_video_panel()
    for b in panel["blocks"]:
        if b.get("type") == "actions":
            for el in b.get("elements", []):
                if el.get("action_id") == NEW_ID:
                    assert el.get("style") == "primary"


def test_video_panel_has_header_block():
    panel = build_video_panel()
    assert any(b.get("type") == "header" for b in panel["blocks"])


# ---------------------------------------------------------------------------
# build_video_modal
# ---------------------------------------------------------------------------

def test_video_modal_is_modal_type():
    view = build_video_modal("C123")
    assert view["type"] == "modal"


def test_video_modal_callback_id():
    view = build_video_modal("C123")
    assert view["callback_id"] == CREATE_CALLBACK


def test_video_modal_private_metadata_is_channel_id():
    view = build_video_modal("C999")
    assert view["private_metadata"] == "C999"


def test_video_modal_has_required_input_blocks():
    view = build_video_modal("C123")
    block_ids = _block_ids(view["blocks"])
    for bid in ("url", "prompt", "title", "style", "voice", "mode"):
        assert bid in block_ids, f"missing block_id: {bid}"


def test_video_modal_title_submit_close():
    view = build_video_modal("C123")
    assert view["title"]["type"] == "plain_text"
    assert view["submit"]["text"] == "Generate"
    assert view["close"]["text"] == "Cancel"


def test_video_modal_style_has_initial_option_matching_default():
    view = build_video_modal("C123")
    style_block = next(b for b in view["blocks"] if b.get("block_id") == "style")
    el = style_block["element"]
    assert el["type"] == "static_select"
    assert el["initial_option"]["value"] == DEFAULT_STYLE


def test_video_modal_voice_has_initial_option_matching_default():
    view = build_video_modal("C123")
    voice_block = next(b for b in view["blocks"] if b.get("block_id") == "voice")
    el = voice_block["element"]
    assert el["initial_option"]["value"] == DEFAULT_VOICE


def test_video_modal_mode_has_initial_option_matching_default():
    view = build_video_modal("C123")
    mode_block = next(b for b in view["blocks"] if b.get("block_id") == "mode")
    el = mode_block["element"]
    assert el["initial_option"]["value"] == DEFAULT_MODE


def test_video_modal_url_block_not_optional():
    view = build_video_modal("C123")
    url_block = next(b for b in view["blocks"] if b.get("block_id") == "url")
    assert url_block.get("optional") is not True


def test_video_modal_style_options_cover_all_styles():
    view = build_video_modal("C123")
    style_block = next(b for b in view["blocks"] if b.get("block_id") == "style")
    option_values = {o["value"] for o in style_block["element"]["options"]}
    for val, _ in STYLES:
        assert val in option_values


# ---------------------------------------------------------------------------
# parse_video_modal
# ---------------------------------------------------------------------------

def _make_view(
    url: str = "https://example.com",
    prompt: str = "walk through checkout",
    title: str = "My Video",
    style: str = "cinematic",
    voice: str = "ryan",
    mode: str = "animated",
    channel_id: str = "C42",
) -> dict:
    """Build a realistic view_submission view dict as Slack sends it."""
    return {
        "private_metadata": channel_id,
        "state": {
            "values": {
                "url": {"url": {"type": "plain_text_input", "value": url}},
                "prompt": {"prompt": {"type": "plain_text_input", "value": prompt}},
                "title": {"title": {"type": "plain_text_input", "value": title}},
                "style": {
                    "style": {
                        "type": "static_select",
                        "selected_option": {
                            "value": style,
                            "text": {"type": "plain_text", "text": "Cinematic"},
                        },
                    }
                },
                "voice": {
                    "voice": {
                        "type": "static_select",
                        "selected_option": {
                            "value": voice,
                            "text": {"type": "plain_text", "text": "Ryan"},
                        },
                    }
                },
                "mode": {
                    "mode": {
                        "type": "static_select",
                        "selected_option": {
                            "value": mode,
                            "text": {"type": "plain_text", "text": "Animated"},
                        },
                    }
                },
            }
        },
    }


def test_parse_video_modal_round_trips_all_fields():
    view = _make_view()
    result = parse_video_modal(view)
    assert result["url"] == "https://example.com"
    assert result["prompt"] == "walk through checkout"
    assert result["title"] == "My Video"
    assert result["style"] == "cinematic"
    assert result["voice"] == "ryan"
    assert result["mode"] == "animated"
    assert result["channel_id"] == "C42"


def test_parse_video_modal_empty_title_returns_none():
    view = _make_view(title="")
    result = parse_video_modal(view)
    assert result["title"] is None


def test_parse_video_modal_whitespace_only_title_returns_none():
    view = _make_view(title="   ")
    result = parse_video_modal(view)
    assert result["title"] is None


def test_parse_video_modal_defaults_when_select_absent():
    """Missing selected_option falls back to DEFAULT_* values."""
    view = {
        "private_metadata": "C1",
        "state": {
            "values": {
                "url": {"url": {"value": "https://x.com"}},
                "prompt": {"prompt": {"value": "show the app"}},
                "title": {"title": {"value": ""}},
                "style": {"style": {}},
                "voice": {"voice": {}},
                "mode": {"mode": {}},
            }
        },
    }
    result = parse_video_modal(view)
    assert result["style"] == DEFAULT_STYLE
    assert result["voice"] == DEFAULT_VOICE
    assert result["mode"] == DEFAULT_MODE


def test_parse_video_modal_channel_id_from_private_metadata():
    view = _make_view(channel_id="CCHANNEL")
    result = parse_video_modal(view)
    assert result["channel_id"] == "CCHANNEL"


# ---------------------------------------------------------------------------
# build_refine_modal
# ---------------------------------------------------------------------------

def test_refine_modal_is_modal():
    view = build_refine_modal("job-abc")
    assert view["type"] == "modal"


def test_refine_modal_callback_id():
    view = build_refine_modal("job-abc")
    assert view["callback_id"] == REFINE_CALLBACK


def test_refine_modal_private_metadata_is_job_id():
    view = build_refine_modal("job-xyz")
    assert view["private_metadata"] == "job-xyz"


def test_refine_modal_has_change_input_block():
    view = build_refine_modal("job-abc")
    block_ids = _block_ids(view["blocks"])
    assert "change" in block_ids


def test_refine_modal_change_block_is_multiline():
    view = build_refine_modal("job-abc")
    change_block = next(b for b in view["blocks"] if b.get("block_id") == "change")
    assert change_block["element"]["multiline"] is True


# ---------------------------------------------------------------------------
# build_result_blocks
# ---------------------------------------------------------------------------

def test_result_blocks_contain_share_url():
    blocks = build_result_blocks("job-1", "My title", "https://share/vid")
    texts = _section_text(blocks)
    assert "https://share/vid" in texts


def test_result_blocks_has_refine_button():
    blocks = build_result_blocks("job-1", "My title", "https://share/vid")
    ids = _action_ids(blocks)
    assert f"{REFINE_PREFIX}job-1" in ids


def test_result_blocks_title_in_section():
    blocks = build_result_blocks("job-2", "Demo Video", "https://share/vid2")
    texts = _section_text(blocks)
    assert "Demo Video" in texts


def test_result_blocks_returns_list():
    blocks = build_result_blocks("job-1", "Title", "https://url")
    assert isinstance(blocks, list)
    assert len(blocks) >= 1


# ---------------------------------------------------------------------------
# build_proposal_blocks
# ---------------------------------------------------------------------------

def test_proposal_blocks_has_apply_button():
    blocks = build_proposal_blocks("job-3")
    ids = _action_ids(blocks)
    assert f"{APPLY_PREFIX}job-3" in ids


def test_proposal_blocks_apply_is_primary():
    blocks = build_proposal_blocks("job-3")
    for b in blocks:
        if b.get("type") == "actions":
            for el in b.get("elements", []):
                if el.get("action_id") == f"{APPLY_PREFIX}job-3":
                    assert el.get("style") == "primary"


def test_proposal_blocks_returns_list():
    blocks = build_proposal_blocks("job-3")
    assert isinstance(blocks, list)


# ---------------------------------------------------------------------------
# build_list_blocks
# ---------------------------------------------------------------------------

def test_list_blocks_has_header():
    blocks = build_list_blocks([])
    assert any(b.get("type") == "header" for b in blocks)


def test_list_blocks_done_job_has_refine_button():
    jobs = [{"id": "j1", "title": "My Video", "status": "done"}]
    blocks = build_list_blocks(jobs)
    ids = _action_ids(blocks)
    assert f"{REFINE_PREFIX}j1" in ids


def test_list_blocks_pending_job_has_no_refine_button():
    jobs = [{"id": "j2", "title": "Pending", "status": "pending"}]
    blocks = build_list_blocks(jobs)
    ids = _action_ids(blocks)
    assert f"{REFINE_PREFIX}j2" not in ids


def test_list_blocks_capped_at_10():
    jobs = [{"id": f"j{i}", "title": f"V{i}", "status": "done"} for i in range(15)]
    blocks = build_list_blocks(jobs)
    refine_ids = [aid for aid in _action_ids(blocks) if aid.startswith(REFINE_PREFIX)]
    assert len(refine_ids) <= 10


def test_list_blocks_job_title_in_section():
    jobs = [{"id": "j1", "title": "Cool Video", "status": "done"}]
    blocks = build_list_blocks(jobs)
    texts = _section_text(blocks)
    assert "Cool Video" in texts


def test_list_blocks_empty_jobs_shows_no_videos_message():
    blocks = build_list_blocks([])
    texts = _section_text(blocks).lower()
    assert "no videos" in texts or "no video" in texts


# ---------------------------------------------------------------------------
# Predicates / extractors
# ---------------------------------------------------------------------------

def test_is_vid_new_exact_match():
    assert is_vid_new(NEW_ID)
    assert not is_vid_new(LIST_ID)
    assert not is_vid_new("other")
    assert not is_vid_new("")


def test_is_vid_list_exact_match():
    assert is_vid_list(LIST_ID)
    assert not is_vid_list(NEW_ID)
    assert not is_vid_list("")


def test_is_vid_refine_true_for_prefix():
    assert is_vid_refine("slackvid_refine:abc")
    assert is_vid_refine(f"{REFINE_PREFIX}job-123")
    assert not is_vid_refine("slackvid_apply:abc")
    assert not is_vid_refine("other")
    assert not is_vid_refine("")


def test_job_from_refine_extracts_id():
    assert job_from_refine("slackvid_refine:abc") == "abc"
    assert job_from_refine("slackvid_refine:job-123") == "job-123"


def test_is_vid_apply_true_for_prefix():
    assert is_vid_apply("slackvid_apply:xyz")
    assert is_vid_apply(f"{APPLY_PREFIX}job-abc")
    assert not is_vid_apply("slackvid_refine:xyz")
    assert not is_vid_apply("")


def test_job_from_apply_extracts_id():
    assert job_from_apply("slackvid_apply:xyz") == "xyz"
    assert job_from_apply(f"{APPLY_PREFIX}job-99") == "job-99"
