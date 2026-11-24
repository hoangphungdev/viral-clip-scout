# Retention Pacing, Hooks, Effects & Sound Design

Synthesized from `mutonby/openshorts` (`pro_mode.py`, `punch_in.py`, `editor.py`, `edit_builder.py`, `hooks.py`, `hook_placement.py`, `hook_grounding.py`), `FujiwaraChoki/supoclip`, and retention-editing benchmarks.

---

## 1. Macro Retention Structure

Engineer every short as a tight psychological loop (target **15–75s**, sweet spot **25–50s**):

| Segment | Timing | Goal & Execution |
| :--- | :--- | :--- |
| **Hook** | `0:00 – 0:03` | Speech starts at **frame 1–4 (`0.00–0.13s`)**. Zero intro bumper, zero greeting (`"So today..."`). Combine **visual motion + grounded hook text + spoken curiosity/conflict**. |
| **Setup / Agitation** | `0:03 – 0:15` | Immediately validate the hook with concrete numbers, stakes, or tension. Drop a **4-frame white flash** or hard zoom/angle switch right after the hook (~`2.5–3.5s`). |
| **Escalation & Interrupts** | `0:15 – End-3s` | Deliver fast-paced substance (`~3.5–4.1 words/s`). Break visual monotony every **1.6–4.5s** via scale shifts, B-roll cutaways, screen callouts, or keyword titles. |
| **Payoff & Loop** | Final `1–3s` | Land the twist/takeaway cleanly; **hard cut immediately on the final word** (no logo, no `"follow for part 2"` filler) or align the closing phrase semantically/rhythmically with `0:00` for an invisible rewatch loop. |

---

## 2. Viral Hook Engineering (0–3s)

### A. Hook Copy Rules & Grounding
- **Max length**: `<= 10` words (`<= 12` hard ceiling), readable in `< 1.5s`.
- **Clip-Grounded (Critical)**: Never write a generic title summarizing the whole 1-hour source video. Ground the hook to **what is literally shown or said in this clip** (especially on `SCREENCAST`, `INSET`, and `WIDE` clips).
- **4 High-Performing Hook Archetypes**:
  1. **Curiosity Gap**: *"The 1 bug silently burning 80% of our budget"*
  2. **Contrarian Frame**: *"Stop cutting every silence—here's why it kills retention"*
  3. **Specific Outcome**: *"How we dropped render time from 15s to 2.2s"*
  4. **Negative Constraint**: *"Never zoom after burning captions—do this instead"*

### B. 7 Hook Visual Styles (`hooks.py`)
| Style ID | Visual Treatment | Default Font & Scale (`% of width`) | Best Use |
| :--- | :--- | :--- | :--- |
| **`pill`** *(default)* | Per-line white rounded pill boxes (`#FFFFFF`, alpha 250), black bold text | `Montserrat ExtraBold` (`0.064`) | Native TikTok/Reels look; cleanest multi-line readability |
| **`classic`** | Single white card (`rgba(255,255,255,0.94)`), black text, soft drop shadow | `Noto Serif Bold` (`0.050`) | Editorial, storytelling, commentary |
| **`dark`** | Dark card (`rgba(18,18,20,0.92)`), white text, drop shadow | `Noto Serif Bold` / Sans (`0.050–0.064`) | Bright backgrounds, tech/finance, serious tone |
| **`yellow`** | High-contrast yellow card (`#FFD600`), black text, shadow | `Montserrat` / `Anton` (`0.064–0.080`) | Urgent tips, listicles, street/podcast clips |
| **`red`** | Breaking-news red card (`#DC2626`), white text, shadow | `Anton` / `Montserrat` (`0.064–0.080`) | Warnings, hot takes, drama, gaming/stream moments |
| **`outline`** | No box; white text with `8px` black stroke | `Anton` / `Montserrat` (`0.064–0.080`) | Minimal overlay over busy footage |
| **`outline_yellow`** | No box; yellow text (`#FFD600`) with `8px` black stroke | `Anton` / `Montserrat` (`0.064–0.080`) | Punchy MrBeast-style callouts |

- **Animation & Timing**: Entrance `spring` (mass `0.8`, stiffness `200`, damping `15`, ~`0.5–0.65s`) or `slide-up`, hold **`3.0–5.0s`**, `15-frame` (`0.5s`) fade out.

### C. Face-Safe & Caption-Safe Hook Placement (`hook_placement.py`)
Never hardcode hooks at `20%` Y blindly — `20%` hits a `TRACK` speaker's forehead and a top `SPLIT` speaker's face:
- **Valid vertical range**: **`6%` (`TOP_MARGIN = 0.06`) to `80%` (`BOTTOM_UI = 0.80`)**.
- **Head-box buffer**: Grow detected face boxes (`0.6 × face_height` upward for forehead/hair, `0.2h` downward, `0.15w` sides) and keep the hook box completely off the head box.
- **Caption-band exclusions**:
  - Avoid **`0.70–0.88`** on standard layouts (`BOTTOM_CAPTIONS`).
  - Avoid **`0.42–0.58`** on `SPLIT` layouts (`SEAM_CAPTIONS`).
- **On `WIDE` layouts**: Prefer placing the hook above or below the active 16:9 content band in the blurred margin.
- **Shrink fallback**: If full scale (`1.0`) clips a face or caption band, scale down cleanly (`1.0 -> 0.85 -> 0.72`) before allowing overlap.

---

## 3. Dead-Air Tightening & Shot Cadence (`pro_mode.py`)

For `PRO_TALKING_HEAD` (single speaker to camera):
- **Dead-air cut threshold**: Cut silences **`>= 0.36s`** (`MIN_SILENCE`).
- **Word breathing room**: Leave **`0.13s`** after the outgoing word (`KEEP_BEFORE`) and **`0.10s`** before the incoming word (`KEEP_AFTER`) so cuts never clip consonants or sound robotic.
- **Minimum kept span**: Never leave micro-fragments shorter than **`0.30s`** (`MIN_KEEP`), and never compress a clip below **`5.0s`** total.
- **Target cadence**: **`3.5–4.1 words/s`** (slow `< 3.0` needs tighter cuts/speed-up; `> 4.2` needs fewer jump cuts).
- **Scale alternation per cut**: Cycle `1.00x -> 1.12x -> 1.05x -> 1.16x` across consecutive cuts (`MIN_BEAT = 1.6s`, `MAX_BEAT = 4.5s`) so every cut reads as a deliberate camera angle change.
- **Creeping motion**: Add a subtle **`0.008/s` (`0.8%/s`) slow push-in** inside shots (capped at `+5%`) so no frame ever looks frozen (`>= 12 frames` static feels unedited).

---

## 4. Pattern Interrupts, Effects & Guardrails (`punch_in.py`, `edit_builder.py`)

### Order-of-Operations Rule (CRITICAL)
**All reframing, scale beats, and zoom effects MUST run BEFORE burning captions or hook overlays.** If a source clip already has burned-in captions/hooks (`has_burned_captions = true`), **ALL zoom effects (`zoom_in`, `punch_in`, `zoom_pulse`) are FORBIDDEN** — only `color_pop`, `bw_moment`, `flash`, `vignette`, `broll_cutaway`, and `screen_callout` are allowed.

### Effect Budget & Limits
- **Frequency**: **2–6 edits per 30 seconds** (`MAX_EDITS = 12` per clip). A random effect is worse than none.
- **Never overlap two zoom-type edits** (`zoom_in`, `punch_in`, `zoom_pulse`).
- **Peak zoom cap**: Never exceed **`+15%` (`strength <= 0.15`, `1.15x`)** on face-framed shots; **`1.12x` (`0.12`)** is the sweet spot.

| Effect / Interrupt | Duration | Strength / Params | When & How to Use |
| :--- | :--- | :--- | :--- |
| **`punch_in`** | `0.8–5.0s` (or `0.25s` ease-in + `1.30s` hold + `0.55s` ease-out) | `0.06–0.15` (sweet spot `0.12`) | Instant tighter framing on punchlines, confessions, `"listen to this"` moments. Space audio-beat punches `>= 18s` apart (`<= 3/min`) so it feels intentional, not twitchy. |
| **`zoom_in`** | `1.5–6.0s` (max `8.0s`) | `0.06–0.15` | Smooth linear/smoothstep push across a rising buildup or tense explanation (`ZOOM_CENTER_Y = 0.45`). |
| **`zoom_pulse`** | `0.4–1.2s` | `0.04–0.10` | Quick symmetric in-and-out beat hit on a single shocking word or number. |
| **`color_pop`** | `1.0–4.0s` | `0.2–1.0` (`contrast = 1+0.15s`, `sat = 1+0.6s`) | Boost contrast & vibrancy on product reveals, energetic highs, or B-roll highlights. |
| **`bw_moment`** | `0.8–3.5s` | `saturation = 0` | Desaturate for ironic quotes, mistakes, flashbacks, or serious counterpoint. |
| **`flash`** | `0.15s` (4 frames @ 30fps) | `brightness +0.35` | Brief white flash at post-hook transition or major reveal. **Hard max: `2` per clip.** |
| **`vignette`** | `1.5–6.0s` | `angle = PI/4.5` | Subtle edge darkening for intimate confession or story climax. |
| **`broll_cutaway`** | `1.5–3.5s` | Full-frame or top split | Visual proof (stock clip, tweet/article screenshot, chart, product shot) placed `0–3 frames` before its spoken keyword. Speed up slow B-roll `120–150%` if needed. |
| **`screen_callout`** | `1.5–4.0s` | `1.2x–1.5x` crop + highlight box/arrow | Mandatory on `knowledge`/`review` clips showing code, spreadsheets, or dashboards — zoom into the exact active region. |
| **`keyword_title`** | `1.45s` (`TITLE_SECONDS`) | `<= 14 chars`, `>= 2.5s` apart, **max `5`** | Bold top-zone anchor phrases (`Archivo Black`, `#FF5A1F` or brand accent) over face headroom ONLY — **never during `[0, hook.duration_sec]`** and never over screencast content. |

---

## 5. Genre Tuning Matrix

| Genre | Layout Default | Pacing & Cuts | Visual Interrupt Priority | Caption Preset |
| :--- | :--- | :--- | :--- | :--- |
| **`podcast`** | `SPLIT` / `ALTERNATE` / `TRACK` | Cut pauses `>=0.36s` on solo stretches; switch camera on speaker change | `punch_in` on clash/confession, reaction cutaway, `keyword_title` on hot take | `default` or `hormozi` (`seam` on `SPLIT`) |
| **`knowledge`** | `PRO_TALKING_HEAD` + `SCREENCAST` | Aggressive dead-air trim (`~3.7–4.0 wps`); scale beats every `2–3s` | `screen_callout` zooms, `broll_cutaway` diagrams/tweets, `keyword_title` steps | `hormozi` or `pill` |
| **`storytelling`** | `PRO_TALKING_HEAD` / `TRACK` | Preserve `0.2–0.3s` dramatic pauses; slow `zoom_in` on suspense | `vignette`, `bw_moment` on setback, `broll_cutaway`, post-hook `flash` | `cine` or `clean` |
| **`review`** | `INSET` / `SCREENCAST` / `TRACK` | Snappy verdict cuts; speed-ramp B-roll `125%` | `color_pop` on product hero shot, `screen_callout` specs/price | `pill` or `lime` |
| **`stream`** | `INSET` / `WIDE` | Keep `2–4s` build-up before `[LOUD]`/`[REPLAY]` peak; fast reaction cut | `zoom_pulse` on impact, `flash` (max 2), `red` hook style | `oneword` or `default` |

---

## 6. Audio Mix & Sound Design Blueprint

1. **Voice / Dialogue (Layer 1)**: De-noise + light EQ presence boost (`+2–3 dB` around `3–5 kHz`) + compression (`3:1`–`4:1`). Normalize integrated loudness to **`-14` to `-15 LUFS`** with **`-1.2 dBTP`** true peak.
2. **Music Bed (Layer 2)**: Instrumental track matching clip energy at **`-20` to `-25 dB`** relative to voice, ducked **`-3 dB`** whenever voice is active. **Drop music completely (`music_dropouts`)** for `0.5–2.0s` right before a major twist or mic-drop punchline.
3. **Micro-SFX (Layer 3)**: Land every SFX **`0–3 frames` (`0.00–0.10s`) BEFORE** the visual cut/pop:
   - `whoosh`: Hook exit flash, B-roll slide-in, layout switch.
   - `pop` / `click`: Hook pill entrance, `keyword_title`, highlight box/arrow.
   - `riser` + `sub_hit`: Rising tension before key metric (`riser`), landing right on the reveal (`sub_hit`).
   - `ding`: Clean checklist/framework number (`"Step 1..."`).
