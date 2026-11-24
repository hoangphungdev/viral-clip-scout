---
name: viral-short-edit-blueprint
description: >-
  Generate concrete, retention-engineered vertical 9:16 viral short editing
  blueprints (both human-readable shot sheets and validated edit_plan.json
  specs) from viral-clip-scout outputs (highlights.json, clip SRTs, or cut
  MP4s) or raw short timestamps. Synthesizes layout reframing, 0-3s grounded
  hook overlays, dead-air jump cuts, pattern-interrupt effects, dynamic
  captions, platform safe zones, audio/SFX design, and NLE execution steps for
  CapCut, Premiere Pro, DaVinci Resolve, Remotion, and FFmpeg. Use whenever
  the user asks how to edit scouted clips or turn highlights into viral shorts.
---

# Viral Short Edit Blueprint

Turn high-potential highlight segments from `viral-clip-scout` into **frame-accurate, retention-engineered 9:16 edit blueprints** (`edit_plan.json` + `edit_guide.md`) ready for CapCut, Premiere Pro, DaVinci Resolve, Remotion, or FFmpeg. Distilled from `mutonby/openshorts`, `JeremySNR/cutawan`, `FujiwaraChoki/supoclip`, and `aristache-labs/ViralCutter`.

---

## Handoff from `viral-clip-scout`

- **Inputs**: `<work_dir>/exports/highlights.json` + `<work_dir>/exports/subtitles/clip_XX_*.srt` (or a standalone `.srt` / clip MP4).
- **Outputs**: `<work_dir>/edit_blueprints/clip_XX_<slug>_edit_plan.json` and `clip_XX_<slug>_edit_guide.md`.

---

## Workflow

Let `<skill_dir>` be the directory containing this `SKILL.md`. Choose `<out_dir>` (default: `<work_dir>/edit_blueprints`).

### 1. Inspect Clip Telemetry & Sample Frames
Run:
```bash
python "<skill_dir>/scripts/analyze_for_edit.py" inspect "<highlights.json_or_srt>" --out "<out_dir>"
```
Options:
- `--clip-rank N`: inspect a single ranked clip from `highlights.json`.
- `--video "<clip_or_source.mp4>" --sample-frames`: if a local video and `ffmpeg` exist, extract 8 evenly spaced 1024px stills into `<out_dir>/frames/` for visual layout classification and hook grounding.
- `--max-silence 0.36`: threshold (seconds) for flagging dead-air jump cuts.

Read `<out_dir>/edit_telemetry.json` and inspect any extracted stills with `read_file`.

### 2. Visual & Layout Classification
Read [`./references/layouts-and-reframing.md`](./references/layouts-and-reframing.md) and choose one primary `layout_mode` (or per-scene `layout_ranges`) via **closed-choice inspection**:
- `PRO_TALKING_HEAD` — single speaker to camera (`>=90%` tracked face, ideal for dead-air tightening + scale jumps + background dim).
- `TRACK` — single moving subject / speaker without aggressive pro-mode re-cutting.
- `SPLIT` — two speakers visible side-by-side (`>=2.5s`) stacked 50/50 vertically with captions on the seam.
- `ALTERNATE` — active-speaker hard cuts between close-ups/angles with hysteresis to avoid ping-pong flicker.
- `SCREENCAST` — presenter beside screen content (`>=30%` reading width) stacked over face-framed presenter.
- `INSET` — OBS/Loom stream VOD with small off-center static webcam enlarged below full-width screen.
- `WIDE` — gameplay/slides/charts zoomed cleanly (`~1.3x`, capped `1.4x`, panned to motion) instead of tiny illegible letterboxing.

Also check if the source footage **already has burned-in subtitles** in the bottom 25% (`>=40%` of frames): if so, record `source_subtitle_band_crop` so the bottom band is cropped before reframing.

### 3. Design the Retention Edit Blueprint
Load [`./references/retention-pacing-and-effects.md`](./references/retention-pacing-and-effects.md) and [`./references/captions-safezones-and-nle.md`](./references/captions-safezones-and-nle.md), then design each layer:

1. **0–3s Viral Hook**:
   - Trim any intro fluff so speech starts at `0.00–0.13s` (frame 1–4).
   - **Ground the hook** to what happens/appears in *this clip* (inspect frames on screen-heavy clips). Use one of the 4 hook archetypes (`<=10` words).
   - Pick a hook style (`pill`, `classic`, `dark`, `yellow`, `red`, `outline`, `outline_yellow`) and place `y_pct` inside `[0.06, 0.80]`, strictly clear of the speaker's head box and the active caption band.
2. **Dead-Air & Jump-Cut Tightening**:
   - On `PRO_TALKING_HEAD`, cut gaps `>= 0.36s` keeping `0.13s` tail / `0.10s` lead (`min_keep 0.30s`), alternating scale jumps (`1.00 -> 1.12 -> 1.05 -> 1.16`) every `1.6–4.5s` with `0.8%/s` slow push-in (max `+5%`) and background dim (`0.24` gain). Target `3.5–4.1 words/s`.
3. **Pattern Interrupts, Effects & B-Roll**:
   - Budget **2–6 edits per 30s** (hard max `12` per clip). Never stack random effects.
   - Allowed types: `zoom_in`, `punch_in`, `zoom_pulse`, `color_pop`, `bw_moment`, `flash` (max `2`), `vignette`, `broll_cutaway`, `screen_callout`, `keyword_title` (max `5`, `1.45s`, `>=2.5s` apart, `<=14` chars, never during `[0, hook.duration_sec]`).
   - **Critical rule**: Never overlap zoom-type edits; keep zoom `strength <= 0.15`; never use zooms if `has_burned_captions` is `true` (zooms crop baked text).
4. **Dynamic Captions & Safe Zones**:
   - Choose a preset (`default`, `hormozi`, `pill`, `lime`, `oneword`, `cine`, `clean`) with `1–3` words (`9–18` chars, `<=1.4s`) per block and highlight power words.
   - Place on `seam` (`47–54%` Y) during `SPLIT` stretches and inside the `900×1160` universal safe box (`>=15%` bottom clearance; higher if targeting Instagram Reels).
5. **Audio & Sound Design**:
   - Voice `-14` to `-15 LUFS` (`-1.2 dBTP`); music bed `-20` to `-25 dB` with `-3 dB` speech ducking and strategic drop-outs before punchlines; micro-SFX (`whoosh`, `pop`, `click`, `riser`, `sub_hit`, `ding`) landed `0–3 frames` (`0.00–0.10s`) ahead of the beat.
6. **Payoff & Loop Close**:
   - Hard-cut right after the final punchline word (no outro cards/generic CTAs) or bridge the closing phrase back into frame 1 for a seamless loop.

### 4. Write Blueprint Artifacts
For each target clip, write:
1. `<out_dir>/clip_XX_<slug>_edit_plan.json` matching this schema:
```json
{
  "clip_id": "clip_01",
  "title": "Descriptive clip title",
  "genre": "podcast",
  "duration_sec": 34.5,
  "has_burned_captions": false,
  "source_subtitle_band_crop": null,
  "layout_mode": "PRO_TALKING_HEAD",
  "layout_ranges": [{"start": 0.0, "end": 34.5, "layout": "PRO_TALKING_HEAD", "notes": "Single speaker"}],
  "hook": {
    "text": "Stop doing this before every edit",
    "style": "pill",
    "font": "montserrat",
    "duration_sec": 3.5,
    "y_pct": 0.14,
    "entrance": "spring",
    "grounding_note": "Matches speaker gesture and headline claim"
  },
  "silence_cuts": [{"start": 12.40, "end": 13.25, "keep_tail": 0.13, "keep_lead": 0.10, "reason": "dead_air"}],
  "scale_beats": [{"time": 0.0, "scale": 1.0}, {"time": 3.2, "scale": 1.12}],
  "effects": [
    {"type": "flash", "start": 3.5, "end": 3.65, "strength": 0.35, "reason": "Post-hook transition"},
    {"type": "punch_in", "start": 8.4, "end": 10.5, "strength": 0.12, "reason": "Key metric reveal"},
    {"type": "keyword_title", "start": 14.0, "end": 15.45, "text": "3X RETENTION", "reason": "Anchor takeaway"}
  ],
  "captions": {
    "preset": "hormozi",
    "position": "bottom",
    "max_chars": 9,
    "max_duration": 1.4,
    "safe_zone": "universal_900x1160",
    "color_pop_words": ["STOP", "3X", "RETENTION"]
  },
  "audio": {
    "voice_lufs_target": -14.0,
    "true_peak_dbtp": -1.2,
    "music_bed_db": -22.0,
    "duck_db": -3.0,
    "music_dropouts": [{"start": 29.8, "end": 32.0, "reason": "Final punchline emphasis"}],
    "sfx": [{"time": 3.43, "sfx_type": "whoosh", "sync_target": "Post-hook flash"}]
  },
  "ending": {"type": "hard_cut", "cut_at_sec": 34.2, "loop_bridge_note": ""}
}
```
2. `<out_dir>/clip_XX_<slug>_edit_guide.md`: Editor-ready shot sheet in the user's language containing:
   - Clip header (Score from `viral-clip-scout`, Layout Mode, Duration Before -> After Silence Cuts, Target Platforms).
   - Hook & Caption Spec (exact text, style, font, hex colors, pixel/percentage coordinates, safe zone).
   - Second-by-second Timeline Shot Table (`Time | Beat / Spoken Cue | Visual & Framing | Effects / B-Roll / Titles | Captions Highlight | Audio & SFX`).
   - NLE Quick Execution Recipe tailored to the user's editor (CapCut, Premiere Pro, DaVinci Resolve, or Remotion/FFmpeg).

### 5. Validate Guardrails
Run:
```bash
python "<skill_dir>/scripts/analyze_for_edit.py" validate "<out_dir>/clip_XX_<slug>_edit_plan.json"
```
Fix any reported `errors` (overlapping zooms, excessive zoom strength, >2 flashes, >5 titles, title colliding with hook window, hook colliding with caption band, or post-cut duration < 5s) before presenting.

### 6. Present & Optional Handoff
Present a concise summary per clip (layout, hook, caption preset, top visual beats, audio/SFX cues, and output file links). Mention NLE handoff options: manual edit in CapCut/Resolve, live automation in Premiere Pro (`edit-premiere-project` MCP), or programmatic render in Remotion (`remotion-video-editor` + `video-direction-qa`).
