"""Sequential one-scene-at-a-time FlowKit image generation."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from flowkit_client import FlowKitClient
from ref_loader import refs_dir_from_env, upload_references, verify_references


def _rewrite_prompt_safe(prompt: str) -> str:
    """Light touch rewrite for safety filter retries."""
    return (
        prompt
        + ", stylized fictional illustration, no real persons, no violence, no gore, soft lighting"
    )


def _start_flowkit_stack() -> None:
    if os.environ.get("FLOWKIT_USE_SYSTEMD", "1") == "1":
        return
    script = os.environ.get("FLOWKIT_START_SCRIPT")
    if script and Path(script).exists():
        subprocess.run(["bash", script], check=False)


def _restart_flowkit_stack() -> None:
    script = os.environ.get("FLOWKIT_RESTART_SCRIPT")
    if script and Path(script).exists():
        subprocess.run(["bash", script], check=False, timeout=180)
        return
    if os.environ.get("FLOWKIT_USE_SYSTEMD", "1") == "1":
        subprocess.run(["systemctl", "restart", "flowkit-agent"], check=False)


def _stop_flowkit_stack() -> None:
    if os.environ.get("FLOWKIT_USE_SYSTEMD", "1") == "1":
        return
    script = os.environ.get("FLOWKIT_STOP_SCRIPT")
    if script and Path(script).exists():
        subprocess.run(["bash", script], check=False)


def _sanitize_prompt(prompt: str, scene_id: int) -> str:
    cleaned = " ".join(str(prompt).split()).strip()
    lower = cleaned.lower()
    if (
        len(cleaned.split()) >= 8
        and not lower.startswith("answer:")
        and "total parts:" not in lower
        and not lower.startswith("part ")
    ):
        return cleaned
    return (
        "Minimalist stick figure line art, consistent circular-head character, "
        f"cream background, scene {scene_id}, educational psychology mood"
    )


class SequentialGenerator:
    def __init__(
        self,
        run_id: str,
        runs_dir: Path,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.run_id = run_id
        self.runs_dir = runs_dir
        self.images_dir = runs_dir / run_id / "images"
        self.state_path = runs_dir / run_id / "state.json"
        self.on_progress = on_progress or (lambda _: None)
        self.delay = int(os.environ.get("SCENE_DELAY_SECONDS", "15"))
        self.max_retries = int(os.environ.get("SCENE_MAX_RETRIES", "3"))
        self.client = FlowKitClient()

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {
            "run_id": self.run_id,
            "status": "pending",
            "phase": "refs",
            "total_scenes": 0,
            "images_ready": 0,
            "current_scene": 0,
            "completed": [],
            "failed_scenes": [],
            "error": None,
        }

    def _save_state(self, state: dict[str, Any]) -> None:
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        self.on_progress(state)

    def run(self, scenes: list[dict[str, Any]], entities: list[dict[str, Any]] | None = None) -> None:
        state = self._load_state()
        state["status"] = "running"
        state["total_scenes"] = len(scenes)
        self._save_state(state)

        _start_flowkit_stack()
        try:
            self.client.ensure_ready()
            state["phase"] = "project"
            self._save_state(state)

            project_id = None
            for attempt in range(4):
                try:
                    project_id = self.client.create_project(title=f"Niche {self.run_id}", story="")
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt >= 3:
                        raise
                    state["error"] = f"create_project retry {attempt + 1}: {exc}"
                    self._save_state(state)
                    _restart_flowkit_stack()
                    self.client.ensure_ready(wait_sec=180)
                    time.sleep(15 * (attempt + 1))
            if not project_id:
                raise RuntimeError("create_project failed after retries")

            state["phase"] = "refs"
            self._save_state(state)

            refs_dir = refs_dir_from_env()
            verify_references(refs_dir)
            ref_media = upload_references(refs_dir, self.client, project_id=project_id)
            video_id = project_id  # FlowKit ties scenes to project context

            state["phase"] = "scenes"
            self._save_state(state)

            sorted_scenes = sorted(scenes, key=lambda s: int(s["scene_id"]))
            for scene in sorted_scenes:
                scene_id = int(scene["scene_id"])
                filename = f"scene_{scene_id:02d}.png"
                dest = self.images_dir / filename
                state["current_scene"] = scene_id
                self._save_state(state)

                if dest.exists() and dest.stat().st_size > 10_000:
                    if filename not in state["completed"]:
                        state["completed"].append(filename)
                        state["images_ready"] = len(state["completed"])
                        state["last_saved"] = filename
                        self._save_state(state)
                    continue

                entity_refs = scene.get("entity_refs") or []
                media_inputs = [ref_media[r] for r in entity_refs if r in ref_media]
                prompt = _sanitize_prompt(scene.get("prompt", ""), scene_id)

                last_err = ""
                for attempt in range(1, self.max_retries + 1):
                    try:
                        image_url, _ = self.client.generate_scene_image(
                            project_id=project_id,
                            scene_id=str(scene_id),
                            video_id=video_id,
                            prompt=prompt,
                            ref_media_ids=media_inputs,
                        )
                        self.client.download_url(image_url, dest)
                        if dest.stat().st_size < 10_000:
                            raise RuntimeError(f"Downloaded file too small: {dest}")
                        state["completed"].append(filename)
                        state["images_ready"] = len(state["completed"])
                        state["last_saved"] = filename
                        self._save_state(state)
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_err = str(exc)
                        prompt = _rewrite_prompt_safe(scene.get("prompt", ""))
                        if attempt == self.max_retries:
                            state["status"] = "failed"
                            state["error"] = f"Scene {scene_id}: {last_err}"
                            state["failed_scenes"].append(scene_id)
                            self._save_state(state)
                            raise
                        time.sleep(self.delay)

                time.sleep(self.delay)

            state["status"] = "complete"
            state["phase"] = "done"
            state["error"] = None
            self._save_state(state)
        except Exception as exc:  # noqa: BLE001
            state = self._load_state()
            state["status"] = "failed"
            state["error"] = str(exc)
            self._save_state(state)
            raise
        finally:
            _stop_flowkit_stack()


async def run_generation_async(
    run_id: str,
    scenes: list[dict[str, Any]],
    entities: list[dict[str, Any]] | None,
    runs_dir: Path,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    loop = asyncio.get_event_loop()
    gen = SequentialGenerator(run_id, runs_dir, on_progress=on_progress)
    await loop.run_in_executor(None, lambda: gen.run(scenes, entities))
