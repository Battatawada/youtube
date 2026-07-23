# Doodlytical — Channel Playbook

> Research from `config/seed_urls.json` inspiration channels (Jul 2026).  
> Feed this + `CHANNEL-GROWTH-STRATEGY-PROMPT.md` to NotebookLM before Phase 1 runs.

## Inspiration channels studied

| Channel | Handle | Example title | Format |
|---------|--------|---------------|--------|
| simple, actually | @simpleactuallyus | How to Sleep LESS hours and wake up FRESH (Science-Backed) | Mechanism + outcome promise |
| Obsessed Minds | @ObsessedMinds | Psychology of People Who Always Train Alone | Identity label + specific behavior |
| Mover's Odyssey | @moversodyssey | How Jumping Rope changes the Human Body | "How X changes Y" transformation arc |

**Doodlytical position:** Stick-figure psychology explainers (~15 min). Warmer and clearer than Obsessed Minds; less fitness-body than Mover's Odyssey; more narrative than simple, actually's listicle energy — but borrow their **specificity** and **identity hooks**.

---

## A. Title patterns (what earns clicks)

**Works in this niche:**
- Identity + behavior: "Psychology of People Who…", "Why You…"
- Paradox or counterintuition: "Sleep LESS and wake up FRESH", "Never Ask for Help"
- Entire-topic promise: "Entire [concept] in 15 mins" (Doodlytical format from `niche.json`)
- One sharp mechanism, not a syllabus: "Hypervigilance" beats "Understanding Anxiety Disorders"

**Avoid:**
- "Explained", "Deep Dive", "The Full Story", "Shocking", "Unbelievable"
- Generic self-help: "Unlock Your Potential", "Master Your Mind"
- Wikipedia chapter names with no human stake

**Doodlytical voice:** Curious, direct, slightly warm — not cold true-crime, not hype-bro. Titles should feel like a friend naming the pattern you already live with.

---

## B. Thumbnail patterns

**From comp set + stick-figure niche:**
- ONE hero metaphor (brain, mirror, phone, bed, gym, helping hand) — large, phone-readable
- Cream/beige background, bold black line art — not photoreal, not collage
- Quieter **left third** for 2–4 word overlay (composited in post — never baked into AI image)
- High contrast emotion on stick-figure face/pose
- NO giant "?", NO emoji badges, NO multi-panel evidence boards

**Overlay text (Layer 2):** Fragment of the title paradox — e.g. "NEVER ASK", "BRAIN LIES", "ALWAYS ALONE". Last word red accent.

---

## C. Hook / retention (first 60 seconds)

**Comp channels:** Obsessed Minds and simple, actually hook in **line 1** with a relatable identity claim or counterintuitive fact — they cannot rely on subscriber trust at small scale.

**Doodlytical rule (new/small channel):** Hook in first **30 seconds**. No "Psychology is the study of…" openings.

**Cold-open structure (0–60 sec spoken):**
1. **0–5 sec:** Pattern interrupt — mid-struggle moment ("You said you were fine. Your body disagreed.")
2. **5–15 sec:** Specific proof — number, study, behavior, quote fragment
3. **15–45 sec:** Open loop — BUT/THEREFORE ("Your brain treats help as danger, BUT the real cost is…, THEREFORE…")
4. **45–60 sec:** Second loop — deeper wrong turn left unanswered

**After hook:** Micro-curiosity every 15–20 sec; pattern interrupt every 2–3 min (new example, study, scenario).

---

## D. What NOT to copy

- Profanity-bait or trauma-bait titles
- 40–60 min iceberg marathons (Doodlytical = ~15 min)
- Slow textbook definitions before the viewer feels seen
- Duplicate angles on the same theme (see `topic_history.json` — one topic = one video forever)
- Photoreal thumbnails or cinematic rain/house stills (off-brand for stick figures)

---

## E. Metrics targets (honest — ignore owner self-watches)

| Signal | Healthy (growing channel) | Fix if bad |
|--------|---------------------------|------------|
| CTR | 5–8%+ psychology/self-improvement | Title + thumbnail first |
| Retention @ 30 sec | 30%+ | Cold open |
| Retention @ 3 min | 15%+ | First-act pacing |
| Avg view duration | 6–9+ min on 15 min video | Hook + micro-curiosity every 15–20 sec |

---

## F. Doodlytical constants (pipeline)

| Field | Value |
|-------|--------|
| Channel | Doodlytical `@doodlytical` |
| Host persona | Warm explainer narrator (no character name on-screen) |
| Tone | Clear, curious, grounded — no gore, no clinical coldness |
| Length | ~15 min (~2,100 words @ 140 wpm) |
| Visual | Minimal stick-figure line art, cream background |
| Primary TTS | `en-IE-EmilyNeural` (Azure documentary-narration) |
| Title format | Paradox-first OR "Entire X in 15 mins" — locked in hook package before script |
