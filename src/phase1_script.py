#!/usr/bin/env python3
"""
Phase 1 — NotebookLM (steps 1–3, 5, 8 of manual workflow)

  1. Ingest niche links
  2. Generate top 10 topics → pick one
  3. Multi-part story script (TTS-ready, duration-accurate word count)
  5. Multi-part image prompts (chibi, one visual per prompt)
  8. US YouTube SEO JSON (title, description, tags)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    CONFIG,
    align_scenes_to_narration,
    append_topic_history,
    cap_scenes,
    clean_script_for_tts,
    dedupe_prompts,
    estimate_scene_count,
    extract_notebook_id,
    extract_source_id,
    fallback_seo,
    filter_topics_against_history,
    format_topic_history_for_prompt,
    is_valid_image_prompt,
    is_transient_notebooklm_error,
    load_json,
    load_prompt,
    load_topic_history,
    new_run_id,
    notebooklm_json,
    notebooklm_json_with_retry,
    parse_image_prompt_lines,
    parse_seo_json,
    parse_total_parts,
    prompts_to_scenes,
    save_json,
    strip_prompt_labels,
    split_script_for_scenes,
    strip_markdown,
    strip_total_parts_header,
    topic_overlaps_history,
)


def wait_sources(
    notebook_id: str,
    source_ids: list[str],
    *,
    timeout: int = 900,
    max_attempts: int = 5,
) -> None:
    import subprocess

    for idx, sid in enumerate(source_ids, start=1):
        print(f"  Waiting for source {idx}/{len(source_ids)} ({sid[:8]}...)", flush=True)
        last_err = ""
        for attempt in range(max_attempts):
            result = subprocess.run(
                [
                    "notebooklm",
                    "source",
                    "wait",
                    sid,
                    "-n",
                    notebook_id,
                    "--timeout",
                    str(timeout),
                    "--interval",
                    "3",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                last_err = ""
                break
            last_err = (result.stderr or result.stdout or "source wait failed").strip()
            if attempt + 1 < max_attempts and is_transient_notebooklm_error(last_err):
                wait = 20 * (attempt + 1)
                print(f"  Source wait retry {attempt + 2}/{max_attempts} in {wait}s...", flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f"Source {sid} failed: {last_err}")
        if last_err:
            raise RuntimeError(f"Source {sid} failed: {last_err}")


def _parse_ask_response(raw_stdout: str) -> str:
    text = raw_stdout.strip()
    if not text:
        return ""
    if text.startswith("{"):
        try:
            data = json.loads(text)
            answer = data.get("answer") or data.get("text") or ""
            if isinstance(answer, str) and answer.strip():
                return answer.strip()
        except json.JSONDecodeError:
            pass
    return text


def ask(
    notebook_id: str,
    prompt: str,
    *,
    new: bool = False,
    retries: int = 4,
    request_timeout: int = 180,
) -> str:
    import subprocess

    use_prompt_file = len(prompt) > 6000
    prompt_file: Path | None = None
    if use_prompt_file:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        tmp.write(prompt)
        tmp.close()
        prompt_file = Path(tmp.name)

    cmd = [
        "notebooklm",
        "ask",
        *(["--prompt-file", str(prompt_file)] if prompt_file else [prompt]),
        "--notebook",
        notebook_id,
        "--request-timeout",
        str(request_timeout),
        "--json",
    ]
    if new:
        cmd.extend(["--new", "--yes"])
    last_err = ""
    try:
        for attempt in range(retries):
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            answer = _parse_ask_response(result.stdout or "")
            if result.returncode == 0 and answer:
                return answer
            last_err = (result.stderr or result.stdout or "notebooklm ask failed").strip()
            if attempt + 1 < retries and (
                is_transient_notebooklm_error(last_err)
                or any(
                    s in last_err.lower()
                    for s in (
                        "parseable chunks",
                        "empty response",
                        "streaming chat",
                    )
                )
            ):
                wait = 8 * (attempt + 1)
                print(f"  notebooklm ask retry {attempt + 2}/{retries} in {wait}s...", flush=True)
                time.sleep(wait)
                continue
            break
    finally:
        if prompt_file:
            prompt_file.unlink(missing_ok=True)
    raise RuntimeError(last_err)


_BAD_TOPIC = re.compile(r"continuing conversation|^[a-f0-9]{8,}$", re.IGNORECASE)


def parse_numbered_topics(topics_raw: str) -> list[str]:
    out: list[str] = []
    for line in topics_raw.splitlines():
        cleaned = re.sub(r"^\d+[\).\s]+", "", line.strip()).strip('"').strip("'")
        if cleaned and len(cleaned) > 15 and not _BAD_TOPIC.search(cleaned):
            out.append(cleaned)
    return out


def _first_topic_from_list(topics_raw: str) -> str:
    for cleaned in parse_numbered_topics(topics_raw):
        return cleaned
    raise RuntimeError("Could not parse any topic from topics_list")


def _first_fresh_topic(topics_raw: str, history: list | None = None) -> str:
    history = history if history is not None else load_topic_history()
    for cleaned in parse_numbered_topics(topics_raw):
        reason = topic_overlaps_history(cleaned, history)
        if reason:
            print(f"  Skip listed topic (history): {cleaned[:80]} — {reason}", flush=True)
            continue
        return cleaned
    raise RuntimeError(
        "All candidate topics overlap past videos. Refusing to ship a near-duplicate. "
        "Update topic_history / regenerate topics."
    )


def pick_topic(notebook_id: str, topics_raw: str, past_topics: str) -> str:
    """Pick topic in the same NotebookLM chat as topics list (no --new). Hard history check."""
    history = load_topic_history()
    prompt = (
        f"{load_prompt('pick_topic.txt').replace('{past_topics}', past_topics)}\n\nTopics:\n{topics_raw}"
    )
    try:
        raw = ask(notebook_id, prompt, new=False)
        line = raw.strip().splitlines()[0].strip()
        line = re.sub(r"^\d+[\).\s]+", "", line)
        line = line.strip('"').strip("'")
        if _BAD_TOPIC.search(line) or len(line) < 15:
            print("  Warning: bad topic pick, using first fresh listed topic", flush=True)
            return _first_fresh_topic(topics_raw, history)
        reason = topic_overlaps_history(line, history)
        if reason:
            print(f"  Warning: model re-picked a closed theme — {reason}", flush=True)
            return _first_fresh_topic(topics_raw, history)
        return line
    except RuntimeError:
        raise
    except Exception as exc:
        print(f"  Warning: topic pick failed ({exc}), using first fresh listed topic", flush=True)
        return _first_fresh_topic(topics_raw, history)


def collect_multipart_text(
    notebook_id: str, initial_prompt: str, continue_word: str = "Next", *, new: bool = False
) -> tuple[str, int]:
    first = ask(notebook_id, initial_prompt, new=new)
    total = parse_total_parts(first)
    chunks = [clean_script_for_tts(strip_total_parts_header(strip_markdown(first)))]

    for part_num in range(2, total + 1):
        print(f"  Story part {part_num}/{total}...", flush=True)
        cont = ask(notebook_id, continue_word)
        chunks.append(clean_script_for_tts(strip_total_parts_header(strip_markdown(cont))))

    return "\n\n".join(c for c in chunks if c), total


def collect_all_image_prompts(
    notebook_id: str,
    initial_prompt: str,
    continue_word: str = "Next",
    *,
    new: bool = False,
    retries: int = 6,
    request_timeout: int = 300,
) -> list[str]:
    first = ask(
        notebook_id,
        initial_prompt,
        new=new,
        retries=retries,
        request_timeout=request_timeout,
    )
    total = parse_total_parts(first)
    all_prompts = parse_image_prompt_lines(first)

    for part_num in range(2, total + 1):
        print(f"  Image prompts part {part_num}/{total}...", flush=True)
        cont = ask(
            notebook_id,
            continue_word,
            retries=retries,
            request_timeout=request_timeout,
        )
        all_prompts.extend(parse_image_prompt_lines(cont))

    return all_prompts


def build_image_prompt(
    script: str,
    *,
    duration: int,
    target_scene_count: int,
    embed_script: bool = False,
    max_script_chars: int = 4500,
) -> str:
    """Build image prompt. Prefer conversation context (no embed) to avoid huge asks."""
    template = (
        load_prompt("story_to_image.txt")
        .replace("{duration_minutes}", str(duration))
        .replace("{target_scene_count}", str(target_scene_count))
    )
    if embed_script:
        excerpt = script[:max_script_chars].strip()
        if len(script) > max_script_chars:
            excerpt += "\n[Script continues to the ending in the notebook.]"
        template = template.replace(
            "Use ONLY the complete story script from our conversation above.",
            "Use ONLY the narration script below.",
        )
        script_block = f"\n--- NARRATION SCRIPT ---\n{excerpt}\n"
    else:
        script_block = ""
    return template.replace("{script_excerpt}", script_block)


def collect_image_prompts_chunked(
    notebook_id: str,
    script: str,
    *,
    duration: int,
    target_scene_count: int,
    continue_word: str,
    num_chunks: int = 3,
) -> list[str]:
    """Split script into chunks; fresh NotebookLM chat per chunk (most reliable)."""
    words = script.split()
    if not words:
        return []
    chunk_words = max(250, (len(words) + num_chunks - 1) // num_chunks)
    chunks: list[str] = []
    for i in range(0, len(words), chunk_words):
        chunks.append(" ".join(words[i : i + chunk_words]))

    per_chunk = max(8, (target_scene_count + len(chunks) - 1) // len(chunks))
    all_prompts: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        print(f"  Image chunk {idx}/{len(chunks)} (~{len(chunk.split())} words, {per_chunk} prompts)...", flush=True)
        prompt = build_image_prompt(
            chunk,
            duration=duration,
            target_scene_count=per_chunk,
            embed_script=True,
            max_script_chars=len(chunk) + 100,
        )
        lines = collect_all_image_prompts(
            notebook_id,
            prompt,
            continue_word,
            new=True,
            retries=6,
            request_timeout=300,
        )
        all_prompts.extend(lines)
        if idx < len(chunks):
            time.sleep(12)
    return all_prompts


def collect_image_prompts_resilient(
    notebook_id: str,
    script: str,
    *,
    duration: int,
    target_scene_count: int,
    continue_word: str,
) -> list[str]:
    """Try story chat first (short ask), then fall back to embedded script chunks."""
    time.sleep(12)
    strategies: list[tuple[str, bool, int]] = [
        ("story chat", False, 0),
        ("embedded script (4.5k chars)", True, 4500),
        ("embedded script (2.5k chars)", True, 2500),
    ]
    last_err = ""
    for label, embed, max_chars in strategies:
        prompt = build_image_prompt(
            script,
            duration=duration,
            target_scene_count=target_scene_count,
            embed_script=embed,
            max_script_chars=max_chars,
        )
        print(f"  Image prompts via {label}...", flush=True)
        try:
            lines = collect_all_image_prompts(
                notebook_id,
                prompt,
                continue_word,
                new=not embed,
                retries=6,
                request_timeout=300,
            )
            if len(lines) >= max(5, target_scene_count // 4):
                print(f"  -> {len(lines)} prompts from {label}", flush=True)
                return lines
            print(f"  Warning: only {len(lines)} prompts from {label}, trying next strategy...", flush=True)
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            print(f"  Warning: {label} failed ({exc})", flush=True)
            time.sleep(12)

    print("  Falling back to chunked script image prompts...", flush=True)
    try:
        lines = collect_image_prompts_chunked(
            notebook_id,
            script,
            duration=duration,
            target_scene_count=target_scene_count,
            continue_word=continue_word,
        )
        if len(lines) >= 5:
            print(f"  -> {len(lines)} prompts from chunked script", flush=True)
            return lines
    except Exception as exc:  # noqa: BLE001
        last_err = str(exc)
        print(f"  Warning: chunked script failed ({exc})", flush=True)

    raise RuntimeError(last_err or "Image prompt generation failed after all strategies")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1: NotebookLM")
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--config", type=Path, default=CONFIG / "seed_urls.json")
    parser.add_argument("--pipeline", type=Path, default=CONFIG / "pipeline.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    run_id = new_run_id()
    pipeline = load_json(args.pipeline) if args.pipeline.exists() else {}
    niche = load_json(CONFIG / "niche.json") if (CONFIG / "niche.json").exists() else {}
    duration = int(pipeline.get("duration_minutes", 15))
    wpm = int(pipeline.get("words_per_minute", 140))
    entity_refs = pipeline.get("default_entity_refs", ["character_A"])
    continue_word = pipeline.get("continue_keyword", "Next")
    target_words = duration * wpm
    notebook_id = ""
    segments: list[str] = []
    thumbnail_meta: dict | None = None

    if args.dry_run:
        script = (
            "The rain had not stopped for three days. "
            "Nobody in the town spoke about what was buried beneath the old market."
        )
        prompt_lines = [
            "Minimal cinematic chibi, lone figure at rain-streaked window, amber streetlight, muted blues.",
            "Minimal cinematic chibi, figure approaching basement door, flickering bulb, tense posture.",
        ]
        topic = "Entire psychology of fear in 15 mins"
        story_parts = 1
        seo = {"title": "The Psychology of Fear Explained", "description": "...", "tags": ["psychology"], "hashtags": []}
        script = clean_script_for_tts(script)
        prompt_lines, segments = align_scenes_to_narration(script, prompt_lines, pipeline)
    else:
        seeds = load_json(args.config)
        urls = seeds.get("urls", [])
        if not urls or "REPLACE" in str(urls[0]):
            sys.exit("Edit config/seed_urls.json with niche reference YouTube URLs")

        created = notebooklm_json_with_retry("create", f"{niche.get('name', 'Video')} {run_id}", "--use")
        notebook_id = extract_notebook_id(created)

        source_ids: list[str] = []
        source_request_timeout = int(pipeline.get("source_request_timeout", 120))
        source_add_delay = float(pipeline.get("source_add_delay_sec", 5))
        for i, url in enumerate(urls):
            if i:
                time.sleep(source_add_delay)
            print(f"  Adding source {i + 1}/{len(urls)}...", flush=True)
            added = notebooklm_json_with_retry(
                "source",
                "add",
                url,
                "--notebook",
                notebook_id,
                "--request-timeout",
                str(source_request_timeout),
            )
            source_ids.append(extract_source_id(added))
        time.sleep(source_add_delay)
        wait_sources(
            notebook_id,
            source_ids,
            timeout=int(pipeline.get("source_wait_timeout", 300)),
        )

        print("[Step 1–2] Topics...", flush=True)
        history = load_topic_history()
        past_topics = format_topic_history_for_prompt(history)
        topics_prompt = load_prompt("topics_finding.txt").replace("{past_topics}", past_topics)
        topics_raw = ask(notebook_id, topics_prompt, new=True)
        (out / "topics_list.txt").write_text(topics_raw, encoding="utf-8")

        # Hard filter before pick — prompts alone are not enough (near-duplicate titles shipped).
        parsed = parse_numbered_topics(topics_raw)
        kept, rejected = filter_topics_against_history(parsed, history)
        for t, reason in rejected:
            print(f"  Topic blocked: {t[:90]} — {reason}", flush=True)
        if not kept:
            raise RuntimeError(
                "No fresh topics left after history filter. "
                "All candidates overlapped past videos — refusing duplicate."
            )
        topics_raw = "\n".join(f"{i}. {t}" for i, t in enumerate(kept[:10], 1))
        (out / "topics_list.txt").write_text(topics_raw, encoding="utf-8")

        print("[Step 2] Pick topic...", flush=True)
        topic = pick_topic(notebook_id, topics_raw, past_topics)
        overlap = topic_overlaps_history(topic, history)
        if overlap:
            print(f"  Warning: final pick blocked — {overlap}", flush=True)
            topic = _first_fresh_topic(topics_raw, history)
        # Final hard gate — never continue with a near-duplicate.
        final_hit = topic_overlaps_history(topic, history)
        if final_hit:
            raise RuntimeError(f"Refusing near-duplicate topic: {topic} — {final_hit}")
        print(f"  -> {topic}", flush=True)

        print("[Step 3] Script (multi-part)...", flush=True)
        story_prompt = (
            load_prompt("story_generation.txt")
            .replace("{topic}", topic)
            .replace("{duration_minutes}", str(duration))
        )
        script, story_parts = collect_multipart_text(notebook_id, story_prompt, continue_word, new=True)
        word_count = len(script.split())
        print(f"  -> {word_count} words (target ~{target_words})", flush=True)

        print("[Step 5] Image prompts (multi-part)...", flush=True)
        target_scene_count = estimate_scene_count(script, pipeline)
        print(f"  -> target {target_scene_count} scenes from {word_count} words", flush=True)
        prompt_lines = collect_image_prompts_resilient(
            notebook_id,
            script,
            duration=duration,
            target_scene_count=target_scene_count,
            continue_word=continue_word,
        )

        if pipeline.get("dedupe_image_prompts", True):
            before = len(prompt_lines)
            prompt_lines = dedupe_prompts(prompt_lines)
            if len(prompt_lines) < before:
                print(f"  Deduped {before - len(prompt_lines)} repeated prompts", flush=True)

        before_filter = len(prompt_lines)
        prompt_lines = [strip_prompt_labels(p) for p in prompt_lines]
        prompt_lines = [p for p in prompt_lines if is_valid_image_prompt(p)]
        if len(prompt_lines) < before_filter:
            print(f"  Dropped {before_filter - len(prompt_lines)} junk image prompts", flush=True)

        if len(prompt_lines) < 5:
            sys.exit(f"Too few image prompts after filtering ({len(prompt_lines)}). Re-run pipeline.")

        max_scenes = int(pipeline.get("max_scenes", 60))
        before_cap = len(prompt_lines)
        prompt_lines = cap_scenes(prompt_lines, max_scenes)
        if len(prompt_lines) < before_cap:
            print(f"  Capped scenes {before_cap} -> {len(prompt_lines)} (max_scenes={max_scenes})", flush=True)

        script = clean_script_for_tts(script)
        prompt_lines, segments = align_scenes_to_narration(script, prompt_lines, pipeline)
        print(f"  Aligned to {len(prompt_lines)} narrated scenes (dropped unused tail prompts)", flush=True)

        print("[Step 8] YouTube SEO (US)...", flush=True)
        seo_prompt = (
            load_prompt("youtube_seo.txt")
            .replace("{topic}", topic)
            .replace("{past_topics}", past_topics)
        )
        seo_raw = ask(notebook_id, seo_prompt, new=True)
        (out / "youtube_seo_raw.txt").write_text(seo_raw, encoding="utf-8")
        try:
            seo = parse_seo_json(seo_raw)
        except ValueError:
            print("  SEO JSON parse failed, retrying with stricter prompt...", flush=True)
            retry = f"{seo_prompt}\n\nReply with ONLY raw JSON. No markdown, no explanation."
            seo_raw = ask(notebook_id, retry, new=True)
            (out / "youtube_seo_raw.txt").write_text(seo_raw, encoding="utf-8")
            try:
                seo = parse_seo_json(seo_raw)
            except ValueError:
                print("  Using fallback SEO metadata", flush=True)
                seo = fallback_seo(topic)

        thumbnail_meta: dict | None = None
        if pipeline.get("generate_thumbnail", True):
            print("[Step 6] Thumbnail prompt...", flush=True)
            thumb_prompt = (
                load_prompt("thumbnail.txt")
                .replace("{topic}", topic)
                .replace("{title}", seo.get("title", topic))
            )
            thumb_raw = ask(notebook_id, thumb_prompt, new=True)
            thumb_line = " ".join(thumb_raw.strip().splitlines()[0].split()).strip('"')
            if len(thumb_line) > 30:
                thumbnail_meta = {
                    "prompt": thumb_line,
                    "topic": topic,
                    "title": seo.get("title", topic),
                    "entity_refs": entity_refs,
                }
                print(f"  -> thumbnail prompt ({len(thumb_line.split())} words)", flush=True)

    scenes = prompts_to_scenes(prompt_lines, entity_refs)
    if not args.dry_run:
        (out / "script_raw.txt").write_text(script, encoding="utf-8")
    if not segments:
        segments = [clean_script_for_tts(t) for t in split_script_for_scenes(script, len(scenes))]

    (out / "script.txt").write_text(script, encoding="utf-8")
    (out / "topics.txt").write_text(topic, encoding="utf-8")
    save_json(out / "scenes.json", scenes)
    save_json(out / "script_segments.json", [{"scene_id": i + 1, "text": t} for i, t in enumerate(segments)])
    save_json(out / "youtube_seo.json", seo)
    save_json(out / "entities.json", [])
    if thumbnail_meta:
        save_json(out / "thumbnail.json", thumbnail_meta)

    history_path = CONFIG / "topic_history.json"
    if not args.dry_run:
        append_topic_history(
            history_path,
            run_id=run_id,
            topic=topic,
            title=str(seo.get("title", topic)),
        )

    meta: dict = {
        "run_id": run_id,
        "notebook_id": notebook_id,
        "niche": niche.get("name"),
        "topic": topic,
        "duration_minutes": duration,
        "word_count": len(script.split()),
        "target_word_count": target_words,
        "scene_count": len(scenes),
        "image_style": pipeline.get("image_style"),
        "title": seo.get("title"),
    }
    if not args.dry_run:
        meta["story_parts"] = story_parts
    save_json(out / "metadata.json", meta)

    print(f"run_id={run_id}")
    print(f"Done: script + {len(scenes)} scenes + SEO -> {out}")


if __name__ == "__main__":
    main()
