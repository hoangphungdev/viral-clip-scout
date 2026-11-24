# Layouts & Vertical Reframing Guide (16:9 → 9:16)

Synthesized from `mutonby/openshorts` (`layout_picker.py`, `reframe_v2.py`, `split_layout.py`, `screencast_layout.py`, `camera_inset.py`, `active_speaker.py`, `burned_subtitles.py`), `JeremySNR/cutawan` (LR-ASD speaker detection), and `aristache-labs/ViralCutter` (smart split screen).

---

## 1. Closed-Choice Frame Sampling (Why & How)

Never guess layout from transcript alone, and avoid fragile continuous pixel thresholds (e.g. edge density or raw width percentages) — they fail to tell a spreadsheet apart from a corner scoreboard.

- **Sample 6–12 frames at `1024px` wide** (`analyze_for_edit.py inspect --sample-frames` uses `ffmpeg` to extract 8–12 frames at 1024px; at 640px spreadsheets and UI become illegible).
- Make a **closed-choice categorical decision** per clip or per scene (`PRO_TALKING_HEAD`, `TRACK`, `SPLIT`, `ALTERNATE`, `SCREENCAST`, `INSET`, `WIDE`).
- If the source video is **already vertical (`9:16`)**, skip layout classification and treat as `TRACK` / `PRO_TALKING_HEAD`.

---

## 2. Pre-Reframe Check: Source Burned-In Subtitles

Before reframing a landscape video (`burned_subtitles.py`):
- Check whether the source footage **already has subtitles burned into the lower picture** (excluding corner logos, tickers, or occasional lower-thirds).
- **Trigger rule**: If source subtitles appear in **`>= 40%` of sampled frames** and start **below `75%` of frame height**:
  - **Crop that bottom band off before reframing** (`source_subtitle_band_crop`) rather than cropping horizontally first or stacking your own captions on top.
  - Cropping from the bottom preserves horizontal face coordinates and prevents double-stacked or edge-clipped subtitles.

---

## 3. The 7 Vertical Layout Modes

| Layout Mode | Best For | Crop / Composition Geometry | Critical Guards & Anti-Failure Rules |
| :--- | :--- | :--- | :--- |
| **`PRO_TALKING_HEAD`** | Solo creator / talking head to camera | Tight face-centered 9:16 (`FACE_HEIGHT 0.30–0.37` of frame height, max `0.37`; top of head at `HEAD_TOP = 0.135`); dead air cut + alternating scale cuts (`1.00 / 1.12 / 1.05 / 1.16`) + subtle background dimming (`0.24` gain / light blur) | Only use when **`>= 90%` of clip is single-person TRACK**, **1 real face appears on `>= 70%` of keyframes** (face box height `0.07–0.60`), and no screen/split content is needed. Never apply to screencasts or wide two-shots. |
| **`TRACK`** | Solo speaker moving, interview close-up, podcast solo shot | Smoothed 9:16 follow-crop centered horizontally on tracked speaker with safe-zone deadzone (`SmoothedCameraman`); `ZOOM_CENTER_Y = 0.45` keeps headroom | Never snap-pan on minor head turns (use deadzone smoothing); protect headroom so zoomed shots never slice the forehead. |
| **`SPLIT`** | Podcast / debate / reaction wide two-shot (`>= 2.5s`) | Stack **Top 50% (Speaker A) / Bottom 50% (Speaker B)** inside 1080×1920 | Requires **two real faces side-by-side** in at least half of scene frames, lasting `>= 2.5s`, with **both speakers active**. Move captions to the **center seam (`47–54%` Y)** (`\an5`) so neither speaker's mouth nor bottom UI overlaps text. |
| **`ALTERNATE`** | Edited multi-cam podcasts or dynamic two-person back-and-forth | Hard-cut full 9:16 frame directly to whoever is actively speaking (Cutawan LR-ASD / OpenShorts `active_speaker.py`) | **Normalize mouth activity per speaker** (raw pixel diff scales with lighting/contrast) and apply **hysteresis (`SpeakerTracker`)** so brief breaths or crosstalk do not cause rapid ping-pong cuts. |
| **`SCREENCAST`** (`beside`) | Presenter standing/sitting next to slides, code, chart, or browser | **Stack content columns on top (~60–70% height), face-framed presenter on bottom** | Stack **only the content side** (away from presenter body, requiring `>= 30%` reading width) — stacking the whole frame duplicates the presenter. If a full-body presenter (`>= 60%` frame height) stands in front of a filmed whiteboard/TV, use `TRACK` instead. |
| **`INSET`** | OBS / Loom / Twitch VODs with a small static webcam in a corner or floating window | **Full-width screen content in upper/middle zone + enlarged webcam crop below** | Confirm webcam subject is **small**, **horizontally off-center**, and **still across sampled frames**. Grow face crop to **3× face width** for head-and-shoulders framing and preserve **headroom above forehead** (`FACE_HEADROOM`) rather than pinning to bottom edge. Apply only to scenes where webcam is actually present. |
| **`WIDE`** | Gameplay, charts, cinematic B-roll, full-screen demos without presenter | Moderate **~1.3× zoom** (`WIDE_CONTENT_HEIGHT_RATIO ≈ 0.41`, keeping **~77% width**, capped at **1.4×**, untouched for 4:3) centered on horizontal motion (`wide_action_centre`) | Avoid unzoomed full-width 16:9 inside 9:16 (`~608px` strip = 32% height, illegible on phones). Ignore static HUDs/pillarboxes when computing motion center; shift horizontal crop only if it captures `>= 10%` more motion. Keep hook text **outside the content band**. |

---

## 4. Per-Scene Hybrid Routing (Podcasts & Tutorials)

Long-form clips rarely stay in one shot type for all 45 seconds:
- An **edited podcast** cuts between solo close-ups (`TRACK`) and wide two-shots (`SPLIT`) — route per scene (`layout_ranges`) rather than forcing `SPLIT` across close-ups or shrinking a 39s two-shot into a tiny blurry letterbox.
- A **tutorial/screencast** cuts between webcam-only talking points (`TRACK`), full-screen UI (`WIDE`), and corner-cam demos (`INSET`) — map each scene timestamp range in `layout_ranges` so the editor knows every switch point.
