# viral-clip-scout

A portable, zero-render [Agent Skill](https://agentskills.io) that analyzes long-form videos, audio files, YouTube URLs, or transcripts (`.srt`, `.vtt`, `.json`) to surface **only genuinely high-potential short segments** for editing elsewhere — **without forcing a fixed clip count** (returning `0` clips is valid when nothing clears the quality bar) and **without needing a separate LLM API key** (the host agent performs the analysis and scoring).

## Features

- **Zero-render & lightweight**: Never burns subtitles or re-encodes vertical `9:16` video; leaves final editing to DaVinci Resolve, Premiere Pro, Final Cut Pro, CapCut, or Remotion.
- **No forced quota**: 2-phase pipeline (Candidate Recall -> Strict 4-Axis Rubric Judge across `hook`, `standalone`, `value`, `payoff`, `0–25` each). Defaults to `--min-score 78 --min-axis 15` and never pads weak filler.
- **Pure Python 3.10+ stdlib CLI**: `skills/viral-clip-scout/scripts/clip_scout.py` requires zero third-party dependencies for transcript inputs (`.srt`, `.vtt`, Whisper `.json`) and computes 1-second acoustic RMS `[LOUD]` spikes on WAV audio using stdlib `wave` + `array`.
- **NLE-ready exports**:
  - `timeline.fcpxml` (FCPXML v1.10 with both `Scout Markers` and `Scout Selects` timelines)
  - `markers.edl` (CMX 3600 EDL) & `markers.csv`
  - `highlights.json` (scores, reasons, edit notes, and re-timed `words[]` slice for Remotion/automation)
  - `subtitles/clip_XX_*.srt` (re-timed to `00:00:00,000`)
  - `cut_commands.txt` (lossless `ffmpeg -c copy` commands, optionally executed via `--cut-streams`)

## Installation

### Via `skills` CLI (cross-harness)
```bash
npx skills add hoangphungdev/viral-clip-scout
```

### Manual install (any Agent Harness)
Clone this repository and copy `skills/viral-clip-scout/` into your harness's skill folder:

| Agent Harness | Global Path | Project Path |
| :--- | :--- | :--- |
| **Antigravity** | `~/.gemini/config/skills/viral-clip-scout/` | `.agents/skills/viral-clip-scout/` |
| **Codex / OpenCode** | `~/.agents/skills/viral-clip-scout/` | `.agents/skills/viral-clip-scout/` |
| **Claude Code** | `~/.claude/skills/viral-clip-scout/` | `.claude/skills/viral-clip-scout/` |
| **Cursor** | `~/.cursor/skills/viral-clip-scout/` | `.cursor/skills/viral-clip-scout/` |
| **Gemini CLI** | `~/.gemini/skills/viral-clip-scout/` | `.gemini/skills/viral-clip-scout/` |

## Optional Tools (Only for Raw URLs / Uncaptioned Media)

Transcript inputs (`.srt`, `.vtt`, `.json`) work out of the box with Python 3.10+ stdlib only. Install these only when needed:
- `pip install yt-dlp` — analyze YouTube/video URLs, extract *Most Replayed* heatmaps (`[REPLAY]`), and fetch existing captions
- `pip install faster-whisper` — transcribe local video/audio files that have no subtitle track
- `ffmpeg` / `ffprobe` — detect `[LOUD]` audio peaks on compressed media and run `--cut-streams` lossless MP4 cuts

## Self-Test

```bash
python skills/viral-clip-scout/scripts/clip_scout.py selftest
```

## License

MIT
