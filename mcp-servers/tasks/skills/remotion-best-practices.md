# Video craft & style guide

This steers how every AI-authored video LOOKS and FEELS. It is injected into
both the plan-authoring prompt and the Remotion codegen prompt. Edit freely on
the website (Workspace > Skills > "Remotion Best Practices"); changes apply to
the next render. Correctness rules (allowed imports, determinism, duration
caps) live in a locked contract outside this skill and always apply.

Canonical copy: mcp-servers/tasks/skills/remotion-best-practices.md
Install/update: scripts/install_video_skill.py (writes the skill DB row).

## Look (Apple-grade restraint)

- One deliberate palette per video: a deep, subtly graded background (never
  flat, never busy), 1-2 text colors, ONE accent. High contrast, cohesive mood.
- Type is the design: one bold display size (110-160px, letter-spacing -0.02em
  to -0.04em) plus one supporting size (26-40px). Two weights maximum. Clean
  modern sans (Inter/system) by default.
- Depth comes from hairlines and soft large shadows, not from borders and
  boxes. Prefer a 16px radius card language when framing screenshots.
- Generous margins. Off-center, asymmetric layouts beat centered stacks.

## Cursor click-through (REQUIRED on screenshot scenes with a click target)

The signature of these videos is a cursor that uses the site like a person:
- Draw ONE cursor: a simple white pointer with a soft drop shadow, about
  22-28px tall. It must persist across the scene, never teleport.
- GLIDE: move the cursor to the click point along a slightly curved path with
  ease-in-out over 0.6-1.0s. Overshoot by 2-3px and settle.
- PRESS: on arrival, scale the cursor to 0.9 for ~3 frames, then back, and
  emit one expanding ripple ring (24 to 64px, fading out over ~0.4s) centered
  on the click point.
- REDIRECT: the click CAUSES the page change. Within 5-8 frames of the press,
  transition to the next scene so cause and effect read clearly.
- Click coordinates come from the plan's click object (x and y are fractions
  of the screenshot). Never invent targets; scenes without a click object get
  no cursor.

## Page transitions (REQUIRED between scenes)

Pick per cut, in service of the story, and vary them:
- PUSH: the old page slides out (left or up) while the new one slides in,
  both eased, 0.4-0.6s, with the incoming page starting at 98% scale and
  settling to 100%.
- ZOOM-THROUGH: zoom into the clicked region 1.0 to 1.15, crossfade at the
  peak, land on the new page pulling back to 1.0.
- CROSSFADE with drift for calm or cinematic moods, 0.5-0.8s.
- Title and outro cards enter with staggered text reveals, never hard cuts.
- Never use the same transition three times in a row.

## Motion

- Ease-OUT entrances that arrive and settle; STAGGER reveals a few frames
  apart, never simultaneous.
- HOLD each beat long enough to read (2-3.5s). Keep a subtle continuous drift
  or 1-2% scale so no frame is dead static.
- Springs for crisp pops; long eased fades for cinematic moods. Vary motion
  per scene; never reuse one move everywhere.

## Structure

- Clear arc: HOOK title beat (what it is, why care), then 2-4 screenshot
  beats on the strongest features, then a short OUTRO with a call to action.
- Use only the best screenshots; skip weak or repetitive ones.
- Headlines are benefit-led, 8 words or fewer, never reading the UI verbatim.
- Add ONE distinctive element per video: an underline that draws on, a
  count-up number, a progress bar, or a simple device frame.

## Audio and narration

- Narration is conversational, one idea per scene, speakable at about 2.5
  words per second within the scene's duration.
- The user chooses the voice from the voice library; never assume a voice.
- If the plan sets narration_mode to "off", the silence is deliberate (music
  bed or no audio at all). Do not derive or add narration text.
- Music stays under the voice, a bed and not a track. Quiet confidence beats
  loud energy.

## Pacing

- 2.5-5s per scene, varied lengths, 20-35s total ideal, hard cap 40s.
- Avoid runs of identical durations; rhythm sells the edit.
