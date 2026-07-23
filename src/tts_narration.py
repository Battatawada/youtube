"""TTS chunk planning and prosody heuristics for Azure SSML narration."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

TENSION_WORDS = frozenset(
    {
        "killed",
        "death",
        "died",
        "body",
        "confession",
        "panic",
        "trauma",
        "abuse",
        "fear",
        "terror",
        "nightmare",
        "suicide",
        "violence",
        "betrayal",
        "shame",
        "guilt",
        "anxiety",
        "depression",
    }
)
TWIST_WORDS = frozenset({"but", "however", "yet", "instead", "except", "although", "though"})
SHORT_SENTENCE_WORDS = 8

ROLE_STYLES: dict[str, str] = {
    "narration": "documentary-narration",
    "quote": "serious",
    "authority": "newscast-formal",
    "witness": "empathetic",
    "outro": "friendly",
}

# Irish/GB voices — prosody only, no mstts:express-as
NO_EXPRESS_AS_PREFIXES = ("en-IE-", "en-GB-")


@dataclass
class TtsChunk:
    text: str
    role: str = "narration"
    voice: str = ""
    rate: str = "default"
    pitch: str = "default"
    volume: str = "default"
    style: str | None = None
    pause_after_ms: int = 120

    def char_count(self) -> int:
        return len(self.text)


def voice_supports_express_as(voice: str) -> bool:
    return not voice.startswith(NO_EXPRESS_AS_PREFIXES)


def _base_prosody(scene_index: int, is_hook_scene: bool) -> dict[str, str]:
    if is_hook_scene:
        return {"rate": "-12%", "pitch": "-2Hz", "volume": "+5%"}
    return {"rate": "default", "pitch": "default", "volume": "default"}


def _sentence_prosody(sentence: str, base: dict[str, str]) -> dict[str, str]:
    words = re.findall(r"\S+", sentence.strip())
    lower = sentence.lower()
    rate = base["rate"]
    pitch = base["pitch"]
    volume = base["volume"]

    if len(words) <= SHORT_SENTENCE_WORDS and len(words) >= 2:
        rate = "+3%" if rate == "default" else rate

    if "?" in sentence:
        pitch = "+2Hz" if pitch == "default" else pitch
        rate = "-5%" if rate == "default" else rate

    if any(w in TENSION_WORDS for w in re.findall(r"[a-z']+", lower)):
        rate = "-8%" if rate == "default" else rate
        pitch = "-1Hz" if pitch == "default" else pitch

    first_word = re.sub(r"[^\w']", "", words[0].lower()) if words else ""
    if first_word in TWIST_WORDS:
        rate = "-6%" if rate == "default" else rate
        volume = "+8%" if volume == "default" else volume

    return {"rate": rate, "pitch": pitch, "volume": volume}


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def _extract_quoted_segments(text: str) -> list[tuple[str, str]]:
    """Return list of (kind, segment) where kind is 'quote' or 'narration'."""
    if not text.strip():
        return []
    out: list[tuple[str, str]] = []
    pattern = re.compile(r'"([^"]+)"')
    last = 0
    for match in pattern.finditer(text):
        before = text[last : match.start()].strip()
        if before:
            out.append(("narration", before))
        quote = match.group(1).strip()
        if quote:
            out.append(("quote", quote))
        last = match.end()
    tail = text[last:].strip()
    if tail:
        out.append(("narration", tail))
    if not out:
        out.append(("narration", text.strip()))
    return out


def _guess_quote_voice(quote: str, pool: dict[str, str]) -> str:
    lower = quote.lower()
    female_hints = (" she ", " her ", " woman ", " mother ", " girl ", " wife ")
    if any(h in f" {lower} " for h in female_hints):
        return pool.get("quote_female", pool.get("narrator", ""))
    return pool.get("quote_male", pool.get("narrator", ""))


def plan_scene_chunks(
    text: str,
    *,
    scene_index: int,
    voice_pool: dict[str, str],
    is_outro: bool = False,
    merge_chunks: bool = True,
) -> list[TtsChunk]:
    """Plan TTS chunks for one scene with role, voice, and prosody."""
    if not text.strip():
        return []

    is_hook = scene_index == 0
    narrator = voice_pool.get("narrator", "")
    chunks: list[TtsChunk] = []

    for kind, segment in _extract_quoted_segments(text):
        if kind == "quote":
            voice = _guess_quote_voice(segment, voice_pool)
            role = "quote"
            style = ROLE_STYLES["quote"] if voice_supports_express_as(voice) else None
            chunks.append(
                TtsChunk(
                    text=segment,
                    role=role,
                    voice=voice,
                    rate="default",
                    pitch="default",
                    volume="default",
                    style=style,
                    pause_after_ms=150,
                )
            )
            continue

        base = _base_prosody(scene_index, is_hook)
        role = "outro" if is_outro else "narration"
        voice = narrator
        style = ROLE_STYLES.get(role) if voice_supports_express_as(voice) else None

        for sentence in _split_sentences(segment):
            prosody = _sentence_prosody(sentence, base)
            chunks.append(
                TtsChunk(
                    text=sentence,
                    role=role,
                    voice=voice,
                    rate=prosody["rate"],
                    pitch=prosody["pitch"],
                    volume=prosody["volume"],
                    style=style,
                    pause_after_ms=120,
                )
            )

    if merge_chunks and len(chunks) > 1:
        chunks = _merge_adjacent_chunks(chunks)
    return chunks


def _merge_adjacent_chunks(chunks: list[TtsChunk]) -> list[TtsChunk]:
    """Merge adjacent narration chunks with same voice/prosody to save Azure quota."""
    if not chunks:
        return []
    merged: list[TtsChunk] = [chunks[0]]
    for chunk in chunks[1:]:
        prev = merged[-1]
        same_role = prev.role == chunk.role == "narration"
        same_voice = prev.voice == chunk.voice
        same_prosody = (
            prev.rate == chunk.rate
            and prev.pitch == chunk.pitch
            and prev.volume == chunk.volume
            and prev.style == chunk.style
        )
        if same_role and same_voice and same_prosody:
            prev.text = f"{prev.text} {chunk.text}"
            prev.pause_after_ms = chunk.pause_after_ms
        else:
            merged.append(chunk)
    return merged


def estimate_character_count(chunks: list[TtsChunk]) -> int:
    return sum(c.char_count() for c in chunks)


def plan_all_scenes(
    segments: list[str],
    *,
    voice_pool: dict[str, str],
    merge_chunks: bool = True,
    end_card_text: str = "",
) -> tuple[list[list[TtsChunk]], int]:
    """Plan chunks for all scenes; return per-scene chunk lists and total char estimate."""
    all_scenes: list[list[TtsChunk]] = []
    total = 0
    for i, text in enumerate(segments):
        scene_chunks = plan_scene_chunks(
            text,
            scene_index=i,
            voice_pool=voice_pool,
            merge_chunks=merge_chunks,
        )
        all_scenes.append(scene_chunks)
        total += estimate_character_count(scene_chunks)

    if end_card_text.strip():
        outro = plan_scene_chunks(
            end_card_text,
            scene_index=len(segments),
            voice_pool=voice_pool,
            is_outro=True,
            merge_chunks=merge_chunks,
        )
        all_scenes.append(outro)
        total += estimate_character_count(outro)

    return all_scenes, total


def chunks_to_debug(chunks: list[TtsChunk]) -> list[dict[str, Any]]:
    return [
        {
            "text": c.text[:80] + ("…" if len(c.text) > 80 else ""),
            "role": c.role,
            "voice": c.voice,
            "rate": c.rate,
            "pitch": c.pitch,
            "volume": c.volume,
            "style": c.style,
        }
        for c in chunks
    ]
