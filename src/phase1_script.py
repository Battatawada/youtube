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
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    CONFIG,
    cap_scenes,
    clean_script_for_tts,
    dedupe_prompts,
    extract_notebook_id,
    extract_source_id,
    fallback_seo,
    is_valid_image_prompt,
    is_transient_notebooklm_error,
    load_json,
    load_prompt,
    new_run_id,
    notebooklm_json,
    notebooklm_json_with_retry,
    parse_image_prompt_lines,
    parse_seo_json,
    parse_total_parts,
    prompts_to_scenes,
    save_json,
    split_script_for_scenes,
    strip_markdown,
    strip_total_parts_header,
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


def ask(notebook_id: str, prompt: str, *, new: bool = False, retries: int = 4) -> str:
    import subprocess

    cmd = ["notebooklm", "ask", prompt, "--notebook", notebook_id, "--request-timeout", "180"]
    if new:
        cmd.extend(["--new", "--yes"])
    last_err = ""
    for attempt in range(retries):
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
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
    raise RuntimeError(last_err)


_BAD_TOPIC = re.compile(r"continuing conversation|^[a-f0-9]{8,}$", re.IGNORECASE)


def _first_topic_from_list(topics_raw: str) -> str:
    for line in topics_raw.splitlines():
        cleaned = re.sub(r"^\d+[\).\s]+", "", line.strip()).strip('"')
        if cleaned and len(cleaned) > 15 and not _BAD_TOPIC.search(cleaned):
            return cleaned
    raise RuntimeError("Could not parse any topic from topics_list")


def pick_topic(notebook_id: str, topics_raw: str) -> str:
    """Pick topic in the same NotebookLM chat as topics list (no --new)."""
    prompt = f"{load_prompt('pick_topic.txt')}\n\nTopics:\n{topics_raw}"
    try:
        raw = ask(notebook_id, prompt, new=False)
        line = raw.strip().splitlines()[0].strip()
        line = re.sub(r"^\d+[\).\s]+", "", line)
        line = line.strip('"').strip("'")
        if _BAD_TOPIC.search(line) or len(line) < 15:
            print("  Warning: bad topic pick, using first listed topic", flush=True)
            return _first_topic_from_list(topics_raw)
        return line
    except Exception as exc:
        print(f"  Warning: topic pick failed ({exc}), using first listed topic", flush=True)
        return _first_topic_from_list(topics_raw)


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
    notebook_id: str, initial_prompt: str, continue_word: str = "Next", *, new: bool = False
) -> list[str]:
    first = ask(notebook_id, initial_prompt, new=new)
    total = parse_total_parts(first)
    all_prompts = parse_image_prompt_lines(first)

    for part_num in range(2, total + 1):
        print(f"  Image prompts part {part_num}/{total}...", flush=True)
        cont = ask(notebook_id, continue_word)
        all_prompts.extend(parse_image_prompt_lines(cont))

    return all_prompts


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
        topics_raw = ask(notebook_id, load_prompt("topics_finding.txt"), new=True)
        (out / "topics_list.txt").write_text(topics_raw, encoding="utf-8")

        print("[Step 2] Pick topic...", flush=True)
        topic = pick_topic(notebook_id, topics_raw)
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
        image_prompt = load_prompt("story_to_image.txt").replace("{duration_minutes}", str(duration))
        prompt_lines = collect_all_image_prompts(notebook_id, image_prompt, continue_word, new=True)
        if len(prompt_lines) < 10:
            print("  Warning: very few image prompts, retrying once...", flush=True)
            prompt_lines = collect_all_image_prompts(
                notebook_id, image_prompt + "\n\nGenerate at least 40 distinct prompts.", continue_word, new=True
            )

        if pipeline.get("dedupe_image_prompts", True):
            before = len(prompt_lines)
            prompt_lines = dedupe_prompts(prompt_lines)
            if len(prompt_lines) < before:
                print(f"  Deduped {before - len(prompt_lines)} repeated prompts", flush=True)

        before_filter = len(prompt_lines)
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

        print("[Step 8] YouTube SEO (US)...", flush=True)
        seo_prompt = load_prompt("youtube_seo.txt").replace("{topic}", topic)
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

    scenes = prompts_to_scenes(prompt_lines, entity_refs)
    if not args.dry_run:
        (out / "script_raw.txt").write_text(script, encoding="utf-8")
    script = clean_script_for_tts(script)
    segments = [clean_script_for_tts(t) for t in split_script_for_scenes(script, len(scenes))]

    (out / "script.txt").write_text(script, encoding="utf-8")
    (out / "topics.txt").write_text(topic, encoding="utf-8")
    save_json(out / "scenes.json", scenes)
    save_json(out / "script_segments.json", [{"scene_id": i + 1, "text": t} for i, t in enumerate(segments)])
    save_json(out / "youtube_seo.json", seo)
    save_json(out / "entities.json", [])

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
