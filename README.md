# viral-clip-scout

A portable, zero-render [Agent Skills](https://agentskills.io) bundle (`viral-clip-scout` + `viral-short-edit-blueprint`) that works end-to-end without a separate LLM API key or GPU render:

1. **Scout**: Analyze long-form videos, audio files, YouTube URLs, or transcripts (`.srt`, `.vtt`, `.json`) to surface **only genuinely high-potential short segments** (no forced clip count — returning `0` clips is valid when nothing clears the quality bar).
2. **Blueprint**: Turn scouted moments (`highlights.json`, clip SRTs, or cut MP4s) into concrete, retention-engineered vertical `9:16` editing blueprints (`edit_guide.md` shot sheets + guardrail-validated `edit_plan.json` specs) ready for CapCut, Premiere Pro, DaVinci Resolve, Remotion, or FFmpeg.

---

## Included Skills

### 1. `skills/viral-clip-scout/`
Zero-render, quality-gated moment scouting:
- **No forced quota**: 2-phase pipeline (Candidate Recall -> Strict 4-Axis Rubric Judge across `hook`, `standalone`, `value`, `payoff`, `0–25` each). Defaults to `--min-score 78 --min-axis 15 --min-sec 15 --max-sec 180` (supports YouTube Shorts up to 3 minutes so high-scoring multi-beat story arcs aren't artificially chopped at 60s) and never pads weak filler.
- **Pure Python 3.10+ stdlib CLI**: `skills/viral-clip-scout/scripts/clip_scout.py` handles `.srt`, `.vtt`, and Whisper `.json` with zero third-party packages and detects 1-second acoustic RMS `[LOUD]` spikes on WAV audio using stdlib `wave` + `array`.
- **NLE-ready exports**:
  - `timeline.fcpxml` (FCPXML v1.10 with both `Scout Markers` and `Scout Selects` timelines)
  - `markers.edl` (CMX 3600 EDL) & `markers.csv`
  - `highlights.json` (scores, reasons, edit notes, and re-timed `words[]` slice for Remotion/automation)
  - `subtitles/clip_XX_*.srt` (re-timed to `00:00:00,000`)
  - `cut_commands.txt` (lossless `ffmpeg -c copy` commands, optionally executed via `--cut-streams`)

### 2. `skills/viral-short-edit-blueprint/`
Retention-engineered vertical `9:16` edit planning chained directly from `viral-clip-scout`:
- **Pure Python 3.10+ stdlib CLI**: `skills/viral-short-edit-blueprint/scripts/analyze_for_edit.py` inspects `highlights.json` or `.srt` telemetry (`words_per_sec`, `>= 0.36s` dead-air silence cuts, scale beats, caption blocks), optionally samples `1024px` video frames via `ffmpeg`, and validates `edit_plan.json` guardrails.
- **7 Vertical Layout Modes**: `PRO_TALKING_HEAD`, `TRACK`, `SPLIT`, `ALTERNATE`, `SCREENCAST`, `INSET`, and `WIDE` (plus bottom burned-subtitle pre-crop detection).
- **Hook, Pacing & Effects Guardrails**: `0–3s` clip-grounded hook overlays (7 styles, face-safe & caption-safe placement), dead-air tightening with alternating scale beats (`1.00 / 1.12 / 1.05 / 1.16`), duration-scaled pattern-interrupt budgets (`<=75s`: max `12` edits / `2` flashes / `5` titles; scales up to `30 / 4 / 11` for `75–180s` Shorts, zoom `<= 1.15x`, no overlapping zooms, no post-zoom on burned captions).
- **Captions, Safe Zones & Audio**: 7 dynamic caption presets (`default`, `hormozi`, `pill`, `lime`, `oneword`, `cine`, `clean`), universal `900×1160` safe box (`1080×1920` TikTok / Reels / Shorts), `-14` to `-15 LUFS` voice + optional music bed (`-3 dB` ducking, omit if using pure dialogue + micro-SFX) + micro-SFX sync, and NLE recipes for CapCut, Premiere Pro, DaVinci Resolve, Remotion, and FFmpeg.

---

## Installation

### Via `skills` CLI (cross-harness, installs both skills in one command)
`npx skills` automatically discovers every skill folder under `skills/`:
```bash
npx skills add hoangphungdev/viral-clip-scout
```

### Manual install (any Agent Harness)
Clone this repository and copy **both** folders under `skills/*` (`viral-clip-scout/` and `viral-short-edit-blueprint/`) into your harness's skill directory:

| Agent Harness | Global Path | Project Path |
| :--- | :--- | :--- |
| **Antigravity** | `~/.gemini/config/skills/` | `.agents/skills/` |
| **Codex / OpenCode** | `~/.agents/skills/` | `.agents/skills/` |
| **Claude Code** | `~/.claude/skills/` | `.claude/skills/` |
| **Cursor** | `~/.cursor/skills/` | `.cursor/skills/` |
| **Gemini CLI** | `~/.gemini/skills/` | `.gemini/skills/` |

---

## Optional Tools (Only for Raw URLs / Uncaptioned Media / Frame Sampling)

Transcript inputs (`.srt`, `.vtt`, `.json`) and edit blueprint validation work out of the box with Python 3.10+ stdlib only. Install these only when needed:
- `pip install yt-dlp` — analyze YouTube/video URLs, extract *Most Replayed* heatmaps (`[REPLAY]`), and fetch existing captions
- `pip install faster-whisper` — transcribe local video/audio files that have no subtitle track
- `ffmpeg` / `ffprobe` — detect `[LOUD]` audio peaks on compressed media, run `--cut-streams` lossless MP4 cuts, and extract `1024px` frame samples for visual layout inspection

---

## Self-Test

```bash
python skills/viral-clip-scout/scripts/clip_scout.py selftest
python skills/viral-short-edit-blueprint/scripts/analyze_for_edit.py selftest
```

## License

MIT
