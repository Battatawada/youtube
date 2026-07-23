"""Azure Cognitive Services Speech TTS with SSML styles and word boundaries."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

from tts_narration import TtsChunk, voice_supports_express_as

try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:  # pragma: no cover
    speechsdk = None  # type: ignore[assignment]


class AzureTtsError(RuntimeError):
    pass


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _prosody_attr(value: str, attr: str) -> str:
    if not value or value == "default":
        return ""
    return f' {attr}="{value}"'


def build_ssml(
    chunks: list[TtsChunk],
    *,
    default_voice: str,
    style_degree: float = 0.9,
    base_rate: str = "default",
) -> str:
    """Build SSML for a list of chunks (one scene or merged segment)."""
    body_parts: list[str] = []
    for chunk in chunks:
        voice = chunk.voice or default_voice
        text = _xml_escape(chunk.text.strip())
        if not text:
            continue

        prosody_open = "<prosody"
        prosody_open += _prosody_attr(base_rate if chunk.rate == "default" else chunk.rate, "rate")
        prosody_open += _prosody_attr(chunk.pitch, "pitch")
        prosody_open += _prosody_attr(chunk.volume, "volume")
        prosody_open += ">"

        inner = f"{prosody_open}{text}</prosody>"

        if chunk.style and voice_supports_express_as(voice):
            degree = max(0.01, min(2.0, style_degree))
            inner = (
                f'<mstts:express-as style="{chunk.style}" styledegree="{degree:.2f}">'
                f"{inner}</mstts:express-as>"
            )

        body_parts.append(f'<voice name="{voice}">{inner}</voice>')
        if chunk.pause_after_ms > 0:
            body_parts.append(f'<break time="{chunk.pause_after_ms}ms"/>')

    if not body_parts:
        return ""

    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">'
        + "".join(body_parts)
        + "</speak>"
    )


def _tick_to_seconds(ticks: int) -> float:
    return ticks / 10_000_000


def synthesize_ssml(
    ssml: str,
    *,
    region: str | None = None,
    key: str | None = None,
    output_format: str = "mp3",
) -> tuple[bytes, list[dict[str, Any]]]:
    """Synthesize SSML to audio bytes and word boundary timings."""
    if speechsdk is None:
        raise AzureTtsError("azure-cognitiveservices-speech is not installed")

    key = key or os.environ.get("AZURE_SPEECH_KEY", "")
    region = region or os.environ.get("AZURE_SPEECH_REGION", "")
    if not key or not region:
        raise AzureTtsError("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION must be set")

    speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    if output_format == "mp3":
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
        )

    words: list[dict[str, Any]] = []

    def on_word_boundary(evt: speechsdk.SpeechSynthesisWordBoundaryEventArgs) -> None:
        raw = evt.text or ""
        token = raw.strip()
        if not token:
            return
        start = _tick_to_seconds(evt.audio_offset)
        duration = _tick_to_seconds(evt.duration)
        words.append(
            {
                "text": token,
                "start": round(start, 4),
                "end": round(start + duration, 4),
            }
        )

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


def synthesize_chunks_to_file(
    chunks: list[TtsChunk],
    dest: Path,
    *,
    default_voice: str,
    style_degree: float = 0.9,
    base_rate: str = "default",
    region: str | None = None,
    key: str | None = None,
) -> list[dict[str, Any]]:
    """Synthesize chunks to an MP3 file; return word timings."""
    ssml = build_ssml(
        chunks,
        default_voice=default_voice,
        style_degree=style_degree,
        base_rate=base_rate,
    )
    if not ssml:
        dest.write_bytes(b"")
        return []

    audio, words = synthesize_ssml(ssml, region=region, key=key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(audio)
    return words


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


def write_temp_mp3_from_ssml(ssml: str) -> Path:
    """Helper for tests — write SSML output to a temp file."""
    audio, _ = synthesize_ssml(ssml)
    tmp = Path(tempfile.mkstemp(suffix=".mp3")[1])
    tmp.write_bytes(audio)
    return tmp


def strip_ssml_tags(ssml: str) -> str:
    return re.sub(r"<[^>]+>", "", ssml)
