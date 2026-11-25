#!/usr/bin/env python3
"""Zero-dependency viral clip scout CLI (Python 3.10+ stdlib only).

Subcommands:
  prepare   Extract transcript cues, acoustic RMS spikes, pauses, and heatmaps
            into compact chunk files (`id|MM:SS|[SIGNALS] text`) for agent analysis.
  finalize  Enforce hard 4-axis rubric thresholds (allowing 0 clips), deduplicate,
            and export highlights.json, markers.csv, markers.edl, timeline.fcpxml,
            per-clip re-timed SRTs, and lossless FFmpeg stream-copy commands.
  selftest  Run built-in unit & end-to-end checks in a temporary directory.
"""
from __future__ import annotations

import argparse
import array
import csv
import importlib.util
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import wave
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

TRANSCRIPT_EXTS = {".srt", ".vtt", ".json"}
INLINE_TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]*\}")
TIME_RANGE_RE = re.compile(
    r"(?P<s>(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*"
    r"(?P<e>(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)
SLUG_BAD_RE = re.compile(r"[^a-z0-9]+")


def _die(error: str, hint: str | None = None, code: int = 2) -> None:
    payload: dict[str, Any] = {"error": error}
    if hint:
        payload["hint"] = hint
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(code)


def _is_url(src: str) -> bool:
    return src.startswith(("http://", "https://"))


def _parse_ts(raw: str) -> float:
    clean = raw.strip().replace(",", ".")
    parts = clean.split(":")
    if len(parts) == 2:
        h, m, s = 0, int(parts[0]), float(parts[1])
    elif len(parts) == 3:
        h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    else:
        raise ValueError(f"Invalid timestamp: {raw!r}")
    return h * 3600.0 + m * 60.0 + s


def _fmt_mmss(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _fmt_srt(sec: float) -> str:
    ms_total = max(0, int(round(sec * 1000)))
    h, rem = divmod(ms_total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_smpte(sec: float, fps: float) -> str:
    fps_int = max(1, int(round(fps)))
    total_frames = max(0, int(round(sec * fps_int)))
    frames = total_frames % fps_int
    total_s = total_frames // fps_int
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}:{frames:02d}"


def _fcpxml_time(sec: float, fps_int: int) -> str:
    frames = max(0, int(round(sec * fps_int)))
    return f"{frames}/{fps_int}s"


def _slug(text: str, max_len: int = 36) -> str:
    s = SLUG_BAD_RE.sub("-", text.lower()).strip("-")
    return (s[:max_len].strip("-") or "clip")


def _clean_caption_lines(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        cleaned = " ".join(INLINE_TAG_RE.sub("", ln).split())
        if cleaned:
            out.append(cleaned)
    return out


def parse_srt_or_vtt(path: Path) -> list[dict[str, Any]]:
    """Parse .srt or .vtt, stripping markup and YouTube auto-VTT rolling repeats."""
    text = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    is_vtt = path.suffix.lower() == ".vtt" or text.lstrip().startswith("WEBVTT")
    raw_cues: list[dict[str, Any]] = []
    blocks = re.split(r"\n\s*\n", text)

    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        if is_vtt and lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        ts_idx = next((i for i, ln in enumerate(lines) if TIME_RANGE_RE.search(ln)), None)
        if ts_idx is None:
            continue
        m = TIME_RANGE_RE.search(lines[ts_idx])
        assert m is not None
        start = _parse_ts(m.group("s"))
        end = _parse_ts(m.group("e"))
        if end <= start:
            continue
        body_lines = _clean_caption_lines(lines[ts_idx + 1 :])
        if not body_lines:
            continue
        raw_cues.append({"start": start, "end": end, "lines": body_lines})

    # Deduplicate rolling captions where cue N+1 repeats cue N's trailing line(s).
    cues: list[dict[str, Any]] = []
    prev_lines: list[str] = []
    for item in raw_cues:
        cur_lines = item["lines"]
        deduped = cur_lines
        if is_vtt and prev_lines:
            full_prev = " ".join(prev_lines)
            full_cur = " ".join(cur_lines)
            if full_cur == full_prev:
                prev_lines = cur_lines
                continue
            overlap = 0
            max_check = min(len(prev_lines), len(cur_lines))
            for k in range(max_check, 0, -1):
                if prev_lines[-k:] == cur_lines[:k]:
                    overlap = k
                    break
            if overlap:
                deduped = cur_lines[overlap:]
        prev_lines = cur_lines
        joined = " ".join(deduped).strip()
        if not joined:
            continue
        cues.append({
            "id": len(cues) + 1,
            "start": round(item["start"], 3),
            "end": round(item["end"], 3),
            "text": joined,
            "words": [],
            "signals": [],
        })
    return cues


def parse_json_transcript(path: Path) -> tuple[list[dict[str, Any]], float | None]:
    """Parse Whisper/faster-whisper JSON or bare list of cue dicts."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    duration = None
    if isinstance(data, dict):
        duration = data.get("duration")
        items = data.get("cues") or data.get("segments") or []
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("Unsupported JSON transcript structure")

    cues: list[dict[str, Any]] = []
    for seg in items:
        text = " ".join(str(seg.get("text") or "").split())
        if not text:
            continue
        start = float(seg["start"])
        end = float(seg["end"])
        if end <= start:
            continue
        words = []
        for w in seg.get("words") or []:
            wt = str(w.get("word") or w.get("text") or "").strip()
            if wt and "start" in w and "end" in w:
                words.append({
                    "word": wt,
                    "start": round(float(w["start"]), 3),
                    "end": round(float(w["end"]), 3),
                })
        cues.append({
            "id": len(cues) + 1,
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
            "words": words,
            "signals": [],
        })
    return cues, (float(duration) if duration is not None else None)


def load_transcript_file(path: Path) -> tuple[list[dict[str, Any]], float | None]:
    if path.suffix.lower() == ".json":
        return parse_json_transcript(path)
    if path.suffix.lower() in {".srt", ".vtt"}:
        return parse_srt_or_vtt(path), None
    raise ValueError(f"Unsupported transcript extension: {path.suffix}")


def _ytdlp_cmd() -> list[str] | None:
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    return None


def _run_faster_whisper(media_path: Path, lang: str, model_name: str) -> list[dict[str, Any]]:
    if not importlib.util.find_spec("faster_whisper"):
        _die(
            "No transcript file provided and faster-whisper is not installed.",
            hint="Run: pip install faster-whisper   (or pass --transcript <file.srt|.vtt|.json>)",
        )
    from faster_whisper import WhisperModel  # type: ignore

    model = WhisperModel(model_name, device="auto", compute_type="int8")
    kw: dict[str, Any] = {"word_timestamps": True}
    if lang and lang != "auto":
        kw["language"] = lang
    segments, _info = model.transcribe(str(media_path), **kw)
    cues: list[dict[str, Any]] = []
    for seg in segments:
        text = " ".join((seg.text or "").split())
        if not text or seg.end <= seg.start:
            continue
        words = []
        for w in getattr(seg, "words", None) or []:
            wt = (w.word or "").strip()
            if wt:
                words.append({"word": wt, "start": round(float(w.start), 3), "end": round(float(w.end), 3)})
        cues.append({
            "id": len(cues) + 1,
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "text": text,
            "words": words,
            "signals": [],
        })
    return cues


def _pick_sub_lang(meta: dict[str, Any], requested: str) -> tuple[str | None, bool]:
    """Return (sub_lang, is_auto) prioritizing manual subtitles over auto-captions."""
    manual = meta.get("subtitles") or {}
    auto = meta.get("automatic_captions") or {}
    preferred = [requested] if requested != "auto" else []
    vid_lang = meta.get("language")
    if vid_lang and vid_lang not in preferred:
        preferred.append(vid_lang)
    for fallback in ("en", "en-US", "vi"):
        if fallback not in preferred:
            preferred.append(fallback)

    for is_auto, table in ((False, manual), (True, auto)):
        if not isinstance(table, dict) or not table:
            continue
        for cand in preferred:
            if cand in table:
                return cand, is_auto
            prefix = cand.split("-")[0]
            for key in table:
                if key == prefix or key.startswith(prefix + "-"):
                    return key, is_auto
        if requested == "auto":
            first = next((k for k in table if k != "live_chat"), None)
            if first:
                return first, is_auto
    return None, False


def _prepare_url(url: str, work_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    ytdlp = _ytdlp_cmd()
    if not ytdlp:
        _die("yt-dlp is required to analyze URLs.", hint="Run: pip install yt-dlp")

    res = subprocess.run(
        [*ytdlp, "--no-playlist", "--dump-single-json", "--skip-download", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if res.returncode != 0:
        _die(f"yt-dlp metadata fetch failed: {res.stderr.strip()[:400]}")
    meta = json.loads(res.stdout)
    title = meta.get("title") or "Untitled"
    duration = float(meta.get("duration") or 0.0)
    heatmap = meta.get("heatmap") or []
    chapters = meta.get("chapters") or []

    cues: list[dict[str, Any]] = []
    media_for_rms: Path | None = None

    if args.transcript:
        cues, tdur = load_transcript_file(Path(args.transcript))
        if not duration and tdur:
            duration = tdur
    elif not args.force_whisper:
        sub_lang, is_auto = _pick_sub_lang(meta, args.lang)
        if sub_lang:
            sub_tmpl = str(work_dir / "source_sub.%(ext)s")
            cmd = [*ytdlp, "--no-playlist", "--skip-download", "--sub-format", "vtt/srt", "--sub-langs", sub_lang, "-o", sub_tmpl]
            cmd.append("--write-auto-subs" if is_auto else "--write-subs")
            cmd.append(url)
            subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            sub_files = sorted(work_dir.glob("source_sub*.*"))
            sub_files = [p for p in sub_files if p.suffix.lower() in {".vtt", ".srt"}]
            if sub_files:
                cues = parse_srt_or_vtt(sub_files[0])

    if not cues:
        audio_tmpl = str(work_dir / "source_audio.%(ext)s")
        dl = subprocess.run(
            [*ytdlp, "--no-playlist", "-f", "bestaudio", "-o", audio_tmpl, url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if dl.returncode != 0:
            _die(f"yt-dlp audio download failed: {dl.stderr.strip()[:400]}")
        audio_files = [p for p in sorted(work_dir.glob("source_audio.*")) if p.is_file()]
        if not audio_files:
            _die("yt-dlp finished but produced no audio file.")
        media_for_rms = audio_files[0]
        cues = _run_faster_whisper(media_for_rms, args.lang, args.whisper_model)

    return {
        "title": title,
        "duration": duration,
        "fps": 30.0,
        "heatmap": heatmap,
        "chapters": chapters,
        "cues": cues,
        "media_path": media_for_rms,
    }


def _probe_fps(media_path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 30.0
    res = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
         "-of", "default=nw=1:nk=1", str(media_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    raw = res.stdout.strip()
    if not raw:
        return 30.0
    try:
        if "/" in raw:
            num, den = raw.split("/", 1)
            val = float(num) / float(den)
        else:
            val = float(raw)
        return round(val, 3) if 1.0 <= val <= 240.0 else 30.0
    except (ValueError, ZeroDivisionError):
        return 30.0


def compute_wav_loud_seconds(wav_path: Path, spike_ratio: float = 1.6) -> set[int]:
    """Compute 1-second RMS buckets from 16-bit PCM WAV using Python stdlib only."""
    with wave.open(str(wav_path), "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        if rate <= 0 or width != 2:
            return set()
        chunk_frames = rate
        step = max(1, channels * 4)
        rms_per_sec: list[tuple[int, float]] = []
        sec = 0
        while True:
            raw = wf.readframes(chunk_frames)
            if not raw:
                break
            samples = array.array("h")
            samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
            if sys.byteorder != "little":
                samples.byteswap()
            sub = samples[::step]
            if sub:
                sq_sum = sum(v * v for v in sub)
                rms = math.sqrt(sq_sum / len(sub))
                rms_per_sec.append((sec, rms))
            sec += 1

    non_silent = [r for _, r in rms_per_sec if r > 1.0]
    if len(non_silent) < 3:
        return set()
    threshold = statistics.median(non_silent) * spike_ratio
    return {s for s, r in rms_per_sec if r >= threshold}


def _extract_loud_seconds(media_path: Path) -> set[int]:
    if media_path.suffix.lower() == ".wav":
        try:
            return compute_wav_loud_seconds(media_path)
        except Exception:
            return set()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return set()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tmp_wav = Path(tf.name)
    try:
        res = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-i", str(media_path), "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(tmp_wav)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if res.returncode != 0 or not tmp_wav.exists() or tmp_wav.stat().st_size < 64:
            return set()
        return compute_wav_loud_seconds(tmp_wav)
    finally:
        tmp_wav.unlink(missing_ok=True)


def annotate_signals(
    cues: list[dict[str, Any]],
    loud_seconds: set[int],
    heatmap: list[dict[str, Any]],
) -> dict[str, int]:
    counts = {"LOUD": 0, "PAUSE": 0, "REPLAY": 0}
    prev_end: float | None = None

    for cue in cues:
        sigs: list[str] = []
        if prev_end is not None and (cue["start"] - prev_end) >= 2.0:
            sigs.append("PAUSE")
            counts["PAUSE"] += 1
        prev_end = cue["end"]

        if loud_seconds:
            s_idx = int(math.floor(cue["start"]))
            e_idx = int(math.floor(max(cue["start"], cue["end"] - 0.001)))
            if any(sec in loud_seconds for sec in range(s_idx, e_idx + 1)):
                sigs.append("LOUD")
                counts["LOUD"] += 1

        if heatmap:
            best_val = 0.0
            for pt in heatmap:
                hs = float(pt.get("start_time", 0.0))
                he = float(pt.get("end_time", 0.0))
                hv = float(pt.get("value", 0.0))
                if hv >= 0.70 and hs < cue["end"] and he > cue["start"]:
                    best_val = max(best_val, hv)
            if best_val >= 0.70:
                sigs.append(f"REPLAY:{best_val:.2f}")
                counts["REPLAY"] += 1

        cue["signals"] = sigs
    return counts


def write_chunks(
    cues: list[dict[str, Any]],
    work_dir: Path,
    duration: float,
    window_mins: float,
    overlap_mins: float,
) -> list[str]:
    window_sec = max(60.0, window_mins * 60.0)
    overlap_sec = max(0.0, min(overlap_mins * 60.0, window_sec * 0.5))
    step_sec = max(60.0, window_sec - overlap_sec)

    for old in work_dir.glob("chunk_*.txt"):
        old.unlink()

    if not cues:
        p = work_dir / "chunk_01.txt"
        p.write_text("", encoding="utf-8")
        return [str(p)]

    total_dur = max(duration, cues[-1]["end"])
    ranges: list[tuple[float, float]] = []
    if total_dur <= window_sec:
        ranges.append((0.0, total_dur + 1.0))
    else:
        cur = 0.0
        while cur < total_dur:
            end = min(total_dur + 1.0, cur + window_sec)
            ranges.append((cur, end))
            if end >= total_dur:
                break
            cur += step_sec

    paths: list[str] = []
    for idx, (w_start, w_end) in enumerate(ranges, 1):
        lines: list[str] = []
        for cue in cues:
            if cue["end"] > w_start and cue["start"] < w_end:
                sig_prefix = "".join(f"[{s}]" for s in cue.get("signals") or [])
                if sig_prefix:
                    sig_prefix += " "
                lines.append(f"{cue['id']}|{_fmt_mmss(cue['start'])}|{sig_prefix}{cue['text']}")
        chunk_path = work_dir / f"chunk_{idx:02d}.txt"
        chunk_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        paths.append(str(chunk_path))
    return paths


def cmd_prepare(args: argparse.Namespace) -> None:
    work_dir = Path(args.out).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    src = args.source

    heatmap: list[dict[str, Any]] = []
    chapters: list[dict[str, Any]] = []
    fps = 30.0
    duration = 0.0
    media_path: Path | None = None

    if _is_url(src):
        info = _prepare_url(src, work_dir, args)
        title = info["title"]
        duration = info["duration"]
        fps = info["fps"]
        heatmap = info["heatmap"]
        chapters = info["chapters"]
        cues = info["cues"]
        media_path = info["media_path"]
        canonical_source = src
    else:
        src_path = Path(src).resolve()
        if not src_path.exists():
            _die(f"Source file not found: {src}")
        canonical_source = str(src_path)
        title = src_path.stem
        if src_path.suffix.lower() in TRANSCRIPT_EXTS:
            cues, tdur = load_transcript_file(src_path)
            duration = tdur or (cues[-1]["end"] if cues else 0.0)
        else:
            media_path = src_path
            fps = _probe_fps(src_path)
            if args.transcript:
                cues, tdur = load_transcript_file(Path(args.transcript).resolve())
                duration = tdur or (cues[-1]["end"] if cues else 0.0)
            else:
                sibling = next(
                    (src_path.with_suffix(ext) for ext in (".srt", ".vtt", ".json") if src_path.with_suffix(ext).exists()),
                    None,
                )
                if sibling and not args.force_whisper:
                    cues, tdur = load_transcript_file(sibling)
                    duration = tdur or (cues[-1]["end"] if cues else 0.0)
                else:
                    cues = _run_faster_whisper(src_path, args.lang, args.whisper_model)
                    duration = cues[-1]["end"] if cues else 0.0

    if not duration and cues:
        duration = cues[-1]["end"]

    loud_seconds = _extract_loud_seconds(media_path) if media_path else set()
    sig_counts = annotate_signals(cues, loud_seconds, heatmap)
    chunks = write_chunks(cues, work_dir, duration, args.window_mins, args.overlap_mins)

    cues_doc = {
        "source": canonical_source,
        "title": title,
        "duration": round(duration, 3),
        "fps": fps,
        "chapters": chapters,
        "cues": cues,
    }
    (work_dir / "cues.json").write_text(json.dumps(cues_doc, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {
        "work_dir": str(work_dir),
        "title": title,
        "duration_sec": round(duration, 2),
        "cues_count": len(cues),
        "chunks": chunks,
        "signals_summary": sig_counts,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def _clamp_axis(val: Any) -> int:
    try:
        num = int(round(float(val)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(25, num))


def _build_fcpxml(
    source: str,
    title: str,
    duration: float,
    fps: float,
    chrono_clips: list[dict[str, Any]],
) -> str:
    fps_int = max(1, int(round(fps)))
    src_path = Path(source)
    if not _is_url(source) and src_path.exists():
        media_uri = src_path.resolve().as_uri()
    elif _is_url(source):
        media_uri = source
    else:
        media_uri = "https://example.invalid/source.mp4"

    dur_str = _fcpxml_time(max(duration, chrono_clips[-1]["end"] if chrono_clips else 1.0), fps_int)
    frame_dur = f"1/{fps_int}s"

    root = ET.Element("fcpxml", version="1.10")
    resources = ET.SubElement(root, "resources")
    ET.SubElement(resources, "format", id="r1", name=f"FFVideoFormat1080p{fps_int}", frameDuration=frame_dur, width="1920", height="1080")
    ET.SubElement(
        resources, "asset", id="r2", name=title, src=media_uri,
        start="0s", duration=dur_str, hasVideo="1", hasAudio="1", format="r1",
    )

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="Viral Clip Scout")

    # Project 1: full source with range markers for each viral moment.
    p_markers = ET.SubElement(event, "project", name=f"{title} - Scout Markers")
    seq_m = ET.SubElement(p_markers, "sequence", format="r1", duration=dur_str)
    spine_m = ET.SubElement(seq_m, "spine")
    full_clip = ET.SubElement(spine_m, "asset-clip", name=title, ref="r2", offset="0s", start="0s", duration=dur_str)
    for c in chrono_clips:
        note = f"[{c['total_score']}/100 | #{c['rank']}] Hook: {c['hook']} | Why: {c['why']}"
        ET.SubElement(
            full_clip, "marker",
            start=_fcpxml_time(c["start"], fps_int),
            duration=_fcpxml_time(c["duration"], fps_int),
            value=c["title"],
            note=note,
        )

    # Project 2: selects timeline containing only kept clips back-to-back.
    selects_total = sum(c["duration"] for c in chrono_clips)
    p_selects = ET.SubElement(event, "project", name=f"{title} - Scout Selects")
    seq_s = ET.SubElement(p_selects, "sequence", format="r1", duration=_fcpxml_time(max(1.0, selects_total), fps_int))
    spine_s = ET.SubElement(seq_s, "spine")
    offset_acc = 0.0
    for c in chrono_clips:
        clip_el = ET.SubElement(
            spine_s, "asset-clip",
            name=f"#{c['rank']:02d} {c['title']}",
            ref="r2",
            offset=_fcpxml_time(offset_acc, fps_int),
            start=_fcpxml_time(c["start"], fps_int),
            duration=_fcpxml_time(c["duration"], fps_int),
        )
        ET.SubElement(
            clip_el, "marker",
            start=_fcpxml_time(c["start"], fps_int),
            duration="1s",
            value=f"{c['total_score']}/100",
            note=c.get("edit_notes") or c["hook"],
        )
        offset_acc += c["duration"]

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _build_edl(title: str, fps: float, chrono_clips: list[dict[str, Any]]) -> str:
    lines = [f"TITLE: {title} - Viral Clip Scout", "FCM: NON-DROP FRAME", ""]
    rec_cursor = 0.0
    for idx, c in enumerate(chrono_clips, 1):
        rec_end = rec_cursor + c["duration"]
        src_in = _fmt_smpte(c["start"], fps)
        src_out = _fmt_smpte(c["end"], fps)
        rec_in = _fmt_smpte(rec_cursor, fps)
        rec_out = _fmt_smpte(rec_end, fps)
        lines.append(f"{idx:03d}  AX       V     C        {src_in} {src_out} {rec_in} {rec_out}")
        lines.append(f"* FROM CLIP NAME: {c['title']}")
        lines.append(f"* COMMENT: [RANK {c['rank']} | {c['total_score']}/100] {c['hook']} -- {c['why']}")
        lines.append("")
        rec_cursor = rec_end
    return "\n".join(lines)


def _clip_srt_and_words(
    cues: list[dict[str, Any]],
    start: float,
    end: float,
) -> tuple[str, list[dict[str, Any]]]:
    srt_blocks: list[str] = []
    words_out: list[dict[str, Any]] = []
    idx = 1
    for cue in cues:
        if cue["end"] <= start or cue["start"] >= end:
            continue
        cs = max(0.0, cue["start"] - start)
        ce = min(end - start, cue["end"] - start)
        if ce > cs:
            srt_blocks.append(f"{idx}\n{_fmt_srt(cs)} --> {_fmt_srt(ce)}\n{cue['text']}\n")
            idx += 1
        for w in cue.get("words") or []:
            if w["end"] > start and w["start"] < end:
                words_out.append({
                    "word": w["word"],
                    "start": round(max(0.0, w["start"] - start), 3),
                    "end": round(min(end - start, w["end"] - start), 3),
                })
    return "\n".join(srt_blocks), words_out


def cmd_finalize(args: argparse.Namespace) -> None:
    work_dir = Path(args.work_dir).resolve()
    cues_path = work_dir / "cues.json"
    if not cues_path.exists():
        _die(f"cues.json not found in {work_dir}. Run `prepare` first.")
    cues_doc = json.loads(cues_path.read_text(encoding="utf-8-sig"))
    cues: list[dict[str, Any]] = cues_doc.get("cues") or []
    by_id = {int(c["id"]): c for c in cues}
    ordered_ids = [int(c["id"]) for c in cues]
    id_pos = {cid: i for i, cid in enumerate(ordered_ids)}

    cand_raw = json.loads(Path(args.candidates).resolve().read_text(encoding="utf-8-sig"))
    candidates = cand_raw.get("candidates", []) if isinstance(cand_raw, dict) else cand_raw
    if not isinstance(candidates, list):
        _die("candidates JSON must be a list or an object with a `candidates` list.")

    duration = float(cues_doc.get("duration") or (cues[-1]["end"] if cues else 0.0))
    fps = float(cues_doc.get("fps") or 30.0)
    source = str(cues_doc.get("source") or "")
    title = str(cues_doc.get("title") or "Untitled")

    passed: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for item in candidates:
        try:
            sid = int(item["start_id"])
            eid = int(item["end_id"])
        except (KeyError, TypeError, ValueError):
            rejected.append({"candidate": item, "reason": "invalid start_id/end_id"})
            continue

        if sid not in by_id or eid not in by_id or id_pos[sid] > id_pos[eid]:
            rejected.append({"candidate": item, "reason": f"cue range {sid}..{eid} not found or reversed"})
            continue

        scue, ecue = by_id[sid], by_id[eid]
        s_words = scue.get("words") or []
        e_words = ecue.get("words") or []
        raw_start = float(s_words[0]["start"]) if s_words else float(scue["start"])
        raw_end = float(e_words[-1]["end"]) if e_words else float(ecue["end"])

        prev_bound = cues[id_pos[sid] - 1]["end"] if id_pos[sid] > 0 else 0.0
        next_bound = cues[id_pos[eid] + 1]["start"] if id_pos[eid] + 1 < len(cues) else duration
        pad_start = max(0.0, raw_start - args.pad_start, min(raw_start, prev_bound))
        pad_end = min(duration if duration > 0 else raw_end + args.pad_end, raw_end + args.pad_end, max(raw_end, next_bound))
        clip_dur = round(pad_end - pad_start, 3)

        if clip_dur < args.min_sec or clip_dur > args.max_sec:
            rejected.append({
                "start_id": sid, "end_id": eid, "title": item.get("title", ""),
                "reason": f"duration {clip_dur:.1f}s outside [{args.min_sec:g}, {args.max_sec:g}]s",
            })
            continue

        raw_scores = item.get("scores") or {}
        scores = {k: _clamp_axis(raw_scores.get(k, 0)) for k in ("hook", "standalone", "value", "payoff")}
        total = sum(scores.values())
        min_axis_val = min(scores.values())

        if total < args.min_score or min_axis_val < args.min_axis:
            rejected.append({
                "start_id": sid, "end_id": eid, "title": item.get("title", ""),
                "scores": scores, "total_score": total,
                "reason": f"below threshold (total={total} < {args.min_score} or min_axis={min_axis_val} < {args.min_axis})",
            })
            continue

        passed.append({
            "start_id": sid,
            "end_id": eid,
            "start": round(pad_start, 3),
            "end": round(pad_end, 3),
            "duration": clip_dur,
            "scores": scores,
            "total_score": total,
            "title": str(item.get("title") or f"Clip {sid}-{eid}").strip(),
            "hook": str(item.get("hook") or "").strip(),
            "why": str(item.get("why") or "").strip(),
            "edit_notes": str(item.get("edit_notes") or "").strip(),
        })

    # Rank best-first and drop overlapping lower-ranked picks.
    passed.sort(key=lambda c: (-c["total_score"], -c["scores"]["hook"], c["start"]))
    kept: list[dict[str, Any]] = []
    for cand in passed:
        dup_of = None
        for prev in kept:
            inter = max(0.0, min(cand["end"], prev["end"]) - max(cand["start"], prev["start"]))
            shorter = max(0.001, min(cand["duration"], prev["duration"]))
            if (inter / shorter) > args.overlap_ratio:
                dup_of = (prev["rank"], inter / shorter)
                break
        if dup_of is not None:
            rejected.append({
                "start_id": cand["start_id"], "end_id": cand["end_id"], "title": cand["title"],
                "total_score": cand["total_score"],
                "reason": f"overlaps rank #{dup_of[0]} by {dup_of[1]:.0%}",
            })
            continue
        cand["rank"] = len(kept) + 1
        kept.append(cand)

    exports_dir = work_dir / "exports"
    subs_dir = exports_dir / "subtitles"
    exports_dir.mkdir(parents=True, exist_ok=True)
    subs_dir.mkdir(parents=True, exist_ok=True)
    for old_srt in subs_dir.glob("*.srt"):
        old_srt.unlink()

    chrono = sorted(kept, key=lambda c: c["start"])
    cut_cmds: list[list[str]] = []
    cut_cmd_lines: list[str] = []
    src_in_arg = source if (not _is_url(source) and Path(source).exists()) else "<INPUT_VIDEO_PATH>"

    for idx, c in enumerate(chrono, 1):
        srt_text, words_slice = _clip_srt_and_words(cues, c["start"], c["end"])
        c["words"] = words_slice
        c["start_tc"] = _fmt_smpte(c["start"], fps)
        c["end_tc"] = _fmt_smpte(c["end"], fps)

        base_name = f"clip_{idx:02d}_{_slug(c['title'])}"
        srt_path = subs_dir / f"{base_name}.srt"
        srt_path.write_text(srt_text, encoding="utf-8")
        c["srt_file"] = str(srt_path)

        out_mp4 = exports_dir / "clips" / f"{base_name}.mp4"
        cmd_list = [
            "ffmpeg", "-y", "-ss", f"{c['start']:.3f}", "-to", f"{c['end']:.3f}",
            "-i", src_in_arg, "-c", "copy", "-avoid_negative_ts", "make_zero", str(out_mp4),
        ]
        cut_cmds.append(cmd_list)
        cut_cmd_lines.append(" ".join(f'"{a}"' if " " in a else a for a in cmd_list))

    highlights_path = exports_dir / "highlights.json"
    highlights_doc = {
        "source": source,
        "title": title,
        "duration": round(duration, 3),
        "fps": fps,
        "thresholds": {
            "min_score": args.min_score,
            "min_axis": args.min_axis,
            "min_sec": args.min_sec,
            "max_sec": args.max_sec,
            "overlap_ratio": args.overlap_ratio,
        },
        "kept_count": len(kept),
        "rejected_count": len(rejected),
        "kept": kept,
        "rejected": rejected,
    }
    highlights_path.write_text(json.dumps(highlights_doc, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_path = exports_dir / "markers.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "rank", "start_tc", "end_tc", "start_sec", "end_sec", "duration_sec",
            "total_score", "hook_score", "standalone_score", "value_score", "payoff_score",
            "title", "hook", "why", "edit_notes",
        ])
        for c in chrono:
            sc = c["scores"]
            writer.writerow([
                c["rank"], c["start_tc"], c["end_tc"], c["start"], c["end"], c["duration"],
                c["total_score"], sc["hook"], sc["standalone"], sc["value"], sc["payoff"],
                c["title"], c["hook"], c["why"], c["edit_notes"],
            ])

    edl_path = exports_dir / "markers.edl"
    edl_path.write_text(_build_edl(title, fps, chrono), encoding="utf-8")

    fcpxml_path = exports_dir / "timeline.fcpxml"
    fcpxml_path.write_text(_build_fcpxml(source, title, duration, fps, chrono), encoding="utf-8")

    cuts_txt_path = exports_dir / "cut_commands.txt"
    cuts_txt_path.write_text("\n".join(cut_cmd_lines) + ("\n" if cut_cmd_lines else ""), encoding="utf-8")

    cut_files: list[str] = []
    if args.cut_streams and cut_cmds:
        if not _is_url(source) and Path(source).exists() and shutil.which("ffmpeg"):
            (exports_dir / "clips").mkdir(parents=True, exist_ok=True)
            for cmd in cut_cmds:
                subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
                cut_files.append(cmd[-1])

    out_files = {
        "highlights_json": str(highlights_path),
        "markers_csv": str(csv_path),
        "markers_edl": str(edl_path),
        "timeline_fcpxml": str(fcpxml_path),
        "cut_commands_txt": str(cuts_txt_path),
        "subtitles_dir": str(subs_dir),
    }
    if cut_files:
        out_files["cut_clips"] = cut_files

    print(json.dumps({
        "kept_count": len(kept),
        "rejected_count": len(rejected),
        "exports_dir": str(exports_dir),
        "files": out_files,
    }, indent=2, ensure_ascii=False))


def _write_test_wav(path: Path, loud_at_sec: int, total_secs: int = 12, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        for s in range(total_secs):
            amp = 18000 if s == loud_at_sec else 1800
            chunk = array.array("h", [int(amp * math.sin(2 * math.pi * 440 * i / rate)) for i in range(rate)])
            if sys.byteorder != "little":
                chunk.byteswap()
            wf.writeframes(chunk.tobytes())


def cmd_selftest(_args: argparse.Namespace) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # 1. SRT + VTT rolling-caption deduplication + Whisper JSON with words
        srt_p = root / "sample.srt"
        srt_p.write_text(
            "1\n00:00:01,000 --> 00:00:03,500\n<i>First</i> line\n\n"
            "2\n00:00:06.000 --> 00:00:08.000\nAfter pause\n",
            encoding="utf-8",
        )
        srt_cues = parse_srt_or_vtt(srt_p)
        assert len(srt_cues) == 2 and srt_cues[0]["text"] == "First line"

        vtt_p = root / "sample.vtt"
        vtt_p.write_text(
            "WEBVTT\nKind: captions\n\n"
            "00:00:01.000 --> 00:00:03.000 align:start position:0%\nhello <00:00:01.500><c>world</c>\n\n"
            "00:00:03.000 --> 00:00:05.000\nhello world\nnext line here\n",
            encoding="utf-8",
        )
        vtt_cues = parse_srt_or_vtt(vtt_p)
        assert len(vtt_cues) == 2
        assert vtt_cues[0]["text"] == "hello world"
        assert vtt_cues[1]["text"] == "next line here"

        # 2. Pure-stdlib RMS burst detection
        wav_p = root / "burst.wav"
        _write_test_wav(wav_p, loud_at_sec=6, total_secs=10)
        loud = compute_wav_loud_seconds(wav_p)
        assert 6 in loud and 1 not in loud

        # 3. Whisper JSON + prepare chunking with overlap
        wjson = root / "talk.json"
        segs = []
        for idx in range(25):
            st = idx * 4.0
            en = st + 3.2
            segs.append({
                "start": st, "end": en,
                "text": f"Sentence number {idx + 1} with concrete proof.",
                "words": [{"word": "Sentence", "start": st, "end": st + 0.4}, {"word": "proof.", "start": en - 0.5, "end": en}],
            })
        wjson.write_text(json.dumps({"duration": 100.0, "segments": segs}), encoding="utf-8")

        work = root / "work"
        prep_args = argparse.Namespace(
            source=str(wjson), out=str(work), transcript=None, lang="auto",
            whisper_model="small", window_mins=1.0, overlap_mins=0.2, force_whisper=False,
        )
        cmd_prepare(prep_args)
        chunk_files = sorted(work.glob("chunk_*.txt"))
        assert len(chunk_files) >= 2
        assert "1|00:00|Sentence number 1" in chunk_files[0].read_text(encoding="utf-8")

        # 4. Finalize filtering: min_axis gate, min_score gate, overlap dedup, and 0-clip mode
        cands = [
            {"start_id": 1, "end_id": 6, "title": "Strong Hook Clip", "hook": "Stop doing this", "why": "Clear insight",
             "scores": {"hook": 22, "standalone": 20, "value": 21, "payoff": 19}},  # 82 -> keep rank 1
            {"start_id": 2, "end_id": 7, "title": "Overlap Lower", "hook": "Dup hook", "why": "Overlaps rank 1",
             "scores": {"hook": 20, "standalone": 20, "value": 20, "payoff": 19}},  # 79 -> overlap drop
            {"start_id": 10, "end_id": 15, "title": "Missing Context", "hook": "Crazy hook", "why": "Needs context",
             "scores": {"hook": 25, "standalone": 10, "value": 25, "payoff": 20}},  # 80 but axis=10 -> reject!
            {"start_id": 18, "end_id": 23, "title": "Weak Score", "hook": "Meh", "why": "Flat",
             "scores": {"hook": 18, "standalone": 18, "value": 18, "payoff": 18}},  # 72 < 78 -> reject!
        ]
        cand_p = work / "candidates.json"
        cand_p.write_text(json.dumps({"candidates": cands}), encoding="utf-8")
        fin_args = argparse.Namespace(
            work_dir=str(work), candidates=str(cand_p), min_score=78, min_axis=15,
            min_sec=15.0, max_sec=75.0, overlap_ratio=0.4, pad_start=0.15, pad_end=0.25, cut_streams=False,
        )
        cmd_finalize(fin_args)

        hl = json.loads((work / "exports" / "highlights.json").read_text(encoding="utf-8"))
        assert hl["kept_count"] == 1 and hl["rejected_count"] == 3
        assert hl["kept"][0]["title"] == "Strong Hook Clip"
        fcpxml_root = ET.fromstring((work / "exports" / "timeline.fcpxml").read_text(encoding="utf-8"))
        assert fcpxml_root.tag == "fcpxml"
        edl_txt = (work / "exports" / "markers.edl").read_text(encoding="utf-8")
        assert "001  AX" in edl_txt
        srt_out = next((work / "exports" / "subtitles").glob("clip_01_*.srt")).read_text(encoding="utf-8")
        assert "00:00:00,000 -->" in srt_out

        # 5. Zero-clip case: must succeed cleanly with 0 kept clips (no padding)
        zero_work = root / "zero_work"
        cmd_prepare(argparse.Namespace(
            source=str(wjson), out=str(zero_work), transcript=None, lang="auto",
            whisper_model="small", window_mins=45.0, overlap_mins=3.0, force_whisper=False,
        ))
        zero_cand = zero_work / "candidates.json"
        zero_cand.write_text(json.dumps([cands[3]]), encoding="utf-8")
        cmd_finalize(argparse.Namespace(
            work_dir=str(zero_work), candidates=str(zero_cand), min_score=78, min_axis=15,
            min_sec=15.0, max_sec=75.0, overlap_ratio=0.4, pad_start=0.15, pad_end=0.25, cut_streams=False,
        ))
        zero_hl = json.loads((zero_work / "exports" / "highlights.json").read_text(encoding="utf-8"))
        assert zero_hl["kept_count"] == 0 and zero_hl["kept"] == []

        # 6. Extended Shorts duration check: ~87.45s clip passes default max_sec=180.0, fails max_sec=75.0
        ext_work = root / "ext_work"
        cmd_prepare(argparse.Namespace(
            source=str(wjson), out=str(ext_work), transcript=None, lang="auto",
            whisper_model="small", window_mins=45.0, overlap_mins=3.0, force_whisper=False,
        ))
        ext_cand = ext_work / "candidates.json"
        ext_cand.write_text(json.dumps({
            "candidates": [{
                "start_id": 1, "end_id": 22, "title": "Extended Arc Clip",
                "hook": "Watch until the finale", "why": "Full multi-beat payoff",
                "scores": {"hook": 22, "standalone": 21, "value": 22, "payoff": 22},
            }]
        }), encoding="utf-8")
        cmd_finalize(argparse.Namespace(
            work_dir=str(ext_work), candidates=str(ext_cand), min_score=78, min_axis=15,
            min_sec=15.0, max_sec=180.0, overlap_ratio=0.4, pad_start=0.15, pad_end=0.25, cut_streams=False,
        ))
        ext_hl = json.loads((ext_work / "exports" / "highlights.json").read_text(encoding="utf-8"))
        assert ext_hl["kept_count"] == 1 and ext_hl["kept"][0]["duration"] > 75.0

        cmd_finalize(argparse.Namespace(
            work_dir=str(ext_work), candidates=str(ext_cand), min_score=78, min_axis=15,
            min_sec=15.0, max_sec=75.0, overlap_ratio=0.4, pad_start=0.15, pad_end=0.25, cut_streams=False,
        ))
        capped_hl = json.loads((ext_work / "exports" / "highlights.json").read_text(encoding="utf-8"))
        assert capped_hl["kept_count"] == 0 and "outside [15, 75]s" in capped_hl["rejected"][0]["reason"]

    print(json.dumps({"selftest": "passed", "checks": 6}))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Viral Clip Scout: zero-render highlight finder & NLE exporter.")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prepare", help="Extract transcript cues, acoustic/heatmap signals, and chunks.")
    p_prep.add_argument("source", help="Video/audio file, URL, or .srt/.vtt/.json transcript")
    p_prep.add_argument("--out", required=True, help="Working directory for cues.json and chunk_*.txt")
    p_prep.add_argument("--transcript", help="Optional explicit transcript (.srt/.vtt/.json)")
    p_prep.add_argument("--lang", default="auto", help="Subtitle/ASR language code (default: auto)")
    p_prep.add_argument("--whisper-model", default="small", help="faster-whisper model size (default: small)")
    p_prep.add_argument("--window-mins", type=float, default=45.0, help="Chunk window length in minutes")
    p_prep.add_argument("--overlap-mins", type=float, default=3.0, help="Overlap between chunks in minutes")
    p_prep.add_argument("--force-whisper", action="store_true", help="Ignore existing subtitles and transcribe audio")
    p_prep.set_defaults(func=cmd_prepare)

    p_fin = sub.add_parser("finalize", help="Filter candidates by hard thresholds and export NLE files.")
    p_fin.add_argument("work_dir", help="Working directory created by `prepare`")
    p_fin.add_argument("--candidates", required=True, help="Path to scored candidates JSON")
    p_fin.add_argument("--min-score", type=int, default=78, help="Minimum total score /100 (default: 78)")
    p_fin.add_argument("--min-axis", type=int, default=15, help="Minimum score per axis /25 (default: 15)")
    p_fin.add_argument("--min-sec", type=float, default=15.0, help="Minimum clip duration in seconds")
    p_fin.add_argument("--max-sec", type=float, default=180.0, help="Maximum clip duration in seconds (default: 180 for YouTube Shorts up to 3 min)")
    p_fin.add_argument("--overlap-ratio", type=float, default=0.4, help="Max allowed overlap ratio between kept clips")
    p_fin.add_argument("--pad-start", type=float, default=0.15, help="Pre-speech padding in seconds")
    p_fin.add_argument("--pad-end", type=float, default=0.25, help="Post-speech padding in seconds")
    p_fin.add_argument("--cut-streams", action="store_true", help="Run lossless ffmpeg -c copy for local media")
    p_fin.set_defaults(func=cmd_finalize)

    p_test = sub.add_parser("selftest", help="Run self-contained tests in a temporary directory.")
    p_test.set_defaults(func=cmd_selftest)
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
