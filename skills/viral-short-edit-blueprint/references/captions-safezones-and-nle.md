# Dynamic Captions, Platform Safe Zones & NLE Execution

Synthesized from `mutonby/openshorts` (`subtitles.py`, `hook_placement.py`), 2025–2026 platform UI safe-zone specs (`1080×1920`), and multi-NLE workflows (`CapCut`, `Premiere Pro`, `DaVinci Resolve`, `Remotion`, `FFmpeg`).

---

## 1. The 7 Caption Presets (`subtitles.py`)

83–85% of mobile viewers start watching on mute. Always group words into **`1–3` words (`9–18` chars, max `1.4s`)** per block, merge broken continuation tokens (e.g. `"YouTube"` + `"-Kanal."`), and emphasize power words:

| Preset ID | Font & Size | Base / Active Hex | Stroke / Shadow | Case & Reveal | `max_chars` | Best Fit |
| :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| **`default`** | `Anton`, `40` | `#FFFFFF` / `#FFE500` | `2px` `#000000` border | Uppercase, `pop` | `18` | Universal safe choice; `#FFE500` rarely collides with footage |
| **`hormozi`** | `Montserrat ExtraBold`, `44` | `#FFFFFF` / `#FFE500` | `4px` border + `2px` shadow | Uppercase, `reveal=true`, `pop` | `9` | High-energy talking-head, `knowledge`, business/podcast |
| **`pill`** | `Montserrat ExtraBold`, `44` | `#FFFFFF` / `#7C3AED` box | `3px` border, active solid pill | Uppercase, `highlight` | `9` | CapCut/Submagic style, tech, SaaS, reviews |
| **`lime`** | `Montserrat ExtraBold`, `44` | `#FFFFFF` / `#A3FF12` box | `3px` border, active solid pill | Uppercase, `highlight` | `9` | Youthful, gaming, fitness, creator tips |
| **`oneword`** | `Anton`, `70` | `#FFFFFF` / `#FFFFFF` | `5px` `#000000` border | Uppercase, `pop` | `1` *(1 word/block)* | Rapid-fire `[LOUD]` streams, intense hooks |
| **`cine`** | `Montserrat ExtraBold`, `36` | `#FFFFFF` (`0.8` opacity) / `#FF5A1F` | `0px` border, `2px` shadow | Sentence case | `14` | `PRO_TALKING_HEAD`, cinematic storytelling |
| **`clean`** | `Montserrat ExtraBold`, `34` | `#FFFFFF` (`0.7` opacity) / `#FFFFFF` | `0px` border, `2px` shadow | Sentence case | `12` | Calm documentaries, thoughtful essays |

- **Opacity note**: Keep `base_opacity = 1.0` over bright scenes; use `0.7–0.8` dimming only on dark/graded `PRO_TALKING_HEAD` or `storytelling` edits.

---

## 2. Platform Safe Zones (`1080×1920` Canvas)

### Universal Cross-Platform Safe Box (Publish Once Everywhere)
Keep all faces, hooks, callouts, and subtitles inside the **~`900×1160 px` centered corridor**:
- **Top margin**: Keep clear of top **`250–380 px`** (`~13–20%` Y; absolute minimum `6%` / `115 px` only if TikTok-only).
- **Bottom margin**: Keep clear of bottom **`350–484 px`** (`~18–25%` Y). OpenShorts enforces `SAFE_MARGIN_V = 43` in `PlayResY=288` (`~15%` bottom margin, spanning `~75–83%` Y) as a baseline, and recommends raising captions toward **`70–78%` Y** when cross-posting to Instagram Reels.
- **Left margin**: Keep clear of outer **`60–90 px`**.
- **Right margin**: Keep clear of outer **`140–192 px`** (Like / Comment / Share / Remix stack).

### Platform-Specific Breakdown (`1080×1920`)
| Platform | Top Clear | Bottom Clear | Left Clear | Right Clear | Watch-Out |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TikTok** | `~200 px` | `320–528 px` | `~60 px` | `120–185 px` | Long descriptions expand upward into bottom-left |
| **Instagram Reels** | `~269 px` (`14%`) | `~672 px` (`35%` worst case) | `~65 px` | `~65–140 px` | Profile grid crops 9:16 to **4:5 / 1:1 center** — keep subject & hook centered |
| **YouTube Shorts** | `~288 px` (`15%`) | `380–672 px` | `~48 px` | `~192 px` | Heavy right interaction bar + bottom subscribe/audio pill |

### Caption Placement Rules
- **Standard layouts (`TRACK`, `PRO_TALKING_HEAD`, `ALTERNATE`, `SCREENCAST`, `INSET`, `WIDE`)**: Place bottom captions around **`72–82%` Y** (`MarginV >= 43/288`, never lower than `85%` Y).
- **`SPLIT` layout**: Always place captions on the **center horizontal seam (`47–54%` Y, center-aligned `\an5`)** so they never cover Top Speaker's chin or Bottom Speaker's forehead.

---

## 3. NLE Translation & Handoff Recipes

### A. CapCut (Desktop / Web)
1. **Import**: Drag lossless cut MP4 (`exports/clips/clip_XX_*.mp4`) + matching SRT (`exports/subtitles/clip_XX_*.srt`).
2. **Canvas & Layout**: Set Ratio **`9:16`** (`1080×1920`, `30/60fps`). Enable **Auto Reframe** (or split two video tracks stacked 50/50 for `SPLIT`, screen top + webcam bottom for `INSET`).
3. **Track Stack (Bottom -> Top)**:
   - `V1`: Main A-Roll (`PRO_TALKING_HEAD` silence cuts + alternating `100% / 112% / 105% / 116%` scale keyframes with `Ease Out`).
   - `V2`: B-Roll cutaways & `screen_callout` zooms (`0–3f` before keyword).
   - `V3`: `keyword_title` cards (max 5, `1.45s` duration, top headroom).
   - `V4`: `0–3.5s` Hook Pill card (placed in face-safe slot, pop-in animation).
   - `V5`: Captions (apply **Word-by-Word Pop / Hormozi** style, bold Sans, highlight `#FFE500`, position inside safe zone).
4. **Audio**: Enable **Loudness Normalization (`-14 LUFS`)** + **Voice Isolation** on A1; music bed on A2 at `-22 dB` with keyframes ducking `-3 dB` and muting on `music_dropouts`; SFX on A3 aligned `2 frames` early.

### B. Adobe Premiere Pro (Manual or `edit-premiere-project` MCP)
1. **Import**: Import `exports/timeline.fcpxml` or `markers.edl` from `viral-clip-scout`.
2. **Sequence**: `1080×1920`, `29.97/30fps` (or match source fps). Run **Auto Reframe Sequence** for `TRACK`, or crop/position layers for `SPLIT`/`INSET`.
3. **Motion & Effects**: Keyframe `Transform -> Scale` (`1.00 -> 1.12`) with **Bezier / Ease In-Out**; add Lumetri Color (`contrast +15`, `saturation +60` for `color_pop`; `saturation 0` for `bw_moment`).
4. **Captions & Hook**: Convert SRT to Captions -> Upgrade Caption to Graphic -> apply Essential Graphics preset; verify with safe-zone guides (`900×1160`).
5. **MCP Shortcuts** (when connected to live Premiere Pro): Pair with `auto_reframe_sequence`, `plan_emphasis_zoom_keyframes`, `check_caption_safe_zone`, `setup_ducking`, `add_text_overlay`, and `verify_delivery_conformance`.

### C. DaVinci Resolve
1. **Import**: *File -> Import -> Timeline...* -> `exports/timeline.fcpxml` (`Scout Selects` pre-trimmed timeline).
2. **Timeline**: Switch Timeline Resolution to `1080×1920` Vertical (`Use Vertical Resolution`), enable **Smart Reframe** in Inspector for `TRACK`.
3. **Keyframes**: Use **Dynamic Zoom** (Ease In/Out) or Transform Zoom keyframes (`<= 1.15x`) **before** Subtitle/Fusion text tracks.
4. **Fairlight Audio**: Normalize Dialogue track to `-14 LUFS / -1.2 dBTP`, sidechain compressor on Music track (`-3 dB` duck triggered by Voice bus).

### D. Remotion / FFmpeg Automation
- **Remotion**: Feed `highlights.json` (`words[]`) + `edit_plan.json` into `<ShortVideo>` / `<HookOverlay>` / `<Subtitles>` (or pair with `remotion-video-editor` + `video-direction-qa` for `short_qa.py` frame/LUFS audit).
- **FFmpeg Filtergraph Gotcha**: Never keep apostrophes (`'`) inside file paths passed to `ass='...'` or `sendcmd=f='...'` — FFmpeg's filter parser breaks on shell-escaped quotes (`'\''`). Always use clean slug filenames (`subs_01.ass`) and run zoom/crop filters **before** `ass=` / `overlay=` hook filters.
