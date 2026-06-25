#!/usr/bin/env python3
"""
Phase 2 — edge-tts (step 4 + timing for step 7)

  4. Dual narrators — Emily primary, Andrew every 4th scene
  7. Per-scene audio + word_timings.json for karaoke captions + captions.srt
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_tts

from captions import EMILY, ANDREW, estimate_word_timings, merge_srt_blocks, pick_narrator_voice, resolve_voice
from common import CONFIG, clean_script_for_tts, load_json, save_json, split_script_for_scenes

DEFAULT_VOICES = [EMILY, ANDREW]
MAX_TTS_RETRIES = 4
EMPTY_SCENE_SEC = 0.35


def write_silent_mp3(dest: Path, duration: float = EMPTY_SCENE_SEC) -> None:
    """Placeholder audio so concat length matches scene_durations.json."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
            "-t", str(duration), "-c:a", "libmp3lame", "-q:a", "9", str(dest),
        ],
        check=True,
        capture_output=True,
    )


async def synthesize_with_captions(
    text: str, voice: str, rate: str, dest: Path
) -> tuple[str, list[dict[str, Any]]]:
    """Synthesize MP3; return SRT block + word timings for karaoke overlay."""
    if not text.strip():
        write_silent_mp3(dest, EMPTY_SCENE_SEC)
        return "", []

    voice = resolve_voice(voice)
    last_err: Exception | None = None

    for attempt in range(MAX_TTS_RETRIES):
        communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
        submaker = edge_tts.SubMaker()
        words: list[dict[str, Any]] = []
        try:
            with dest.open("wb") as audio_file:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_file.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        submaker.feed(chunk)
                        start = chunk["offset"] / 10_000_000
                        duration = chunk["duration"] / 10_000_000
                        words.append(
                            {
                                "text": chunk["text"],
                                "start": round(start, 4),
                                "end": round(start + duration, 4),
                            }
                        )
            if dest.stat().st_size == 0:
                raise edge_tts.exceptions.NoAudioReceived("TTS produced empty audio file")
            return submaker.get_srt(), words
        except edge_tts.exceptions.NoAudioReceived as exc:
            last_err = exc
            dest.unlink(missing_ok=True)
            if attempt + 1 < MAX_TTS_RETRIES:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception as exc:
            dest.unlink(missing_ok=True)
            last_err = exc
            transient = any(
                s in str(exc).lower()
                for s in ("timeout", "connect", "network", "503", "502", "429")
            )
            if transient and attempt + 1 < MAX_TTS_RETRIES:
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            raise

    raise last_err or RuntimeError("TTS failed")


def concat_audio(parts: list[Path], output: Path) -> None:
    if not parts:
        raise ValueError("No audio segments to concatenate")
    missing = [p for p in parts if not p.exists() or p.stat().st_size == 0]
    if missing:
        raise ValueError(f"Missing or empty audio segments: {missing}")
    list_file = output.parent / "_concat_list.txt"
    with list_file.open("w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p.resolve().as_posix()}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output)],
        check=True,
        capture_output=True,
    )
    list_file.unlink(missing_ok=True)


def probe_duration(path: Path) -> float:
    if not path.exists() or path.stat().st_size == 0:
        return 0.5
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return max(0.5, float(result.stdout.strip()))


async def run_phase(
    input_dir: Path,
    output_dir: Path,
    voices: list[str],
    rate: str,
) -> None:
    script = clean_script_for_tts((input_dir / "script.txt").read_text(encoding="utf-8"))
    scenes_meta = load_json(input_dir / "scenes.json")
    if not script or not scenes_meta:
        raise ValueError("Need script.txt and scenes.json")

    segments_path = input_dir / "script_segments.json"
    if segments_path.exists():
        segments_data = load_json(segments_path)
        segments = [clean_script_for_tts(s.get("text", "")) for s in segments_data]
    else:
        segments = [clean_script_for_tts(t) for t in split_script_for_scenes(script, len(scenes_meta))]

    if len(segments) != len(scenes_meta):
        segments = [clean_script_for_tts(t) for t in split_script_for_scenes(script, len(scenes_meta))]

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "script_clean.txt").write_text(script, encoding="utf-8")

    narration = output_dir / "narration.mp3"
    durations: list[dict] = []
    part_files: list[Path] = []
    srt_blocks: list[str] = []
    offsets: list[float] = []
    word_timings: list[dict] = []
    clock = 0.0

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for i, item in enumerate(scenes_meta):
            sid = int(item["scene_id"])
            text = segments[i] if i < len(segments) else ""
            voice = pick_narrator_voice(i, voices, text)
            part = tmp_path / f"scene_{sid:02d}.mp3"
            srt, words = await synthesize_with_captions(text, voice, rate, part)
            dur = probe_duration(part)
            if text.strip() and not words:
                words = estimate_word_timings(text, dur)
            durations.append(
                {
                    "scene_id": sid,
                    "duration_sec": round(dur, 3),
                    "file": f"scene_{sid:02d}.png",
                    "voice": voice,
                }
            )
            word_timings.append({"scene_id": sid, "voice": voice, "words": words})
            part_files.append(part)
            srt_blocks.append(srt)
            offsets.append(clock)
            clock += dur

        concat_audio(part_files, narration)

    save_json(output_dir / "scene_durations.json", durations)
    save_json(output_dir / "word_timings.json", word_timings)
    srt_full = merge_srt_blocks(srt_blocks, offsets)
    (output_dir / "captions.srt").write_text(srt_full, encoding="utf-8")

    save_json(
        output_dir / "script_segments.json",
        [{"scene_id": int(s["scene_id"]), "text": segments[i] if i < len(segments) else ""}
         for i, s in enumerate(scenes_meta)],
    )

    meta = load_json(input_dir / "metadata.json") if (input_dir / "metadata.json").exists() else {}
    meta["total_audio_sec"] = round(sum(d["duration_sec"] for d in durations), 3)
    meta["tts_voices"] = voices
    target = meta.get("duration_minutes", 0) * 60
    if target:
        meta["duration_drift_sec"] = round(meta["total_audio_sec"] - target, 1)
    save_json(output_dir / "metadata.json", meta)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2: edge-tts")
    parser.add_argument("--input", type=Path, default=Path("output"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--pipeline", type=Path, default=CONFIG / "pipeline.json")
    parser.add_argument("--rate", default=None)
    args = parser.parse_args()

    pipeline = load_json(args.pipeline) if args.pipeline.exists() else {}
    voices = pipeline.get("tts_voices") or DEFAULT_VOICES
    if isinstance(voices, str):
        voices = [voices]
    voices = [resolve_voice(v) for v in voices]
    rate = os.environ.get("TTS_RATE") or pipeline.get("tts_rate", "-5%")

    try:
        asyncio.run(run_phase(args.input, args.output, voices, rate))
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    print(f"Wrote narration.mp3 + word_timings.json + captions.srt -> {args.output}")


if __name__ == "__main__":
    main()
