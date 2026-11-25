#!/usr/bin/env python3
"""Edit telemetry inspector, frame sampler, and blueprint guardrail validator.

Pure Python 3.10+ stdlib (uses ffmpeg optionally only when --sample-frames is requested).
Pairs with viral-clip-scout outputs (highlights.json or .srt) to power the
viral-short-edit-blueprint skill.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Configure UTF-8 stdio on Windows so Unicode/Vietnamese/emoji never crash prints.
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# --- Production Constants (distilled from openshorts & retention QA) ----------
VALID_LAYOUTS = {
    "TRACK", "PRO_TALKING_HEAD", "SPLIT", "ALTERNATE", "SCREENCAST", "INSET", "WIDE",
}
VALID_HOOK_STYLES = {
    "pill", "classic", "dark", "yellow", "red", "outline", "outline_yellow",
}
VALID_CAPTION_PRESETS = {
    "default", "hormozi", "pill", "lime", "oneword", "cine", "clean",
}
VALID_EFFECT_TYPES = {
    "zoom_in", "punch_in", "zoom_pulse", "color_pop", "bw_moment",
    "flash", "vignette", "broll_cutaway", "screen_callout", "keyword_title",
}
ZOOM_EFFECT_TYPES = {"zoom_in", "punch_in", "zoom_pulse"}

MIN_SILENCE = 0.36
KEEP_BEFORE = 0.13
KEEP_AFTER = 0.10
MIN_KEEP = 0.30
MIN_RESULT_SECONDS = 5.0

SCALE_LEVELS = (1.00, 1.12, 1.05, 1.16)
MIN_BEAT = 1.6
MAX_BEAT = 4.5

TOP_MARGIN = 0.06
BOTTOM_UI = 0.80
BOTTOM_CAPTIONS = (0.70, 0.88)
SEAM_CAPTIONS = (0.42, 0.58)

MAX_EDITS = 12
MIN_EFFECT_SECONDS = 0.15
MAX_ZOOM_SECONDS = 8.0
MAX_ZOOM_STRENGTH = 0.15
MAX_FLASHES = 2
MAX_TITLES = 5
TITLE_MAX_CHARS = 14
TITLE_GAP = 2.5

_SRT_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})"
)
_TAG_RE = re.compile(r"<[^>]+>")


def _slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return (s[:max_len] or "clip").strip("_")


def _parse_ts(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    blocks = re.split(r"\n{2,}", raw.strip())
    cues: list[dict[str, Any]] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        ts_idx = next((i for i, ln in enumerate(lines) if _SRT_TIME_RE.search(ln)), -1)
        if ts_idx < 0:
            continue
        m = _SRT_TIME_RE.search(lines[ts_idx])
        assert m is not None
        start = _parse_ts(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _parse_ts(m.group(5), m.group(6), m.group(7), m.group(8))
        text = " ".join(_TAG_RE.sub("", ln) for ln in lines[ts_idx + 1 :]).strip()
        text = re.sub(r"\s+", " ", text)
        if text and end > start:
            cues.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    return cues


def merge_continuation_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge continuation tokens lacking a leading space into their base word."""
    merged: list[dict[str, Any]] = []
    for w in words:
        raw = str(w.get("word", ""))
        if not raw.strip():
            continue
        if merged and not raw.startswith(" "):
            prev = merged[-1]
            prev["word"] = f"{prev['word']}{raw}"
            if w.get("end") is not None:
                prev["end"] = float(w["end"])
        else:
            merged.append({
                "word": raw.strip(),
                "start": float(w.get("start", 0.0)),
                "end": float(w.get("end", 0.0)),
            })
    return merged


def build_caption_blocks(
    words: list[dict[str, Any]], max_chars: int = 18, max_duration: float = 1.4
) -> list[dict[str, Any]]:
    if not words:
        return []
    blocks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    block_start = words[0]["start"]

    for w in words:
        token = w["word"]
        if not current:
            current = [w]
            block_start = w["start"]
            continue
        cur_len = sum(len(item["word"]) + 1 for item in current)
        dur = w["end"] - block_start
        if cur_len + len(token) > max_chars or dur > max_duration:
            blocks.append(current)
            current = [w]
            block_start = w["start"]
        else:
            current.append(w)
    if current:
        blocks.append(current)

    return [
        {
            "start": round(b[0]["start"], 3),
            "end": round(b[-1]["end"], 3),
            "text": " ".join(item["word"] for item in b),
        }
        for b in blocks
    ]


def compute_silence_cuts(
    spans: list[dict[str, Any]],
    duration: float,
    max_silence: float = MIN_SILENCE,
) -> tuple[list[dict[str, Any]], float]:
    """Detect dead-air gaps >= max_silence while preserving KEEP_BEFORE/KEEP_AFTER."""
    if not spans or duration <= 0:
        return [], 0.0
    cuts: list[dict[str, Any]] = []
    # Leading dead air before first spoken token
    if spans[0]["start"] >= max_silence:
        cut_end = round(max(0.0, spans[0]["start"] - KEEP_AFTER), 3)
        if cut_end >= 0.15:
            cuts.append({
                "start": 0.0,
                "end": cut_end,
                "saved_sec": cut_end,
                "reason": "leading_dead_air",
            })

    for prev, nxt in zip(spans, spans[1:]):
        gap = nxt["start"] - prev["end"]
        if gap >= max_silence:
            cs = round(prev["end"] + KEEP_BEFORE, 3)
            ce = round(nxt["start"] - KEEP_AFTER, 3)
            if ce - cs >= 0.10:
                cuts.append({
                    "start": cs,
                    "end": ce,
                    "saved_sec": round(ce - cs, 3),
                    "reason": "dead_air",
                })

    # Trailing dead air after final token
    tail_gap = duration - spans[-1]["end"]
    if tail_gap >= max_silence:
        cs = round(spans[-1]["end"] + KEEP_BEFORE, 3)
        if duration - cs >= 0.15:
            cuts.append({
                "start": cs,
                "end": round(duration, 3),
                "saved_sec": round(duration - cs, 3),
                "reason": "trailing_dead_air",
            })

    total_saved = round(sum(c["saved_sec"] for c in cuts), 3)
    return cuts, total_saved


def suggest_scale_beats(
    duration: float, silence_cuts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Suggest scale changes (1.00 -> 1.12 -> 1.05 -> 1.16) spaced 1.6-4.5s apart."""
    if duration <= 0:
        return []
    anchors = [0.0]
    for cut in silence_cuts:
        t = round(cut["end"], 2)
        if t - anchors[-1] >= MIN_BEAT and duration - t >= 1.0:
            anchors.append(t)

    # Fill long holds (> MAX_BEAT) with intermediate scale shifts.
    filled: list[float] = [0.0]
    for target in anchors[1:] + [duration]:
        while target - filled[-1] > MAX_BEAT:
            nxt = round(filled[-1] + 3.0, 2)
            if target - nxt < MIN_BEAT:
                break
            filled.append(nxt)
        if target < duration and target - filled[-1] >= MIN_BEAT:
            filled.append(target)

    return [
        {"time": t, "scale": SCALE_LEVELS[i % len(SCALE_LEVELS)], "push_per_sec": 0.008}
        for i, t in enumerate(filled)
    ]


def _sample_video_frames(
    video_path: Path,
    start_sec: float,
    end_sec: float,
    out_dir: Path,
    count: int = 8,
    width: int = 1024,
) -> list[str]:
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin or not video_path.exists():
        return []
    count = max(1, min(12, count))
    span = max(0.5, end_sec - start_sec)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for idx in range(count):
        ts = start_sec + span * ((idx + 0.5) / count)
        dst = out_dir / f"frame_{idx + 1:02d}_{ts:.2f}s.jpg"
        cmd = [
            ffmpeg_bin, "-y", "-ss", f"{ts:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(dst),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode == 0 and dst.exists():
            saved.append(str(dst))
    return saved


def _analyze_clip(
    clip_id: str,
    title: str,
    duration: float,
    raw_words: list[dict[str, Any]],
    cues: list[dict[str, Any]],
    max_silence: float,
    meta: dict[str, Any],
) -> dict[str, Any]:
    merged_words = merge_continuation_words(raw_words)
    if merged_words:
        spans = merged_words
        word_count = len(merged_words)
        blocks = build_caption_blocks(merged_words)
    else:
        spans = cues
        word_count = sum(len(c["text"].split()) for c in cues)
        # Approximate word blocks from cues when only SRT is available.
        approx_words: list[dict[str, Any]] = []
        for c in cues:
            tokens = c["text"].split()
            if not tokens:
                continue
            step = (c["end"] - c["start"]) / len(tokens)
            for i, tok in enumerate(tokens):
                approx_words.append({
                    "word": tok,
                    "start": c["start"] + i * step,
                    "end": c["start"] + (i + 1) * step,
                })
        blocks = build_caption_blocks(approx_words)

    wps = round(word_count / max(0.1, duration), 2)
    if wps < 3.0:
        verdict = "slow_needs_tightening"
    elif wps <= 4.2:
        verdict = "optimal_short_cadence"
    else:
        verdict = "fast_preserve_breathing_room"

    silence_cuts, saved_sec = compute_silence_cuts(spans, duration, max_silence=max_silence)
    est_tight_dur = round(max(0.0, duration - saved_sec), 3)
    scale_beats = suggest_scale_beats(duration, silence_cuts)

    return {
        "clip_id": clip_id,
        "title": title,
        "duration_sec": round(duration, 3),
        "word_count": word_count,
        "words_per_sec": wps,
        "pacing_verdict": verdict,
        "has_word_timestamps": bool(merged_words),
        "silence_cuts": silence_cuts,
        "estimated_tightened_duration_sec": est_tight_dur,
        "time_saved_sec": saved_sec,
        "suggested_scale_beats": scale_beats,
        "caption_blocks_preview": blocks[:20],
        "total_caption_blocks": len(blocks),
        **meta,
    }


def cmd_inspect(args: argparse.Namespace) -> None:
    inp = Path(args.input).resolve()
    if not inp.exists():
        raise SystemExit(f"Input file not found: {inp}")
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    video_override = Path(args.video).resolve() if args.video else None
    clips_out: list[dict[str, Any]] = []

    if inp.suffix.lower() == ".json":
        doc = json.loads(inp.read_text(encoding="utf-8-sig"))
        kept = doc.get("kept") or []
        source = str(doc.get("source") or "")
        src_path = video_override or (Path(source) if source and Path(source).exists() else None)
        if args.clip_rank is not None:
            kept = [c for c in kept if int(c.get("rank", -1)) == args.clip_rank]
        for c in kept:
            rank = int(c.get("rank", len(clips_out) + 1))
            clip_id = f"clip_{rank:02d}"
            title = str(c.get("title") or clip_id)
            dur = float(c.get("duration") or max(0.0, float(c.get("end", 0)) - float(c.get("start", 0))))
            words = c.get("words") or []
            srt_file = Path(c["srt_file"]) if c.get("srt_file") else None
            cues = parse_srt(srt_file) if (srt_file and srt_file.exists()) else []
            sampled: list[str] = []
            if args.sample_frames and src_path is not None:
                c_start = 0.0 if video_override and video_override != Path(source) else float(c.get("start", 0.0))
                c_end = dur if c_start == 0.0 and video_override else float(c.get("end", dur))
                sampled = _sample_video_frames(
                    src_path, c_start, c_end, out_dir / "frames" / f"{clip_id}_{_slug(title)}",
                    count=args.frames, width=args.width,
                )
            clips_out.append(_analyze_clip(
                clip_id=clip_id,
                title=title,
                duration=dur,
                raw_words=words,
                cues=cues,
                max_silence=args.max_silence,
                meta={
                    "rank": rank,
                    "source_start": float(c.get("start", 0.0)),
                    "source_end": float(c.get("end", dur)),
                    "scout_total_score": c.get("total_score"),
                    "scout_scores": c.get("scores"),
                    "scout_hook": c.get("hook", ""),
                    "scout_why": c.get("why", ""),
                    "scout_edit_notes": c.get("edit_notes", ""),
                    "srt_file": str(srt_file) if srt_file else None,
                    "sampled_frames": sampled,
                },
            ))
    elif inp.suffix.lower() == ".srt":
        cues = parse_srt(inp)
        dur = cues[-1]["end"] if cues else 0.0
        sampled = []
        if args.sample_frames and video_override is not None:
            sampled = _sample_video_frames(
                video_override, 0.0, dur, out_dir / "frames" / f"clip_01_{_slug(inp.stem)}",
                count=args.frames, width=args.width,
            )
        clips_out.append(_analyze_clip(
            clip_id="clip_01",
            title=inp.stem,
            duration=dur,
            raw_words=[],
            cues=cues,
            max_silence=args.max_silence,
            meta={"srt_file": str(inp), "sampled_frames": sampled},
        ))
    else:
        raise SystemExit(f"Unsupported input format '{inp.suffix}'; expected highlights.json or .srt")

    telemetry_path = out_dir / "edit_telemetry.json"
    payload = {
        "input": str(inp),
        "clips_count": len(clips_out),
        "clips": clips_out,
    }
    telemetry_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "telemetry_file": str(telemetry_path),
        "clips_count": len(clips_out),
        "clips": [
            {
                "clip_id": c["clip_id"],
                "title": c["title"],
                "duration_sec": c["duration_sec"],
                "words_per_sec": c["words_per_sec"],
                "pacing_verdict": c["pacing_verdict"],
                "silence_cuts_count": len(c["silence_cuts"]),
                "time_saved_sec": c["time_saved_sec"],
                "sampled_frames_count": len(c.get("sampled_frames", [])),
            }
            for c in clips_out
        ],
    }, indent=2, ensure_ascii=False))


def validate_edit_plan(plan: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Validate an edit_plan.json dict against production guardrails."""
    errors: list[str] = []
    warnings: list[str] = []

    required = ("clip_id", "duration_sec", "layout_mode", "hook", "captions", "effects", "audio")
    for key in required:
        if key not in plan:
            errors.append(f"Missing required field '{key}'.")
    if errors:
        return errors, warnings

    try:
        duration = float(plan["duration_sec"])
    except (TypeError, ValueError):
        errors.append("duration_sec must be numeric.")
        return errors, warnings

    if duration < MIN_RESULT_SECONDS:
        errors.append(f"duration_sec ({duration:.2f}s) must be >= {MIN_RESULT_SECONDS}s.")

    layout = str(plan["layout_mode"]).strip()
    if layout not in VALID_LAYOUTS:
        errors.append(f"Invalid layout_mode '{layout}'. Expected one of {sorted(VALID_LAYOUTS)}.")

    has_burned = bool(plan.get("has_burned_captions", False))

    # --- Hook checks ---
    hook = plan.get("hook") or {}
    if not isinstance(hook, dict):
        errors.append("hook must be an object.")
    else:
        htext = str(hook.get("text", "")).strip()
        if not htext:
            errors.append("hook.text must be non-empty.")
        elif len(htext.split()) > 12:
            warnings.append(f"hook.text has {len(htext.split())} words (recommended <= 10 words).")

        hstyle = str(hook.get("style", "")).strip()
        if hstyle not in VALID_HOOK_STYLES:
            errors.append(f"Invalid hook.style '{hstyle}'. Expected one of {sorted(VALID_HOOK_STYLES)}.")

        try:
            hdur = float(hook.get("duration_sec", 0.0))
        except (TypeError, ValueError):
            hdur = 0.0
        if hdur < 1.5 or hdur > 6.0:
            errors.append(f"hook.duration_sec ({hdur}) must be within [1.5, 6.0].")

        try:
            y_pct = float(hook.get("y_pct", -1.0))
        except (TypeError, ValueError):
            y_pct = -1.0
        if not (TOP_MARGIN <= y_pct <= BOTTOM_UI):
            errors.append(f"hook.y_pct ({y_pct}) outside safe vertical bounds [{TOP_MARGIN}, {BOTTOM_UI}].")
        else:
            band = SEAM_CAPTIONS if layout == "SPLIT" else BOTTOM_CAPTIONS
            if band[0] <= y_pct <= band[1]:
                errors.append(
                    f"hook.y_pct ({y_pct}) collides with active caption band {band} for layout '{layout}'."
                )

    # --- Captions checks ---
    caps = plan.get("captions") or {}
    if not isinstance(caps, dict):
        errors.append("captions must be an object.")
    else:
        preset = str(caps.get("preset", "")).strip()
        if preset not in VALID_CAPTION_PRESETS:
            errors.append(f"Invalid captions.preset '{preset}'. Expected one of {sorted(VALID_CAPTION_PRESETS)}.")
        max_chars = caps.get("max_chars", 18)
        if not isinstance(max_chars, int) or max_chars < 1 or max_chars > 22:
            errors.append(f"captions.max_chars ({max_chars}) must be an integer in [1, 22].")
        cap_pos = str(caps.get("position", "bottom")).strip()
        if layout == "SPLIT" and cap_pos != "seam":
            warnings.append("layout_mode is SPLIT; captions.position should usually be 'seam' (47-54% Y).")

    # --- Silence cuts checks ---
    cuts = plan.get("silence_cuts") or []
    total_cut = 0.0
    for i, c in enumerate(cuts):
        try:
            cs, ce = float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"silence_cuts[{i}] must have numeric 'start' and 'end'.")
            continue
        if cs < 0 or ce > duration or ce <= cs:
            errors.append(f"silence_cuts[{i}] ({cs}..{ce}) invalid for duration {duration}.")
        else:
            total_cut += (ce - cs)
    if duration - total_cut < MIN_RESULT_SECONDS:
        errors.append(
            f"Remaining duration after silence_cuts ({duration - total_cut:.2f}s) < {MIN_RESULT_SECONDS}s."
        )

    # --- Effects checks ---
    effects = plan.get("effects") or []
    dur_mult = max(1, math.ceil(duration / 60.0)) if duration > 75.0 else 1
    max_edits = min(30, MAX_EDITS * dur_mult)
    max_flashes = min(5, MAX_FLASHES + (dur_mult - 1))
    max_titles = min(12, MAX_TITLES + 3 * (dur_mult - 1))

    if not isinstance(effects, list):
        errors.append("effects must be a list.")
    else:
        if len(effects) > max_edits:
            errors.append(f"Too many effects ({len(effects)} > max {max_edits}).")
        zooms: list[tuple[float, float, str]] = []
        flash_count = 0
        titles: list[tuple[float, str]] = []
        hook_dur = float(hook.get("duration_sec", 0.0)) if isinstance(hook, dict) else 0.0

        for i, eff in enumerate(effects):
            if not isinstance(eff, dict):
                errors.append(f"effects[{i}] must be an object.")
                continue
            etype = str(eff.get("type", "")).strip()
            if etype not in VALID_EFFECT_TYPES:
                errors.append(f"effects[{i}] invalid type '{etype}'.")
                continue
            try:
                es, ee = float(eff["start"]), float(eff["end"])
            except (KeyError, TypeError, ValueError):
                errors.append(f"effects[{i}] requires numeric 'start' and 'end'.")
                continue
            if es < -1e-6 or ee > duration + 1e-6 or (ee - es) + 1e-6 < MIN_EFFECT_SECONDS:
                errors.append(
                    f"effects[{i}] ({etype}) range {es}..{ee} invalid (must fit [0, {duration}] and >= {MIN_EFFECT_SECONDS}s)."
                )

            if etype in ZOOM_EFFECT_TYPES:
                if has_burned:
                    errors.append(f"effects[{i}] ({etype}) is forbidden when has_burned_captions=true.")
                if (ee - es) - 1e-6 > MAX_ZOOM_SECONDS:
                    errors.append(f"effects[{i}] ({etype}) duration {ee - es:.2f}s > {MAX_ZOOM_SECONDS}s.")
                strength = eff.get("strength", 0.12)
                try:
                    strength_f = float(strength)
                except (TypeError, ValueError):
                    strength_f = 999.0
                if strength_f <= 0 or strength_f > MAX_ZOOM_STRENGTH:
                    errors.append(
                        f"effects[{i}] ({etype}) strength ({strength}) must be in (0, {MAX_ZOOM_STRENGTH}]."
                    )
                zooms.append((es, ee, etype))
            elif etype == "flash":
                flash_count += 1
            elif etype == "keyword_title":
                ttext = str(eff.get("text", "")).strip()
                if not ttext:
                    errors.append(f"effects[{i}] (keyword_title) requires non-empty 'text'.")
                elif len(ttext) > TITLE_MAX_CHARS:
                    errors.append(
                        f"effects[{i}] (keyword_title) text '{ttext}' length {len(ttext)} > {TITLE_MAX_CHARS}."
                    )
                if es < hook_dur:
                    errors.append(
                        f"effects[{i}] (keyword_title) starts at {es}s inside hook window [0, {hook_dur}s]."
                    )
                titles.append((es, ttext))

        # Check zoom overlap
        zooms.sort(key=lambda z: (z[0], z[1]))
        for (s1, e1, t1), (s2, e2, t2) in zip(zooms, zooms[1:]):
            if s2 < e1:
                errors.append(f"Overlapping zoom effects: {t1} ({s1}..{e1}) overlaps {t2} ({s2}..{e2}).")

        if flash_count > max_flashes:
            errors.append(f"Too many flash effects ({flash_count} > max {max_flashes}).")
        if len(titles) > max_titles:
            errors.append(f"Too many keyword_title effects ({len(titles)} > max {max_titles}).")
        titles.sort(key=lambda t: t[0])
        for (t1, n1), (t2, n2) in zip(titles, titles[1:]):
            if (t2 - t1) < TITLE_GAP:
                errors.append(
                    f"keyword_title '{n2}' at {t2}s is closer than {TITLE_GAP}s to '{n1}' at {t1}s."
                )

    return errors, warnings


def cmd_validate(args: argparse.Namespace) -> None:
    plan_path = Path(args.plan).resolve()
    if not plan_path.exists():
        raise SystemExit(f"Edit plan not found: {plan_path}")
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    errors, warnings = validate_edit_plan(plan)
    out = {
        "valid": len(errors) == 0,
        "plan_file": str(plan_path),
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if errors:
        sys.exit(1)


def cmd_selftest(_args: argparse.Namespace) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # Check 1: Inspect mock viral-clip-scout highlights.json with words[] + continuation + dead air
        srt_clip = root / "clip_01.srt"
        srt_clip.write_text("1\n00:00:00,000 --> 00:00:04,000\nHook line\n", encoding="utf-8")
        highlights = root / "highlights.json"
        highlights.write_text(json.dumps({
            "source": "talk.mp4",
            "title": "Podcast",
            "kept": [{
                "rank": 1,
                "start": 10.0,
                "end": 22.0,
                "duration": 12.0,
                "total_score": 84,
                "scores": {"hook": 22, "standalone": 20, "value": 21, "payoff": 21},
                "title": "Why YouTube-Channels Fail",
                "hook": "Stop cutting like this",
                "why": "Concrete editing mistake",
                "edit_notes": "Punch in on metric",
                "srt_file": str(srt_clip),
                "words": [
                    {"word": " Stop", "start": 0.0, "end": 0.35},
                    {"word": " editing", "start": 0.36, "end": 0.80},
                    {"word": " YouTube", "start": 0.82, "end": 1.25},
                    {"word": "-Channels", "start": 1.26, "end": 1.65},
                    {"word": " blindly.", "start": 2.50, "end": 3.00},
                ],
            }],
        }), encoding="utf-8")
        out1 = root / "out1"
        cmd_inspect(argparse.Namespace(
            input=str(highlights), out=str(out1), clip_rank=None,
            video=None, sample_frames=False, frames=8, width=1024, max_silence=0.36,
        ))
        tel1 = json.loads((out1 / "edit_telemetry.json").read_text(encoding="utf-8"))
        clip1 = tel1["clips"][0]
        assert clip1["word_count"] == 4, f"Expected merged word_count 4, got {clip1['word_count']}"
        assert len(clip1["silence_cuts"]) >= 1, "Expected >=1 silence cut (0.85s gap + trailing)"
        all_cap_text = " ".join(b["text"] for b in clip1["caption_blocks_preview"])
        assert "YouTube-Channels" in all_cap_text, f"Expected merged token in {clip1['caption_blocks_preview']}"

        # Check 2: Inspect standalone .srt
        out2 = root / "out2"
        cmd_inspect(argparse.Namespace(
            input=str(srt_clip), out=str(out2), clip_rank=None,
            video=None, sample_frames=False, frames=8, width=1024, max_silence=0.36,
        ))
        tel2 = json.loads((out2 / "edit_telemetry.json").read_text(encoding="utf-8"))
        assert tel2["clips_count"] == 1

        # Check 3: Valid edit_plan.json passes
        good_plan = {
            "clip_id": "clip_01",
            "title": "Good Edit",
            "genre": "knowledge",
            "duration_sec": 30.0,
            "has_burned_captions": False,
            "layout_mode": "PRO_TALKING_HEAD",
            "hook": {"text": "Stop cutting pauses blindly", "style": "pill", "duration_sec": 3.5, "y_pct": 0.14},
            "silence_cuts": [{"start": 10.0, "end": 10.8}],
            "effects": [
                {"type": "flash", "start": 3.5, "end": 3.65},
                {"type": "punch_in", "start": 6.0, "end": 8.0, "strength": 0.12},
                {"type": "keyword_title", "start": 11.0, "end": 12.45, "text": "3X RETENTION"},
            ],
            "captions": {"preset": "hormozi", "position": "bottom", "max_chars": 9},
            "audio": {"voice_lufs_target": -14.0},
        }
        errs_ok, _ = validate_edit_plan(good_plan)
        assert not errs_ok, f"Expected 0 errors on good_plan, got: {errs_ok}"

        # Check 4: Broken edit_plan.json triggers all guardrails
        bad_plan = {
            "clip_id": "clip_bad",
            "duration_sec": 20.0,
            "has_burned_captions": True,
            "layout_mode": "TRACK",
            "hook": {"text": "Bad hook", "style": "pill", "duration_sec": 3.5, "y_pct": 0.76},
            "silence_cuts": [],
            "effects": [
                {"type": "zoom_in", "start": 2.0, "end": 6.0, "strength": 0.25},
                {"type": "punch_in", "start": 5.0, "end": 7.0, "strength": 0.10},
                {"type": "flash", "start": 1.0, "end": 1.15},
                {"type": "flash", "start": 4.0, "end": 4.15},
                {"type": "flash", "start": 8.0, "end": 8.15},
                {"type": "keyword_title", "start": 1.5, "end": 2.95, "text": "WAY TOO LONG TITLE TEXT"},
            ],
            "captions": {"preset": "default", "position": "bottom", "max_chars": 18},
            "audio": {"voice_lufs_target": -14.0},
        }
        errs_bad, _ = validate_edit_plan(bad_plan)
        joined = " | ".join(errs_bad)
        assert "collides with active caption band" in joined
        assert "has_burned_captions=true" in joined
        assert "Overlapping zoom effects" in joined
        assert "Too many flash effects" in joined
        assert "inside hook window" in joined
        assert "MAX_ZOOM_STRENGTH" in joined or "strength" in joined

        # Check 5: Extended 150s Short scales allowed flash/title/effect caps cleanly
        extended_plan = {
            "clip_id": "clip_ext",
            "title": "Extended 150s Story Short",
            "genre": "stream",
            "duration_sec": 150.0,
            "has_burned_captions": False,
            "layout_mode": "WIDE",
            "hook": {"text": "He almost missed the plane", "style": "red", "duration_sec": 3.5, "y_pct": 0.14},
            "silence_cuts": [],
            "effects": [
                {"type": "flash", "start": 3.5, "end": 3.65},
                {"type": "flash", "start": 55.0, "end": 55.15},
                {"type": "flash", "start": 108.0, "end": 108.15},
                {"type": "keyword_title", "start": 12.0, "end": 13.45, "text": "2 MIN LEFT"},
                {"type": "keyword_title", "start": 28.0, "end": 29.45, "text": "BUS HIJACK"},
                {"type": "keyword_title", "start": 58.0, "end": 59.45, "text": "FOUND A PLANE"},
                {"type": "keyword_title", "start": 78.0, "end": 79.45, "text": "CHOPPER FIRE"},
                {"type": "keyword_title", "start": 95.0, "end": 96.45, "text": "28 SECONDS"},
                {"type": "keyword_title", "start": 112.0, "end": 113.45, "text": "LIFTOFF!"},
                {"type": "keyword_title", "start": 130.0, "end": 131.45, "text": "MOM CALLED"},
            ],
            "captions": {"preset": "default", "position": "bottom", "max_chars": 18},
            "audio": {"voice_lufs_target": -14.0},
        }
        errs_ext, _ = validate_edit_plan(extended_plan)
        assert not errs_ext, f"Expected 0 errors on extended_plan, got: {errs_ext}"

    print(json.dumps({"selftest": "passed", "checks": 5}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze clips and validate viral short edit blueprints.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ins = sub.add_parser("inspect", help="Compute edit telemetry and optionally sample frames.")
    p_ins.add_argument("input", help="Path to viral-clip-scout highlights.json or .srt")
    p_ins.add_argument("--out", required=True, help="Output directory for edit_telemetry.json and frames/")
    p_ins.add_argument("--clip-rank", type=int, default=None, help="Filter highlights.json to a single rank")
    p_ins.add_argument("--video", default=None, help="Local video file for --sample-frames")
    p_ins.add_argument("--sample-frames", action="store_true", help="Extract evenly spaced 1024px stills via ffmpeg")
    p_ins.add_argument("--frames", type=int, default=8, help="Number of frames to sample per clip (1-12)")
    p_ins.add_argument("--width", type=int, default=1024, help="Width in px for sampled frames")
    p_ins.add_argument("--max-silence", type=float, default=MIN_SILENCE, help="Silence gap threshold in seconds")
    p_ins.set_defaults(func=cmd_inspect)

    p_val = sub.add_parser("validate", help="Validate an edit_plan.json against retention & render guardrails.")
    p_val.add_argument("plan", help="Path to edit_plan.json")
    p_val.set_defaults(func=cmd_validate)

    p_st = sub.add_parser("selftest", help="Run deterministic self-tests.")
    p_st.set_defaults(func=cmd_selftest)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
