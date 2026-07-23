# Channel Growth Strategy — Doodlytical Pipeline Upgrade

> `@` this file in future chats. Adapted from the Criminally Drawn true-crime upgrade for **psychology stick-figure** (`@doodlytical`).

**Companion:** `config/CHANNEL-PLAYBOOK.md` (inspiration research from seed channels).

---

## Shared infra: Azure Speech TTS

All channels share one **Azure Speech** account.

- Free tier: **500,000 characters/month** (~25 full-length videos across ALL channels).
- Budget: ~12–15k characters per ~15 min Doodlytical video → plan **~8 videos/channel/month** if splitting 3 ways.
- Secrets: `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` (e.g. `centralindia`).
- Config: `tts_provider: "azure"`, `tts_modulation: true`, `tts_merge_chunks: true`, `tts_azure_style_degree: 0.9`, `tts_rate: "-7%"`.
- **Edge TTS** = fallback when Azure fails or quota exhausted.

---

## Pipeline order (hook-first)

Phase 1:

1. **Topic pick** — fresh topic, not in `topic_history.json`
2. **Web research** (NotebookLM + seed reference channels)
3. **Hook package** (`story_hook_package.txt`) → JSON: `title`, `cold_open`, `thumbnail_text`, `thumbnail_scene`
4. **Full script** (`story_generation.txt`) — paste `cold_open` verbatim, then continue
5. **Image prompts** + scenes
6. **SEO** (`youtube_seo.txt`) — title **LOCKED** from hook package
7. **Thumbnail** — refine `thumbnail_scene`; text composited in post

Phase 2: Azure TTS with modulation  
Phase 3: Flow images + thumbnail base  
Post: `thumbnail_compose.py` burns overlay text

---

## Per-channel customization (Doodlytical)

| Field | Value |
|-------|--------|
| `{CHANNEL_NAME}` | Doodlytical |
| `{CHANNEL_HANDLE}` | @doodlytical |
| `{HOST_NAME}` | (warm narrator — no on-screen host name) |
| `{CHANNEL_TONE}` | Warm curious explainer; no jargon; no gore-bait |
| `{INSPIRATION_CHANNELS}` | @simpleactuallyus, @ObsessedMinds, @moversodyssey |
| `{PRIMARY_VOICE}` | en-IE-EmilyNeural |
| `{VIDEO_LENGTH}` | ~15 min |
| `{VISUAL_STYLE}` | Minimal stick-figure line art, cream background |

---

## Files (source of truth in repo)

```
config/CHANNEL-PLAYBOOK.md
config/prompts/story_hook_package.txt
config/prompts/story_generation.txt
config/prompts/youtube_seo.txt
config/prompts/thumbnail.txt
config/prompts/topics_finding.txt
config/pipeline.json
config/topic_history.json
src/tts_narration.py
src/azure_tts.py
src/thumbnail_compose.py
src/phase1_script.py
src/phase2_audio.py
```

---

## Agent checklist

1. Read this file + `context.md` + `config/CHANNEL-PLAYBOOK.md`.
2. Verify hook-first Phase 1 order and locked SEO title.
3. First Azure run: log character estimate; warn if monthly quota exceeded.
4. First video after upgrade: manually review hook (60 sec), thumbnail at phone size, title CTR fit.

---

## Azure quota math (shared across 3 channels)

- 500,000 chars / month total
- ~13,000 chars per 15-min video (avg)
- **~38 videos/month max** → ~12 per channel if equal
- Save quota: `tts_merge_chunks: true`, avoid re-running Phase 2, keep scripts tight
