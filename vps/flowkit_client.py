"""HTTP client for local FlowKit agent (port 8100) — FlowKit 1.1.x API."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}


def _backoff_seconds(status: int, attempt: int) -> float:
    """403/429 need long pauses — Google Flow quota throttles after ~20-40 generations."""
    if status in {403, 429}:
        return min(900.0, 300.0 * (attempt + 1))
    return min(60.0, 10.0 * (attempt + 1))


class FlowKitClient:
    def __init__(self, base_url: str | None = None, timeout: float = 120.0) -> None:
        self.base_url = (base_url or os.environ.get("FLOWKIT_BASE_URL", "http://127.0.0.1:8100")).rstrip("/")
        self.timeout = timeout
        self.max_retries = int(os.environ.get("FLOWKIT_API_RETRIES", "10"))

    def health(self) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(f"{self.base_url}/health")
            resp.raise_for_status()
            return resp.json()

    def ensure_ready(self, wait_sec: int = 180) -> None:
        """Wait until extension is connected and /api/projects responds."""
        deadline = time.time() + wait_sec
        last_error = ""
        while time.time() < deadline:
            try:
                data = self.health()
                if not data.get("extension_connected"):
                    last_error = "extension not connected — open Chrome, Flow tab, connect extension"
                    time.sleep(5)
                    continue
                # Probe API (502 here means extension bridge is broken)
                with httpx.Client(timeout=30.0) as client:
                    probe = client.get(f"{self.base_url}/api/projects")
                if probe.status_code in RETRYABLE_STATUS:
                    last_error = f"GET /api/projects -> {probe.status_code}"
                    time.sleep(5)
                    continue
                if probe.is_success or probe.status_code == 404:
                    return
                last_error = f"GET /api/projects -> {probe.status_code}: {probe.text[:200]}"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            time.sleep(5)
        raise RuntimeError(
            f"FlowKit not ready after {wait_sec}s: {last_error}. "
            "On VPS: VNC -> start-chrome-flowkit -> open labs.google/fx/tools/flow -> "
            "curl http://127.0.0.1:8100/health must show extension_connected:true"
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        retries: int | None = None,
    ) -> dict[str, Any]:
        attempts = retries if retries is not None else self.max_retries
        last_err = ""
        for attempt in range(attempts):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.request(method, f"{self.base_url}{path}", json=json_body)
                if resp.status_code in RETRYABLE_STATUS and attempt + 1 < attempts:
                    last_err = f"{resp.status_code} {resp.text[:300]}"
                    time.sleep(_backoff_seconds(resp.status_code, attempt))
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code in RETRYABLE_STATUS and attempt + 1 < attempts:
                    last_err = f"{code} {exc.response.text[:300]}"
                    time.sleep(_backoff_seconds(code, attempt))
                    continue
                raise
            except httpx.RequestError as exc:
                last_err = str(exc)
                if attempt + 1 < attempts:
                    time.sleep(_backoff_seconds(0, attempt))
                    continue
                raise RuntimeError(f"FlowKit request failed: {last_err}") from exc
        raise RuntimeError(f"FlowKit request failed after {attempts} attempts: {last_err}")

    def create_project(self, title: str, story: str = "") -> str:
        payload = {"name": title, "story": story or None}
        data = self._request_json("POST", "/api/projects", json_body=payload)
        if "id" in data:
            return str(data["id"])
        if isinstance(data.get("project"), dict) and data["project"].get("id"):
            return str(data["project"]["id"])
        raise RuntimeError(f"Unexpected project create response: {data}")

    def upload_image(self, path: Path, project_id: str = "") -> str:
        payload = {
            "file_path": str(path.resolve()),
            "project_id": project_id,
            "file_name": path.name,
        }
        data = self._request_json("POST", "/api/flow/upload-image", json_body=payload)
        media_id = data.get("media_id") or data.get("mediaId")
        if media_id:
            return str(media_id)
        raw = data.get("raw") or data
        if isinstance(raw, dict):
            media_id = raw.get("mediaId") or raw.get("media_id")
            if media_id:
                return str(media_id)
        raise RuntimeError(f"No media_id in upload response: {data}")

    @staticmethod
    def _extract_image_url(data: dict[str, Any]) -> tuple[str, str]:
        media = data.get("media") or []
        if media:
            item = media[0]
            name = str(item.get("name") or "")
            media_id = name if _UUID_RE.match(name) else ""
            gen = item.get("image", {}).get("generatedImage", {})
            if not media_id:
                candidate = str(gen.get("mediaId") or "")
                if _UUID_RE.match(candidate):
                    media_id = candidate
            for field in ("fifeUrl", "imageUri", "encodedImage"):
                url = gen.get(field) or ""
                if url:
                    if not media_id:
                        match = re.search(
                            r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
                            str(url),
                            re.I,
                        )
                        if match:
                            media_id = match.group(1)
                    return str(url), media_id
            if media_id:
                return "", media_id

        for field in ("fifeUrl", "imageUri", "image_url", "imageUrl", "url"):
            url = data.get(field)
            if url:
                return str(url), str(data.get("media_id") or data.get("mediaId") or "")
        raise RuntimeError(f"No image URL in FlowKit response: {data}")

    def generate_scene_image(
        self,
        *,
        project_id: str,
        scene_id: str,
        video_id: str,
        prompt: str,
        ref_media_ids: list[str],
        orientation: str = "landscape",
    ) -> tuple[str, str]:
        del scene_id, video_id  # direct Flow API uses project + prompt only
        prompt = " ".join(str(prompt).split()).strip()
        if not prompt:
            raise RuntimeError("Refusing to generate image with empty prompt")
        aspect = (
            "IMAGE_ASPECT_RATIO_LANDSCAPE"
            if orientation.lower() in {"landscape", "horizontal"}
            else "IMAGE_ASPECT_RATIO_PORTRAIT"
        )
        body: dict[str, Any] = {
            "prompt": prompt,
            "project_id": project_id,
            "aspect_ratio": aspect,
        }
        if ref_media_ids:
            body["character_media_ids"] = ref_media_ids

        data = self._request_json(
            "POST", "/api/flow/generate-image", json_body=body, retries=self.max_retries
        )
        image_url, media_id = self._extract_image_url(data)
        if not image_url and media_id:
            image_url = self.get_media_url(media_id)
        if not image_url:
            raise RuntimeError(f"No image_url in FlowKit response: {data}")
        return image_url, media_id

    def get_media_url(self, media_id: str) -> str:
        data = self._request_json("GET", f"/api/flow/media/{media_id}")
        for field in ("fifeUrl", "servingUri", "imageUri", "url"):
            url = data.get(field)
            if url:
                return str(url)
        nested = data.get("image", {}).get("generatedImage", {})
        for field in ("fifeUrl", "imageUri"):
            url = nested.get(field)
            if url:
                return str(url)
        raise RuntimeError(f"No URL in media response for {media_id}: {data}")

    def download_url(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
