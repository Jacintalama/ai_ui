import os
import video_remotion_render as vrr


async def test_render_remotion_job_orchestrates(tmp_path, monkeypatch):
    slug, jid = "vid-x", "11111111-1111-1111-1111-111111111111"
    base = tmp_path / slug / ".video" / jid
    (base / "screenshots").mkdir(parents=True)
    (base / "screenshots" / "screenshot-1.png").write_bytes(b"x")
    (base / "site_context.json").write_text('{"host":"example.com","title":"Example"}')
    seen = {}

    async def fake_client(job_dir, **kw):
        seen.update(kw)
        seen["job_dir"] = job_dir
        open(os.path.join(job_dir, "remotion-video.mp4"), "wb").write(b"vid")
        return os.path.join(job_dir, "remotion-video.mp4")

    async def fake_synth(text, voice, out_wav):
        return None

    async def fake_mux(video_in, out_path, audio_path, click_times=None):
        open(out_path, "wb").write(b"final")
        return out_path

    monkeypatch.setattr(vrr, "render_remotion", fake_client)
    monkeypatch.setattr(vrr, "_synthesize_narration", fake_synth)
    monkeypatch.setattr(vrr, "_run_audio_mux", fake_mux)
    plan = {"narration_script": "", "scenes": [
        {"kind": "screenshot", "screenshot": "screenshot-1.png", "headline": "h",
         "motion": "zoom-in", "duration_s": 3.0}]}
    out = await vrr.render_remotion_job(str(tmp_path), slug, jid, plan, voice=None)
    assert out.endswith("out.mp4") and os.path.exists(out)
    assert seen["host"] == "example.com" and seen["title"] == "Example"
    assert seen["scenes"][0]["screenshot"].endswith("screenshot-1.png")
    assert os.path.isabs(seen["scenes"][0]["screenshot"])  # abs path passed to service
    assert seen["scenes"][0]["durationS"] == 3.0


async def test_render_remotion_job_passes_narration_to_mux(tmp_path, monkeypatch):
    slug, jid = "vid-a", "22222222-2222-2222-2222-222222222222"
    base = tmp_path / slug / ".video" / jid
    (base / "screenshots").mkdir(parents=True)
    (base / "screenshots" / "screenshot-1.png").write_bytes(b"x")
    seen = {}

    async def fake_client(job_dir, **kw):
        open(os.path.join(job_dir, "remotion-video.mp4"), "wb").write(b"vid")
        return os.path.join(job_dir, "remotion-video.mp4")

    async def fake_synth(text, voice, out_wav):
        open(out_wav, "wb").write(b"RIFF")
        return out_wav

    async def fake_mux(video_in, out_path, audio_path, click_times=None):
        seen["audio_path"] = audio_path
        open(out_path, "wb").write(b"final")
        return out_path

    monkeypatch.setattr(vrr, "render_remotion", fake_client)
    monkeypatch.setattr(vrr, "_synthesize_narration", fake_synth)
    monkeypatch.setattr(vrr, "_run_audio_mux", fake_mux)
    plan = {"narration_script": "walk through it", "scenes": [
        {"kind": "screenshot", "screenshot": "screenshot-1.png", "headline": "h",
         "motion": "zoom-in", "duration_s": 3.0}]}
    await vrr.render_remotion_job(str(tmp_path), slug, jid, plan, voice="amy")
    assert seen["audio_path"] and seen["audio_path"].endswith("narration.wav")


async def test_render_remotion_job_uses_headlines_for_empty_narration_and_animation(tmp_path, monkeypatch):
    slug, jid = "vid-b", "33333333-3333-3333-3333-333333333333"
    base = tmp_path / slug / ".video" / jid
    (base / "screenshots").mkdir(parents=True)
    (base / "screenshots" / "screenshot-1.png").write_bytes(b"x")
    seen = {}

    async def fake_client(job_dir, **kw):
        seen["animationPreset"] = kw.get("animationPreset")
        open(os.path.join(job_dir, "remotion-video.mp4"), "wb").write(b"vid")
        return os.path.join(job_dir, "remotion-video.mp4")

    async def fake_synth(text, voice, out_wav):
        seen["text"] = text
        seen["voice"] = voice
        open(out_wav, "wb").write(b"RIFF")
        return out_wav

    async def fake_mux(video_in, out_path, audio_path, click_times=None):
        seen["audio_path"] = audio_path
        open(out_path, "wb").write(b"final")
        return out_path

    monkeypatch.setattr(vrr, "render_remotion", fake_client)
    monkeypatch.setattr(vrr, "_synthesize_narration", fake_synth)
    monkeypatch.setattr(vrr, "_run_audio_mux", fake_mux)
    plan = {"narration_script": "", "scenes": [
        {"kind": "screenshot", "screenshot": "screenshot-1.png",
         "headline": "Open the dashboard", "subtext": "Click into the reports",
         "motion": "zoom-in", "duration_s": 3.0}]}

    await vrr.render_remotion_job(
        str(tmp_path), slug, jid, plan, voice="ryan", animation_preset="cursor_click")

    assert seen["animationPreset"] == "cursor_click"
    assert "Open the dashboard" in seen["text"]
    assert seen["voice"] == "ryan"
    assert seen["audio_path"] and seen["audio_path"].endswith("narration.wav")


async def test_render_remotion_job_times_click_ticks(tmp_path, monkeypatch):
    """Clicks on visible screenshot scenes produce mux tick times at ~52% of
    the scene; hidden-region and clickless scenes produce none."""
    import video_remotion_render as vrr
    slug, jid = "s1", "j1"
    job_dir = tmp_path / slug / ".video" / jid
    (job_dir / "screenshots").mkdir(parents=True)

    async def fake_render(job_dir_, **kw):
        return str(job_dir / "video-only.mp4")

    seen = {}

    async def fake_mux(video_in, out_path, audio_path, click_times=None):
        seen["clicks"] = click_times
        return out_path

    async def fake_synth(text, out_path, voice=None):
        return None

    monkeypatch.setattr(vrr, "render_remotion", fake_render)
    monkeypatch.setattr(vrr, "_run_audio_mux", fake_mux)
    monkeypatch.setattr(vrr, "_synthesize_narration", fake_synth)
    plan = {"narration_mode": "off", "scenes": [
        {"kind": "title", "duration_s": 2.0},
        {"kind": "screenshot", "duration_s": 4.0, "screenshot": "screenshot-1.png",
         "click": {"x": 0.4, "y": 0.5, "label": "Go"}},
        {"kind": "screenshot", "duration_s": 4.0, "screenshot": "screenshot-2.png",
         "click": {"x": 0.4, "y": 0.9, "label": "Hidden"}},
        {"kind": "screenshot", "duration_s": 4.0, "screenshot": "screenshot-3.png"},
    ]}
    await vrr.render_remotion_job(str(tmp_path), slug, jid, plan, voice=None)
    assert seen["clicks"] == [2.0 + 4.0 * 0.52]
