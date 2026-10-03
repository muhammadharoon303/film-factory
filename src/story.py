"""Story -> outline -> scenes (dialogue, narration, visual prompts) -> YouTube metadata. Staged for small-model reliability."""
import logging
import re

from .llm import ask_json

log = logging.getLogger("story")

SYSTEM = ("You are an award-winning screenwriter of short films. Everything you write is 100% original: invent new "
          "character names, places and plots. NEVER use existing franchises, characters, brands, song lyrics, or real "
          "people. {safe} Output ONLY valid JSON.")
MOODS = "dark, calm, tense, hopeful, epic, mysterious, playful"


def _system(cfg):
    safe = "Keep content suitable for a general audience: no gore, no sexual content, no hate." \
        if cfg["film"].get("family_friendly", True) else ""
    return SYSTEM.format(safe=safe)


def build_film(cfg, prev_titles):
    f, lang = cfg["film"], cfg["channel"]["language_name"]
    n = max(5, min(30, round(f["target_duration_sec"] / f["seconds_per_scene"])))
    words = int(f["target_duration_sec"] * 2.2 / n)
    sysmsg = _system(cfg)

    def v_concept(d):
        assert d["title"].strip() and len(d["characters"]) >= 1
        for c in d["characters"]:
            assert c["name"] and c["appearance"]

    concept = ask_json(cfg, sysmsg, f"""Create an original short film concept.
Genre: {f['genre']}. Tone: {f['tone']}. {('Theme hint: ' + f['theme_hint']) if f.get('theme_hint') else ''}
Write title, character names and 'ending' in {lang}.
Do NOT reuse ideas/titles from: {prev_titles or 'none yet'}.
Return JSON: {{"title": str, "logline": str, "setting": str,
"characters": [{{"name": str, "role": str, "appearance": "max 15 words, ENGLISH, purely visual (age, hair, clothes)"}}],
"ending": str, "music_mood": one of [{MOODS}]}}
Use 2 or 3 characters.""", max_tokens=900, validate=v_concept)

    names = [c["name"] for c in concept["characters"]]

    def v_outline(d):
        assert len(d["scenes"]) >= n - 2 and all(s["summary"] for s in d["scenes"])

    outline = ask_json(cfg, sysmsg, f"""Film: "{concept['title']}" - {concept['logline']}
Setting: {concept['setting']}. Characters: {', '.join(names)}. Ending: {concept['ending']}
Write a {n}-scene outline with a clear arc (setup, rising conflict, climax, resolution). Language: {lang}.
Return JSON: {{"scenes": [{{"summary": "one or two sentences"}}]}} with exactly {n} scenes.""",
                       max_tokens=1800, validate=v_outline)["scenes"][:n]

    outline_txt = "\n".join(f"{i + 1}. {s['summary']}" for i, s in enumerate(outline))
    scenes, prev = [], "(this is the opening scene)"
    for i, s in enumerate(outline):
        def v_scene(d):
            assert d["lines"] and d["shots"]
            assert all(l["text"].strip() for l in d["lines"])
            assert all(sh["visual_prompt"].strip() for sh in d["shots"])
        try:
            d = ask_json(cfg, sysmsg, f"""Film: "{concept['title']}" ({concept['setting']}). Characters: {', '.join(names)}.
Full outline:
{outline_txt}
Previous scene: {prev}
NOW WRITE SCENE {i + 1} of {n}: {s['summary']}
Rules:
- Spoken lines total about {words} words, in {lang}. Mix narration and dialogue. "speaker" is "NARRATOR" or an exact character name.
- Exactly {f['shots_per_scene']} shots. Each "visual_prompt" is ENGLISH, max 28 words, one still image: subject, action, camera angle, lighting. Mention characters by exact name. No text or letters in the image.
Return JSON: {{"lines": [{{"speaker": str, "text": str}}], "shots": [{{"visual_prompt": str}}]}}""",
                         max_tokens=900, validate=v_scene)
        except Exception as e:  # noqa: BLE001
            log.warning("scene %d failed, skipping: %s", i + 1, e)
            continue
        lines = []
        for l in d["lines"]:
            sp = l["speaker"] if l.get("speaker") in names else "NARRATOR"
            lines.append({"speaker": sp, "text": l["text"].strip()})
        scenes.append({"summary": s["summary"], "lines": lines, "shots": d["shots"][:f["shots_per_scene"]]})
        prev = s["summary"]
    if len(scenes) < max(3, n // 2):
        raise RuntimeError(f"only {len(scenes)}/{n} scenes were written")
    return {"concept": concept, "scenes": scenes}


def build_metadata(cfg, film):
    c, lang = film["concept"], cfg["channel"]["language_name"]
    synopsis = " ".join(s["summary"] for s in film["scenes"])[:1500]

    def v(d):
        assert d["title"].strip() and d["description"].strip() and d["tags"]
    try:
        m = ask_json(cfg, _system(cfg), f"""Write YouTube metadata for the short film "{c['title']}". Genre: {cfg['film']['genre']}.
Synopsis: {synopsis}
Language: {lang}. Honest, no clickbait lies.
Return JSON: {{"title": "max 70 chars", "description": "2 short paragraphs, no spoilers of the ending, max 700 chars",
"tags": ["8 to 14 short tags"], "hashtags": ["#three", "#to", "#five"],
"thumbnail_prompt": "ENGLISH visual description, max 28 words, one striking image, no text",
"thumbnail_text": "max 4 words, {lang}"}}""", max_tokens=700, validate=v)
    except Exception as e:  # noqa: BLE001
        log.warning("metadata fallback: %s", e)
        m = {"title": c["title"], "description": c["logline"], "tags": [cfg["film"]["genre"]],
             "hashtags": ["#shortfilm", "#aifilm"], "thumbnail_prompt": film["scenes"][0]["shots"][0]["visual_prompt"],
             "thumbnail_text": c["title"][:24]}
    clean = lambda s: re.sub(r"[<>]", "", str(s)).strip()  # noqa: E731
    m["title"] = clean(m["title"])[:95]
    m["description"] = clean(m["description"])[:2500]
    tags = [clean(t).lstrip("#") for t in m["tags"]] + cfg["youtube"]["default_tags"]
    out, total = [], 0
    for t in tags:                                   # YouTube: total tags <= 500 chars
        if t and t not in out and total + len(t) + 1 < 450:
            out.append(t)
            total += len(t) + 1
    m["tags"] = out
    m["hashtags"] = [("#" + re.sub(r"\W", "", h)) for h in m.get("hashtags", [])][:5]
    return m
