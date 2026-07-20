"""Shared utilities for the Dark Narrative pipeline."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
PROMPTS = CONFIG / "prompts"


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8").strip()


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def strip_markdown(text: str) -> str:
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    return text.strip()


def normalize_tts_punctuation(text: str) -> str:
    """Fix spacing so TTS pauses naturally at punctuation."""
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([,.!?;:])(?=[A-Za-z\"'])", r"\1 ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"\s*\.\s*", ". ", text)
    text = re.sub(r"\s*\?\s*", "? ", text)
    text = re.sub(r"\s*!\s*", "! ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\.\s+\.", ".", text)
    return text.strip()


def clean_script_for_tts(text: str) -> str:
    """Remove NotebookLM junk and citation markers; keep narration-only text."""
    text = strip_markdown(text)
    # Inline metadata (multi-part merges, conversation IDs, etc.)
    text = re.sub(
        r"(?i)\b(?:new conversation|continuing conversation|conversation)\s*:\s*"
        r"[a-f0-9-]{8,}(?:\s*\(\s*turn\s+\d+\s*\))?",
        "",
        text,
    )
    text = re.sub(r"(?i)\banswer\s*:\s*", "", text)
    text = re.sub(r"(?i)\btotal\s+(parts|scenes)\s*:\s*\d+", "", text)
    text = re.sub(r"(?i)\bpart\s+\d+\b", "", text)
    text = re.sub(r"\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b", "", text, flags=re.IGNORECASE)

    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^answer:\s*$", stripped, re.IGNORECASE):
            continue
        if re.match(r"^answer:\s*total\s+(parts|scenes)\s*:\s*\d+", stripped, re.IGNORECASE):
            continue
        if re.match(r"^total\s+(parts|scenes)\s*:\s*\d+", stripped, re.IGNORECASE):
            continue
        if re.match(r"^part\s+\d+\s*$", stripped, re.IGNORECASE):
            continue
        if re.match(r"^next\s*$", stripped, re.IGNORECASE):
            continue
        if re.match(
            r"^(?:new conversation|continuing conversation|conversation)\s*:\s*[a-f0-9-]+",
            stripped,
            re.IGNORECASE,
        ):
            continue
        kept.append(stripped)
    merged = " ".join(kept)
    merged = re.sub(r"\[\d+(?:,\s*\d+)*\]", "", merged)
    merged = re.sub(r"\s+", " ", merged)
    return normalize_tts_punctuation(merged)


def extract_json_blocks(text: str) -> list[Any]:
    """Parse one or more JSON arrays/objects from LLM output."""
    blocks: list[Any] = []
    fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates = fenced if fenced else [text]
    for chunk in candidates:
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            blocks.append(json.loads(chunk))
        except json.JSONDecodeError:
            for pattern in (r"(\{[\s\S]*\})", r"(\[[\s\S]*\])"):
                match = re.search(pattern, chunk)
                if match:
                    try:
                        blocks.append(json.loads(match.group(1)))
                        break
                    except json.JSONDecodeError:
                        continue
    if not blocks:
        raise ValueError("No JSON found in model response")
    return blocks


def split_script_scenes(script: str) -> list[tuple[int, str]]:
    """Split script on [SCENE_NN] markers."""
    pattern = re.compile(r"\[SCENE_(\d+)\]", re.IGNORECASE)
    parts = pattern.split(script)
    if len(parts) < 3:
        raise ValueError("Script must contain [SCENE_01]..[SCENE_NN] markers")
    scenes: list[tuple[int, str]] = []
    # parts: [preamble, id1, text1, id2, text2, ...]
    i = 1
    while i + 1 < len(parts):
        scene_id = int(parts[i])
        body = strip_markdown(parts[i + 1]).strip()
        if body:
            scenes.append((scene_id, body))
        i += 2
    return scenes


def is_transient_notebooklm_error(message: str) -> bool:
    """True for network/RPC timeouts that are worth retrying on CI."""
    lower = message.lower()
    return any(
        s in lower
        for s in (
            "get_notebook",
            "network error",
            "timed out",
            "timeout",
            "transportservererror",
            "server-error retries exhausted",
            "connection reset",
            "temporarily unavailable",
            "rate limit",
        )
    )


def run_cmd(args: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=merged,
        cwd=ROOT,
    )
    if check and result.returncode != 0:
        sys.stderr.write(result.stderr or result.stdout or "")
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(args)}")
    return result


def notebooklm(*args: str, json_out: bool = False) -> str:
    cmd = ["notebooklm", *args]
    if json_out:
        cmd.append("--json")
    result = run_cmd(cmd)
    return result.stdout.strip()


def notebooklm_json(*args: str) -> dict[str, Any]:
    """Run notebooklm with --json and parse the response envelope."""
    data = json.loads(notebooklm(*args, json_out=True))
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(data.get("message") or str(data))
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected notebooklm JSON response: {data!r}")
    return data


def extract_notebook_id(payload: dict[str, Any]) -> str:
    """notebooklm 0.7+ nests create output under ``notebook``."""
    nb = payload.get("notebook", payload)
    if isinstance(nb, dict) and nb.get("id"):
        return str(nb["id"])
    raise RuntimeError(f"Unexpected notebooklm create response: {payload}")


def extract_source_id(payload: dict[str, Any]) -> str:
    """notebooklm 0.7+ nests source add output under ``source``."""
    src = payload.get("source", payload)
    if isinstance(src, dict) and src.get("id"):
        return str(src["id"])
    if isinstance(src, dict) and src.get("source_id"):
        return str(src["source_id"])
    if payload.get("source_id"):
        return str(payload["source_id"])
    raise RuntimeError(f"Unexpected notebooklm source add response: {payload}")


def append_github_output(key: str, value: str) -> None:
    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def parse_total_parts(text: str) -> int:
    match = re.search(r"Total (?:Parts|Scenes):\s*(\d+)", text, re.IGNORECASE)
    return int(match.group(1)) if match else 1


def strip_total_parts_header(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and re.match(r"Total (?:Parts|Scenes):\s*\d+", lines[0], re.IGNORECASE):
        return "\n".join(lines[1:]).strip()
    if lines and re.match(r"^Answer:\s*$", lines[0], re.IGNORECASE):
        lines = lines[1:]
    if lines and re.match(r"Total (?:Parts|Scenes):\s*\d+", lines[0], re.IGNORECASE):
        return "\n".join(lines[1:]).strip()
    return text.strip()


def notebooklm_json_with_retry(*args: str, retries: int = 4) -> dict[str, Any]:
    """notebooklm_json with retries on transient RPC/network errors."""
    last_err = ""
    for attempt in range(retries):
        try:
            return notebooklm_json(*args)
        except RuntimeError as exc:
            last_err = str(exc)
            if attempt + 1 < retries and is_transient_notebooklm_error(last_err):
                wait = 15 * (attempt + 1)
                print(f"  notebooklm retry {attempt + 2}/{retries} in {wait}s...", flush=True)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(last_err)


def is_transient_http_status(status_code: int) -> bool:
    return status_code in {408, 429, 500, 502, 503, 504}


def httpx_get_json_with_retry(url: str, *, headers: dict | None = None, timeout: float = 60.0, retries: int = 5):
    import httpx

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = httpx.get(url, headers=headers, timeout=timeout)
            if resp.status_code in {502, 503, 504, 429} and attempt + 1 < retries:
                time.sleep(min(60, 5 * (attempt + 1)))
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            retry = isinstance(exc, Exception) and (
                "timeout" in str(exc).lower()
                or "connect" in str(exc).lower()
                or (hasattr(exc, "response") and getattr(exc.response, "status_code", 0) in {502, 503, 504, 429})
            )
            if retry and attempt + 1 < retries:
                time.sleep(min(60, 5 * (attempt + 1)))
                continue
            raise
    raise last_err or RuntimeError(f"GET failed: {url}")


def httpx_post_json_with_retry(
    url: str,
    *,
    json_body: dict,
    headers: dict | None = None,
    timeout: float = 120.0,
    retries: int = 5,
):
    import httpx

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = httpx.post(url, json=json_body, headers=headers, timeout=timeout)
            if resp.status_code in {502, 503, 504, 429} and attempt + 1 < retries:
                time.sleep(min(60, 5 * (attempt + 1)))
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt + 1 < retries and (
                "timeout" in str(exc).lower() or "connect" in str(exc).lower()
            ):
                time.sleep(min(60, 5 * (attempt + 1)))
                continue
            raise
    raise last_err or RuntimeError(f"POST failed: {url}")


def httpx_download_with_retry(
    url: str,
    dest: Path,
    *,
    headers: dict | None = None,
    timeout: float = 120.0,
    retries: int = 5,
) -> None:
    import httpx

    for attempt in range(retries):
        try:
            resp = httpx.get(url, headers=headers, timeout=timeout)
            if resp.status_code in {502, 503, 504, 429} and attempt + 1 < retries:
                time.sleep(min(60, 5 * (attempt + 1)))
                continue
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            return
        except Exception as exc:  # noqa: BLE001
            if attempt + 1 < retries and (
                "timeout" in str(exc).lower() or "connect" in str(exc).lower()
            ):
                time.sleep(min(60, 5 * (attempt + 1)))
                continue
            raise
    raise RuntimeError(f"Download failed: {url}")


def parse_image_prompt_lines(text: str) -> list[str]:
    """Parse blank-line-separated image prompts from NotebookLM output."""
    body = strip_total_parts_header(text)
    blocks = re.split(r"\n\s*\n", body)
    prompts: list[str] = []
    for block in blocks:
        line = " ".join(ln.strip() for ln in block.splitlines() if ln.strip())
        if is_valid_image_prompt(line):
            prompts.append(line)
    return prompts


_METADATA_PROMPT_RE = re.compile(
    r"^(answer:\s*)?(total parts:\s*\d+|part\s+\d+\s*$|next\s*$)",
    re.IGNORECASE,
)
_CONVERSATION_PROMPT_RE = re.compile(
    r"^(?:new conversation|continuing conversation|conversation)\s*:\s*[a-f0-9-]+",
    re.IGNORECASE,
)


def is_valid_image_prompt(line: str, *, min_words: int = 8) -> bool:
    """Drop NotebookLM headers and other non-prompt lines."""
    cleaned = line.strip()
    if not cleaned:
        return False
    if _METADATA_PROMPT_RE.match(cleaned):
        return False
    if _CONVERSATION_PROMPT_RE.match(cleaned):
        return False
    if re.search(r"(?i)\banswer:\s*total\s+(parts|scenes)\s*:", cleaned):
        return False
    if re.search(r"(?i)\b(?:new conversation|conversation)\s*:\s*[a-f0-9-]{8,}", cleaned):
        return False
    if re.match(r"^total parts:\s*\d+", cleaned, re.IGNORECASE):
        return False
    if re.match(r"^scene\s+\d+\b", cleaned, re.IGNORECASE):
        return False
    if re.search(r"\bscene\s+\d+\b.*\blearning\b", cleaned, re.IGNORECASE):
        return False
    if len(cleaned.split()) < min_words:
        return False
    return True


def strip_prompt_labels(prompt: str) -> str:
    """Remove Flow-prone title prefixes from image prompts."""
    p = " ".join(prompt.split()).strip()
    p = re.sub(r"(?i)^scene\s+\d+\s*[:\-]?\s*", "", p)
    p = re.sub(r"(?i)\b(scene|chapter|part)\s+\d+\s*title\s*[:\-]?\s*", "", p)
    return p.strip()


def cap_scenes(prompts: list[str], max_scenes: int) -> list[str]:
    if max_scenes > 0 and len(prompts) > max_scenes:
        return prompts[:max_scenes]
    return prompts


def estimate_scene_count(script: str, pipeline: dict[str, Any] | None = None) -> int:
    """Scene count from narration length — not from LLM prompt spam."""
    pipeline = pipeline or {}
    max_scenes = int(pipeline.get("max_scenes", 60))
    min_scenes = int(pipeline.get("min_scenes", 10))
    words_per_scene = int(pipeline.get("words_per_scene", 35))
    text = clean_script_for_tts(script)
    word_count = len(text.split())
    if word_count < 1:
        return min_scenes
    n = max(min_scenes, round(word_count / max(1, words_per_scene)))
    return min(max_scenes, n)


def align_scenes_to_narration(
    script: str,
    prompts: list[str],
    pipeline: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """
    One image per narrated beat. Drop tail scenes that would be silent 0.35s flashes.
    Returns (prompts, script_segments) with equal length.
    """
    pipeline = pipeline or {}
    max_scenes = int(pipeline.get("max_scenes", 60))
    min_words = int(pipeline.get("min_words_per_scene", 12))
    text = clean_script_for_tts(script)
    target = min(len(prompts), estimate_scene_count(text, pipeline), max_scenes)
    target = max(1, target)
    prompts = prompts[:target]
    segments = split_script_for_scenes(text, len(prompts))

    while len(segments) > 1 and len(segments[-1].split()) < min_words:
        segments.pop()
        prompts.pop()

    if len(segments) != len(prompts):
        segments = split_script_for_scenes(text, len(prompts))

    return prompts, segments


# Theme aliases catch paraphrases ("hate asking for help" ≈ "never ask for help").
THEME_ALIAS_GROUPS: list[frozenset[str]] = [
    frozenset(
        {
            "ask for help",
            "asking for help",
            "asking help",
            "never ask",
            "hate asking",
            "refuse help",
            "refusing help",
            "wont ask",
            "won't ask",
            "cant ask",
            "can't ask",
        }
    ),
    frozenset(
        {
            "hyperindependence",
            "hyper independence",
            "do everything alone",
            "prefer alone",
            "prefer to do everything alone",
            "do it alone",
        }
    ),
    frozenset({"overthink", "overthinker", "overthinking", "chronic overthinker", "rumination"}),
    frozenset({"being watched", "hate being watched", "hypervigilance", "watched", "scrutiny"}),
    frozenset({"people pleasing", "people pleaser", "approval seeking", "fear of saying no"}),
    frozenset({"imposter", "impostor", "imposter syndrome", "impostor syndrome"}),
    frozenset({"procrastinat", "procrastination", "avoidance", "putting things off"}),
    frozenset({"attachment", "avoidant attachment", "anxious attachment", "secure attachment"}),
    frozenset({"burnout", "burned out", "burnt out", "exhaustion"}),
    frozenset({"perfectionis", "perfectionism", "never good enough"}),
    frozenset({"loneliness", "lonely", "isolation", "social isolation"}),
]

_TOPIC_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "in", "on", "to", "for", "with", "from",
        "why", "how", "who", "what", "when", "where", "was", "were", "is", "are",
        "you", "your", "yours", "we", "our", "they", "their", "this", "that",
        "psychology", "psychological", "explained", "entire", "mins", "minutes",
        "science", "people", "person", "human", "humans", "mind", "mental",
        "about", "into", "over", "under", "after", "before", "between", "through",
        "full", "complete", "video", "story", "guide", "deep", "dive",
    }
)

# Light stems so ask/asking and help/helping collide.
_STEM_RULES: tuple[tuple[str, str], ...] = (
    ("asking", "ask"),
    ("asked", "ask"),
    ("helping", "help"),
    ("helped", "help"),
    ("hating", "hate"),
    ("hated", "hate"),
    ("watching", "watch"),
    ("watched", "watch"),
    ("preferring", "prefer"),
    ("preferred", "prefer"),
    ("thinking", "think"),
    ("overthinking", "overthink"),
    ("overthinker", "overthink"),
    ("loneliness", "lonely"),
)


def normalize_topic_text(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("'", "'").replace("'", "'")
    t = t.replace("won't", "wont").replace("can't", "cant").replace("don't", "dont")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _stem_token(token: str) -> str:
    for src, dst in _STEM_RULES:
        if token == src or token.startswith(src):
            return dst
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ers") and len(token) > 5:
        return token[:-3]
    if token.endswith("er") and len(token) > 4:
        return token[:-2]
    if token.endswith("ies") and len(token) > 5:
        return token[:-3] + "y"
    if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
        return token[:-1]
    return token


def extract_topic_keys(text: str) -> set[str]:
    """Keys for hard dedupe: theme aliases, stemmed tokens, bigrams."""
    norm = normalize_topic_text(text)
    if not norm:
        return set()
    keys: set[str] = set()
    for group in THEME_ALIAS_GROUPS:
        lowered = {a.lower() for a in group}
        if any(alias in norm for alias in lowered):
            keys.add("theme:" + "|".join(sorted(lowered)[:6]))
            keys.update(lowered)
    words = [
        _stem_token(w)
        for w in norm.split()
        if w not in _TOPIC_STOPWORDS and len(w) >= 3
    ]
    words = [w for w in words if w not in _TOPIC_STOPWORDS and len(w) >= 3]
    for w in words:
        if len(w) >= 4:
            keys.add(w)
    for i in range(len(words) - 1):
        bigram = f"{words[i]} {words[i + 1]}"
        if len(bigram) >= 7:
            keys.add(bigram)
    return keys


def topic_keys_for_history_row(row: dict[str, Any]) -> set[str]:
    stored = row.get("topic_keys")
    if isinstance(stored, list) and stored:
        return {str(x).lower() for x in stored}
    blob = " ".join(str(row.get(k, "")) for k in ("topic", "title") if row.get(k))
    return extract_topic_keys(blob)


def topic_similarity_ratio(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    na = normalize_topic_text(a)
    nb = normalize_topic_text(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def topic_overlaps_history(topic: str, history: list[dict[str, Any]] | None = None) -> str | None:
    """
    Return a reason if topic is the same theme / near-paraphrase of a past video.
    Strict: theme-group hit, strong key overlap, or high title similarity.
    """
    history = history if history is not None else load_topic_history()
    cand = extract_topic_keys(topic)
    for row in history:
        past_label = row.get("title") or row.get("topic") or "prior video"
        past_blob = f"{row.get('title', '')} {row.get('topic', '')}".strip()
        ratio = topic_similarity_ratio(topic, past_blob)
        if ratio >= 0.72:
            return f"too similar to prior video ({past_label}) similarity={ratio:.2f}"

        past_keys = topic_keys_for_history_row(row)
        overlap = {
            k
            for k in (cand & past_keys)
            if k not in _TOPIC_STOPWORDS and (k.startswith("theme:") or len(k) >= 5)
        }
        if not overlap:
            continue
        strong = any(k.startswith("theme:") or " " in k for k in overlap) or len(overlap) >= 2
        if strong:
            sample = ", ".join(sorted(overlap)[:4])
            return f"overlaps prior theme ({past_label}) via [{sample}]"
    return None


def filter_topics_against_history(
    topics: list[str],
    history: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[tuple[str, str]]]:
    history = history if history is not None else load_topic_history()
    kept: list[str] = []
    rejected: list[tuple[str, str]] = []
    for t in topics:
        reason = topic_overlaps_history(t, history)
        if reason:
            rejected.append((t, reason))
        else:
            kept.append(t)
    return kept, rejected


def load_topic_history(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or CONFIG / "topic_history.json"
    if not path.exists():
        return []
    data = load_json(path)
    if isinstance(data, dict):
        return list(data.get("topics", []))
    if isinstance(data, list):
        return data
    return []


def format_topic_history_for_prompt(topics: list[dict[str, Any]], limit: int = 80) -> str:
    if not topics:
        return "(none yet — this is the first video)"
    lines: list[str] = [
        "HARD BAN — these topics/themes are CLOSED. Do NOT repeat, rephrase, or pick a near-duplicate:",
        "Near-duplicate examples that MUST be rejected: 'Hate Asking for Help' ≈ 'Never Ask for Help'.",
    ]
    for row in topics[-limit:]:
        title = row.get("title") or row.get("topic") or "Unknown"
        topic = row.get("topic") or ""
        run_id = row.get("run_id", "")
        keys = sorted(
            k for k in topic_keys_for_history_row(row) if not k.startswith("theme:")
        )[:8]
        line = f"- DONE: {title}"
        if topic and topic != title:
            line += f" (key: {topic})"
        if run_id:
            line += f" [{run_id}]"
        if keys:
            line += f" | ban tokens: {', '.join(keys)}"
        lines.append(line)
    lines.append(
        "Pick a completely different psychological mechanism / audience pain — not a title rewrite."
    )
    return "\n".join(lines)


def append_topic_history(
    path: Path,
    *,
    run_id: str,
    topic: str,
    title: str,
    max_entries: int = 80,
) -> None:
    existing = load_topic_history(path)
    keys = sorted(extract_topic_keys(f"{topic} {title}"))
    row = {
        "run_id": run_id,
        "topic": topic,
        "title": title,
        "topic_keys": keys,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Drop prior rows that are the same theme so history stays clean.
    existing = [
        r
        for r in existing
        if not topic_overlaps_history(topic, [r]) and not topic_overlaps_history(title, [r])
    ]
    existing.append(row)
    save_json(path, {"topics": existing[-max_entries:]})

def prompts_to_scenes(prompts: list[str], entity_refs: list[str] | None = None) -> list[dict]:
    refs = entity_refs or ["character_A"]
    return [
        {"scene_id": i + 1, "prompt": p, "entity_refs": list(refs)}
        for i, p in enumerate(prompts)
    ]


def dedupe_prompts(prompts: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in prompts:
        key = p.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p.strip())
    return out


def split_script_for_scenes(script: str, num_scenes: int) -> list[str]:
    """
    Split narration into N sequential chunks for per-scene TTS.
    Image prompt i aligns with audio chunk i → editor-accurate timing.
    Distributes words evenly — no empty trailing scenes.
    """
    if num_scenes < 1:
        raise ValueError("num_scenes must be >= 1")
    text = re.sub(r"\s+", " ", script.strip())
    if not text:
        return [""] * num_scenes

    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return [text] + [""] * (num_scenes - 1)

    # Fewer sentences than scenes: split by word budget (avoid rapid empty tail clips)
    if len(sentences) < num_scenes:
        words = text.split()
        if not words:
            return [""] * num_scenes
        words_per = len(words) / num_scenes
        chunks: list[str] = []
        for i in range(num_scenes):
            a = int(i * words_per)
            b = len(words) if i == num_scenes - 1 else int((i + 1) * words_per)
            chunks.append(" ".join(words[a:b]))
        return chunks

    if len(sentences) <= num_scenes:
        return sentences + [""] * (num_scenes - len(sentences))

    total_words = sum(len(s.split()) for s in sentences)
    words_per_chunk = total_words / num_scenes
    chunks = []
    current: list[str] = []
    word_count = 0

    for sent in sentences:
        current.append(sent)
        word_count += len(sent.split())
        if len(chunks) < num_scenes - 1 and word_count >= words_per_chunk:
            chunks.append(" ".join(current))
            current = []
            word_count = 0

    if current:
        chunks.append(" ".join(current))

    while len(chunks) < num_scenes:
        chunks.append("")
    return chunks[:num_scenes]


def parse_seo_json(text: str) -> dict:
    blocks = extract_json_blocks(text)
    for block in blocks:
        if isinstance(block, dict) and "title" in block:
            return block
    raise ValueError("No SEO JSON object in NotebookLM response")


def sanitize_seo_title(title: str, max_chars: int = 65) -> str:
    cleaned = re.sub(r"\*+", "", title or "").strip(" -–—")
    return cleaned[:max_chars].strip()


def fallback_seo(topic: str) -> dict:
    """Rich SEO metadata when NotebookLM returns non-JSON."""
    niche = load_json(CONFIG / "niche.json") if (CONFIG / "niche.json").exists() else {}
    channel = niche.get("name", "Doodlytical")
    tagline = niche.get("tagline", "Psychology explainers in about 15 minutes.")
    title = sanitize_seo_title(topic)
    description = (
        f"{tagline}\n\n"
        f"In this video we break down {topic.lower()} with stick-figure stories and real psychology — "
        f"no jargon, no fluff.\n\n"
        f"What you'll learn:\n"
        f"• Why this pattern shows up in everyday life\n"
        f"• The hidden mental mechanism behind it\n"
        f"• Practical takeaways you can use today\n\n"
        f"Timestamps coming soon.\n\n"
        f"If this helped, subscribe to {channel} for more psychology explainers."
    )
    return {
        "title": title,
        "description": description,
        "tags": ["doodlytical", "psychology", "human behavior", "motivation", "self improvement"],
        "hashtags": ["#psychology", "#doodlytical"],
    }
