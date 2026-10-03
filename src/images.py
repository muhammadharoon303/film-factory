"""Images: Stable Diffusion 1.5 + LCM-LoRA (4 steps) on CPU. Falls back to a gradient card if a render fails."""
import logging
import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .utils import retry

log = logging.getLogger("images")
_pipe = None
NEG_NOTE = "no text, no watermark"


def _load(cfg):
    global _pipe
    if _pipe is None:
        import torch
        from diffusers import DiffusionPipeline, LCMScheduler
        torch.set_num_threads(os.cpu_count() or 2)
        kw = dict(torch_dtype=torch.float32, safety_checker=None, requires_safety_checker=False)
        try:
            pipe = DiffusionPipeline.from_pretrained(cfg["images"]["base_model"], variant="fp16", **kw)
        except Exception:  # noqa: BLE001
            pipe = DiffusionPipeline.from_pretrained(cfg["images"]["base_model"], **kw)
        pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
        pipe.load_lora_weights(cfg["images"]["lcm_lora"])
        pipe.fuse_lora()
        pipe.set_progress_bar_config(disable=True)
        _pipe = pipe
    return _pipe


def unload():
    global _pipe
    _pipe = None
    import gc
    gc.collect()


def _fallback(path, w, h, seed):
    rnd = random.Random(seed)
    top, bot = [tuple(rnd.randint(10, 90) for _ in range(3)) for _ in range(2)]
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] * (1 - k) + bot[i] * k) for i in range(3)))
    img.filter(ImageFilter.GaussianBlur(2)).save(path)


def _render(cfg, prompt, seed, path):
    import torch
    im = cfg["images"]
    pipe = _load(cfg)
    g = torch.Generator("cpu").manual_seed(seed)
    img = pipe(prompt=prompt, num_inference_steps=im["steps"], guidance_scale=1.0,
               width=im["width"], height=im["height"], generator=g).images[0]
    img.save(path)


def _prompt(cfg, film, visual):
    apps = [f"{c['appearance']}" for c in film["concept"]["characters"] if c["name"].lower() in visual.lower()]
    return ", ".join([visual] + apps + [cfg["film"]["visual_style"]])


def generate_shots(cfg, film, work):
    im = cfg["images"]
    base_seed = random.randint(0, 2**31 - 1)
    k = 0
    for si, scene in enumerate(film["scenes"]):
        for hi, shot in enumerate(scene["shots"]):
            path = Path(work) / f"shot_{si:02}_{hi}.png"
            prompt = _prompt(cfg, film, shot["visual_prompt"])
            try:
                retry(lambda: _render(cfg, prompt, base_seed + k, path), attempts=3, delay=3, what=f"image {si}.{hi}")
            except Exception as e:  # noqa: BLE001
                log.error("image failed, using fallback card: %s", e)
                _fallback(path, im["width"], im["height"], base_seed + k)
            shot["image"] = str(path)
            k += 1
            log.info("image %d done", k)


def make_thumbnail(cfg, film, meta, work):
    im = cfg["images"]
    raw, out = Path(work) / "thumb_raw.png", Path(work) / "thumbnail.jpg"
    try:
        retry(lambda: _render(cfg, f"{meta['thumbnail_prompt']}, {cfg['film']['visual_style']}, dramatic poster composition",
                              random.randint(0, 2**31 - 1), raw), attempts=2, what="thumbnail")
        img = Image.open(raw).convert("RGB")
    except Exception as e:  # noqa: BLE001
        log.warning("thumbnail fallback: %s", e)
        img = Image.open(film["scenes"][0]["shots"][0]["image"]).convert("RGB")
    img = img.resize((1280, 720), Image.LANCZOS)
    text = (meta.get("thumbnail_text") or film["concept"]["title"]).upper()[:28]
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 110)
    except OSError:
        font = ImageFont.load_default()
    d = ImageDraw.Draw(img)
    words, lines, cur = text.split(), [], ""
    for w in words:
        if d.textlength((cur + " " + w).strip(), font=font) > 1150 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    y = 720 - 60 - 125 * len(lines)
    for ln in lines:
        d.text((60, y), ln, font=font, fill="white", stroke_width=8, stroke_fill="black")
        y += 125
    img.save(out, quality=90)
    return str(out)
