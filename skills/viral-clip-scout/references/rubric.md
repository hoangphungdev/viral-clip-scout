# Viral Clip Scoring Rubric & NLE Export Guide

Evaluate **each candidate moment independently**. Never inflate scores to hit a quota — returning **0 clips** is strictly better than passing filler.

## 1. Four-Axis Rubric (0–25 per axis, max 100)

### A. `hook` — The 2-Second Test (0–25)
Would the first 1–2 spoken lines stop a cold viewer scrolling with zero context?

| Score | Anchor |
| :--- | :--- |
| **0–10** | Slow warm-up, greeting, "so today…", filler throat-clearing, or flat setup. |
| **11–14** | Mildly interesting topic statement, no tension, surprise, or curiosity gap. |
| **15–18** | Clear promise, relatable pain point, or direct provocative statement right away. |
| **19–22** | Immediate pattern interrupt: contrarian claim, sharp conflict, concrete number/stake, or vivid question. |
| **23–25** | Unstoppable opening: instant curiosity loop, visceral emotion (`[LOUD]` / `[REPLAY]`), or jaw-dropping premise in the first sentence. |

### B. `standalone` — Zero-Context Completeness (0–25)
Can a stranger understand the setup, tension, and point without watching the previous 5 minutes?

| Score | Anchor |
| :--- | :--- |
| **0–10** | Starts mid-pronoun ("and that's why *it* broke"), answers an unheard question, or relies heavily on unseen prior slides/stories. |
| **11–14** | **Hard ceiling <= 14** if the opening line references an unexplained "this/that/they" or needs prior context to make sense. |
| **15–18** | Self-contained premise and resolution; minor background detail is easy to infer. |
| **19–22** | Complete mini-arc (setup -> tension -> resolution) that feels deliberately written as a short. |
| **23–25** | Effortlessly crystal-clear standalone story or argument; zero dangling references. |

### C. `value` — Density, Emotion, or Proof (0–25)
Does the middle deliver substance worth sharing, saving, or arguing about in comments?

| Score | Anchor |
| :--- | :--- |
| **0–10** | Generic truism, surface-level rambling, or padded repetition. |
| **11–14** | Useful or mildly entertaining, but predictable to anyone familiar with the niche. |
| **15–18** | Specific actionable tactic, memorable analogy, real numbers/case study, or genuine energy shift. |
| **19–22** | Counter-intuitive insight, sharp debate clash, high stakes, or strong `[LOUD]` / `[REPLAY]` confirmation. |
| **23–25** | Elite save/share material: undeniable proof, rare insider lesson, hilarious/shocking peak, or fierce debate trigger. |

### D. `payoff` — Clean Landing (0–25)
Does the clip close cleanly on its strongest note instead of drifting into the next topic?

| Score | Anchor |
| :--- | :--- |
| **0–10** | Cuts off mid-thought, trails into "yeah anyway…", or starts introducing the next unrelated topic. |
| **11–14** | Acceptable stop, but ending repeats what was already said or weakens the punchline. |
| **15–18** | Clean semantic ending right after the point lands (often right before a `[PAUSE]`). |
| **19–22** | Crisp punchline, quotable mic-drop takeaway, or satisfying reveal right at the end. |
| **23–25** | Re-watch loop trigger: ending reframes the opening hook or lands an unforgettable twist. |

---

## 2. Hard Threshold Calibration

Filtering is enforced deterministically in `clip_scout.py finalize`:
`kept` requires **both** `total_score >= min_score` **and** `min(hook, standalone, value, payoff) >= min_axis`.

| Preset | `--min-score` | `--min-axis` | When to use |
| :--- | :---: | :---: | :--- |
| **Ultra-Picky** | `84` | `18` | Flagship channels; zero tolerance for weak hooks or missing context. |
| **Balanced (Default)** | `78` | `15` | Daily/weekly repurposing; keeps only genuinely strong, standalone moments. |
| **Wide Net** | `70` | `13` | Raw editorial scouting when a human editor wants more rough-cut candidates. |

---

## 3. Genre Profiles (Tune What "Good" Means)

- **`podcast` / interview**: Prioritize heated disagreement, surprising confessions, sharp Q&A exchanges (include the short question cue so `standalone >= 15`), and `[LOUD]` laughter/interruptions.
- **`knowledge` / tutorial**: Prioritize 1 concrete mistake, framework, benchmark number, or "do X instead of Y" takeaway. Flag visual needs in `edit_notes` (e.g., `"needs screen zoom on code"`).
- **`storytelling` / vlog**: Prioritize inciting incident -> escalation -> twist/lesson. Trim slow backstory before the inciting hook.
- **`review` / comparison**: Prioritize decisive verdicts, unexpected flaws/wins, price-to-value shocks, and side-by-side claims.
- **`stream` / gaming / reaction**: Lean heavily on `[LOUD]` and `[REPLAY:x.xx]` clusters; capture 2–4 seconds of build-up before the spike plus the immediate aftermath.

---

## 4. NLE Import Quick Guide (`<work_dir>/exports/`)

- **DaVinci Resolve**:
  - Import `timeline.fcpxml` (*File -> Import -> Timeline...*) for both `Scout Markers` (full video with scored markers) and `Scout Selects` (pre-trimmed timeline), **or** import `markers.edl` / `markers.csv` directly into Timeline Index.
- **Adobe Premiere Pro / Final Cut Pro**:
  - Import `timeline.fcpxml` (or `markers.edl` for Premiere Pro) to jump straight to every kept `start_tc`–`end_tc` with hook & score notes attached.
- **CapCut (Desktop / Web)**:
  - Run `cut_commands.txt` (or pass `--cut-streams` to `finalize`) to get lossless zero-reencode MP4 cuts in `exports/clips/`, then drag the MP4 + matching `exports/subtitles/clip_XX_*.srt` onto the CapCut timeline.
- **Remotion / Code Pipelines**:
  - Read `exports/highlights.json` — each item in `kept[]` includes `rank`, `start`, `end`, `scores`, `title`, `hook`, `why`, `edit_notes`, `srt_file`, and re-timed word timestamps `words[]` (starting at `0.0` relative to clip start) when word-level JSON/Whisper input was used.
