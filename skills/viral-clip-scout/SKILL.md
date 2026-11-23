---
name: viral-clip-scout
description: >-
  Analyze a long video, audio file, YouTube URL, or transcript (.srt/.vtt/.json)
  to find only the highest-potential segments for short-form editing (Shorts,
  TikTok, Reels) without forcing a fixed clip count and without rendering video.
  Exports timestamps, scores, hooks, FCPXML, EDL, CSV markers, per-clip SRTs,
  and optional lossless stream-copy commands for CapCut, Premiere Pro, DaVinci
  Resolve, Final Cut Pro, or Remotion. Use when the user wants to scout/find
  viral moments or highlight timestamps from a long video to edit elsewhere.
---

# Viral Clip Scout (Zero-Render, Quality-Gated)

Find **only genuinely high-potential short segments** from a long video or transcript and export ready-to-edit timelines and markers — **no GPU render, no forced clip quota** (0 clips is valid if nothing passes the bar). You (the host agent) act as the analyzer, so **no extra Gemini/OpenAI API key is needed**.

---

## Workflow

Let `<skill_dir>` be the directory containing this `SKILL.md`, and choose a clean working directory `<work_dir>` (e.g., `./clip-scout-out/` or a temp folder outside any clean git repo unless the user wants it saved in the project).

### 1. Prepare Transcript & Signals
Run:
```bash
python "<skill_dir>/scripts/clip_scout.py" prepare "<source>" --out "<work_dir>"
```
Optional flags:
- `--transcript <path>`: use an existing `.srt`, `.vtt`, or Whisper `.json` alongside a raw media file.
- `--lang <code>` / `--whisper-model small`: ASR controls when transcribing audio.
- `--window-mins 45 --overlap-mins 3`: chunking window (use `20` if context is tight).
- `--force-whisper`: ignore auto-captions and transcribe audio directly.

**Missing optional tools handling:**
- `.srt`, `.vtt`, and `.json` transcripts work with **zero third-party packages** (Python stdlib only).
- If the script exits with code `2` complaining `yt-dlp` or `faster-whisper` is missing, show the user the exact `pip install` hint from stderr (or ask for an `.srt`/`.vtt` file) and stop — do not install packages silently without asking.
- If `ffmpeg` is missing, `prepare` skips acoustic `[LOUD]` detection gracefully; warn the user only if they later request `--cut-streams`.

### 2. Read the Rubric & Chunks
Read [`./references/rubric.md`](./references/rubric.md), then read every `<work_dir>/chunk_*.txt`.
Each line uses the compact format `id|MM:SS|[SIGNALS] text`:
- `[LOUD]`: audio RMS energy >= 1.6x median (laughs, shouting, emphasis).
- `[REPLAY:x.xx]`: YouTube *Most Replayed* hotspot >= 0.70.
- `[PAUSE]`: >= 2.0s silence right before this cue (natural topic boundary).

### 3. Phase 1 — Candidate Recall (0..N Moments)
Scan the chunks looking for **15–75 second** self-contained segments (`start_id`..`end_id`) matched to the video's genre profile (`podcast`, `knowledge`, `storytelling`, `review`, `stream` — ask or infer from content):
- **Never force a count.** Do not pad weak filler to hit a target number. Return `[]` if nothing clears the 2-Second Test.
- Fix dangling openings by moving `start_id` slightly earlier to capture the question/premise rather than cutting off the payoff.
- Avoid overlapping/duplicate picks of the same point.

### 4. Phase 2 — Strict Rubric Judge
Score every candidate **independently** across the 4 axes (`0–25` each) using the anti-inflation anchors in [`./references/rubric.md`](./references/rubric.md):
- `hook` (2-second scroll stop)
- `standalone` (zero-context clarity — **cap `<= 14`** if opening on unexplained pronouns/references)
- `value` (density, insight, stakes, or `[LOUD]`/`[REPLAY]` payoff)
- `payoff` (clean landing, no mid-thought cutoffs)

Write `<work_dir>/candidates.json` (in the same language as the video unless asked otherwise):
```json
{
  "candidates": [
    {
      "start_id": 41,
      "end_id": 54,
      "title": "Short descriptive title",
      "hook": "Punchy opening line or text hook (<=10 words)",
      "why": "One concrete sentence on why this segment lands",
      "edit_notes": "Optional tip for the editor (e.g. zoom on chart at 08:25)",
      "scores": {
        "hook": 21,
        "standalone": 19,
        "value": 20,
        "payoff": 18
      }
    }
  ]
}
```

### 5. Finalize & Export
Run:
```bash
python "<skill_dir>/scripts/clip_scout.py" finalize "<work_dir>" --candidates "<work_dir>/candidates.json"
```
Default thresholds are `--min-score 78 --min-axis 15` (adjust only if the user explicitly asks for `84/18` ultra-picky or `70/13` wide-net). Add `--cut-streams` only if the user asked for lossless MP4 cuts (`ffmpeg -c copy`) on a local video.

**Present the result clearly:**
- If `kept_count == 0`, tell the user **no segments cleared the quality bar** (and briefly note the top rejected reason) rather than inventing clips.
- Otherwise, show a concise ranked table (`# | Timecode | Duration | Score (H/S/V/P) | Title & Hook | Why & Edit Notes`) and list the exported file paths under `<work_dir>/exports/`:
  - `timeline.fcpxml` (DaVinci Resolve / Premiere Pro / Final Cut Pro)
  - `markers.edl` & `markers.csv`
  - `highlights.json` (includes `words[]` slice for Remotion / automation)
  - `subtitles/clip_*.srt` (re-timed to `00:00:00,000`)
  - `cut_commands.txt` (lossless `ffmpeg -c copy` commands)

---

## Cross-Harness Portability

This folder follows the open [Agent Skills](https://agentskills.io) standard (pure Markdown + Python 3.10+ stdlib). Copy or symlink `viral-clip-scout/` into any harness's skill directory:

| Agent Harness | Global Path | Project Path |
| :--- | :--- | :--- |
| **Antigravity** | `~/.gemini/config/skills/viral-clip-scout/` | `.agents/skills/viral-clip-scout/` |
| **Codex / OpenCode / `npx skills`** | `~/.agents/skills/viral-clip-scout/` | `.agents/skills/viral-clip-scout/` |
| **Claude Code** | `~/.claude/skills/viral-clip-scout/` | `.claude/skills/viral-clip-scout/` |
| **Cursor** | `~/.cursor/skills/viral-clip-scout/` | `.cursor/skills/viral-clip-scout/` |
| **Gemini CLI** | `~/.gemini/skills/viral-clip-scout/` | `.gemini/skills/viral-clip-scout/` |
