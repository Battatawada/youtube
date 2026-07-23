"""Azure Cognitive Services Speech TTS — one SSML document per chunk."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import xml.sax.saxutils
from pathlib import Path
from typing import Any

from tts_narration import TtsChunk, voice_supports_express_as

try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:  # pragma: no cover
    speechsdk = None  # type: ignore[assignment]

_ROLE_STYLES: dict[str, str] = {
    "narration": "documentary-narration",
    "quote": "serious",
    "authority": "newscast-formal",
    "witness": "empathetic",
    "outro": "friendly",
}


class AzureTtsError(RuntimeError):
    pass


def _escape_ssml(text: str) -> str:
    return xml.sax.saxutils.escape(text)


def _prosody_value(value: str, default: str) -> str:
    if not value or value == "default":
        return default
    return value


def build_ssml(
    chunk: TtsChunk,
    *,
    style_degree: float = 0.9,
    base_rate: str = "-7%",
) -> str:
    """Build valid Azure SSML for a single chunk (breaks stay inside voice)."""
    voice = chunk.voice
    lang_match = re.match(r"([a-z]{2}-[A-Z]{2})", voice)
    lang = lang_match.group(1) if lang_match else "en-US"

    body = _escape_ssml(chunk.text.strip())
    if chunk.pause_after_ms > 0:
        body = f'{body}<break time="{chunk.pause_after_ms}ms"/>'

    rate = _prosody_value(chunk.rate, base_rate)
    pitch = _prosody_value(chunk.pitch, "+0Hz")
    volume = _prosody_value(chunk.volume, "+0%")

    inner = (
        f'<prosody rate="{rate}" pitch="{pitch}" volume="{volume}">'
        f"<s>{body}</s></prosody>"
    )

    style = _ROLE_STYLES.get(chunk.role, "documentary-narration")
    if chunk.style and voice_supports_express_as(voice):
        degree = max(0.01, min(2.0, style_degree))
        inner = (
            f'<mstts:express-as style="{style}" styledegree="{degree:.2f}">'
            f"{inner}</mstts:express-as>"
        )

    return (
        '<speak version="1.0" '
        'xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" '
        f'xml:lang="{lang}">'
        f'<voice name="{voice}">{inner}</voice></speak>'
    )


def _tick_to_seconds(ticks: int) -> float:
    return ticks / 10_000_000


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
    return max(0.05, float(result.stdout.strip()))


def _concat_mp3(parts: list[Path], output: Path) -> None:
    if not parts:
        raise AzureTtsError("No audio parts to concatenate")
    list_file = output.parent / "_azure_concat.txt"
    with list_file.open("w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p.resolve().as_posix()}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output)],
        check=True,
        capture_output=True,
    )
    list_file.unlink(missing_ok=True)


def synthesize_ssml(
    ssml: str,
    *,
    region: str | None = None,
    key: str | None = None,
) -> tuple[bytes, list[dict[str, Any]]]:
    """Synthesize one SSML document to audio bytes + word timings."""
    if speechsdk is None:
        raise AzureTtsError("azure-cognitiveservices-speech is not installed")

    key = key or os.environ.get("AZURE_SPEECH_KEY", "")
    region = region or os.environ.get("AZURE_SPEECH_REGION", "")
    if not key or not region:
        raise AzureTtsError("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION must be set")

    speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio24Khz160KBitRateMonoMp3
    )
    speech_config.set_property(
        speechsdk.PropertyId.SpeechServiceResponse_RequestWordBoundary,
        "true",
    )

    words: list[dict[str, Any]] = []

    def on_word_boundary(evt: speechsdk.SpeechSynthesisWordBoundaryEventArgs) -> None:
        if evt.boundary_type != speechsdk.SpeechSynthesisBoundaryType.Word:
            return
        token = (evt.text or "").strip()
        if not token:
            return
        start = _tick_to_seconds(evt.audio_offset)
        words.append({"text": token, "start": round(start, 4), "end": round(start, 4)})

    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    synthesizer.synthesis_word_boundary.connect(on_word_boundary)

    result = synthesizer.speak_ssml_async(ssml).get()
    if result.reason == speechsdk.ResultReason.Canceled:
        details = result.cancellation_details
        raise AzureTtsError(
            f"Azure TTS canceled: {details.reason} — {details.error_details}"
        )
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        raise AzureTtsError(f"Azure TTS failed: {result.reason}")

    audio = result.audio_data
    if not audio:
        raise AzureTtsError("Azure TTS returned empty audio")

    return audio, words


def synthesize_chunk(
    chunk: TtsChunk,
    dest: Path,
    *,
    style_degree: float = 0.9,
    base_rate: str = "-7%",
    region: str | None = None,
    key: str | None = None,
) -> list[dict[str, Any]]:
    """Synthesize one chunk to MP3; return word timings."""
    if not chunk.text.strip():
        dest.write_bytes(b"")
        return []

    ssml = build_ssml(chunk, style_degree=style_degree, base_rate=base_rate)
    audio, words = synthesize_ssml(ssml, region=region, key=key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(audio)

    dur = probe_duration(dest)
    for i, w in enumerate(words):
        if i + 1 < len(words):
            w["end"] = words[i + 1]["start"]
        else:
            w["end"] = round(max(float(w["start"]) + 0.12, dur), 4)
    return words


def synthesize_chunks_to_file(
    chunks: list[TtsChunk],
    dest: Path,
    *,
    default_voice: str,
    style_degree: float = 0.9,
    base_rate: str = "-7%",
    region: str | None = None,
    key: str | None = None,
) -> list[dict[str, Any]]:
    """Synthesize chunks (one Azure call each) and concat to a single MP3."""
    usable = [c for c in chunks if c.text.strip()]
    if not usable:
        dest.write_bytes(b"")
        return []

    for chunk in usable:
        if not chunk.voice:
            chunk.voice = default_voice

    if len(usable) == 1:
        return synthesize_chunk(
            usable[0],
            dest,
            style_degree=style_degree,
            base_rate=base_rate,
            region=region,
            key=key,
        )

    all_words: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        parts: list[Path] = []
        clock = 0.0
        for i, chunk in enumerate(usable):
            part = tmp_path / f"chunk_{i:03d}.mp3"
            words = synthesize_chunk(
                chunk,
                part,
                style_degree=style_degree,
                base_rate=base_rate,
                region=region,
                key=key,
            )
            parts.append(part)
            for w in words:
                all_words.append(
                    {
                        "text": w["text"],
                        "start": round(float(w["start"]) + clock, 4),
                        "end": round(float(w["end"]) + clock, 4),
                    }
                )
            clock += probe_duration(part)

        _concat_mp3(parts, dest)
    return all_words


def is_quota_or_auth_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        s in msg
        for s in (
            "401",
            "403",
            "unauthorized",
            "quota",
            "exceeded",
            "throttl",
            "429",
            "invalid subscription",
        )
    )


def is_transient_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in ("timeout", "connect", "network", "503", "502", "429", "throttl"))


def strip_ssml_tags(ssml: str) -> str:
    return re.sub(r"<[^>]+>", "", ssml)
