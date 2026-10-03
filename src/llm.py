"""LLM access. Order: Groq free tier (open-weights Llama) -> local llama.cpp on the runner (Qwen2.5-7B, Apache-2.0)."""
import gc
import json
import logging
import os
import re
import time

import requests

log = logging.getLogger("llm")
_local = None


def _groq(cfg, messages, max_tokens, temperature, json_mode):
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")
    body = {"model": cfg["llm"]["groq_model"], "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    for _ in range(4):
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                          headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
        if r.status_code == 429:
            time.sleep(min(60, float(r.headers.get("retry-after", 10))))
            continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("Groq rate-limited")


def _get_local(cfg):
    global _local
    if _local is None:
        from huggingface_hub import hf_hub_download
        from llama_cpp import Llama
        path = hf_hub_download(cfg["llm"]["local_repo"], cfg["llm"]["local_file"])
        log.info("loading local LLM %s", path)
        _local = Llama(model_path=path, n_ctx=8192, n_threads=cfg["llm"]["n_threads"], verbose=False)
    return _local


def _local_chat(cfg, messages, max_tokens, temperature, json_mode):
    llm = _get_local(cfg)
    out = llm.create_chat_completion(
        messages=messages, max_tokens=max_tokens, temperature=temperature,
        response_format={"type": "json_object"} if json_mode else None)
    return out["choices"][0]["message"]["content"]


def chat(cfg, system, user, max_tokens=1500, temperature=0.8, json_mode=True):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last = None
    for prov in cfg["llm"]["provider_order"]:
        try:
            fn = _groq if prov == "groq" else _local_chat
            return fn(cfg, messages, max_tokens, temperature, json_mode)
        except Exception as e:  # noqa: BLE001
            log.warning("LLM provider %s failed: %s", prov, e)
            last = e
    raise RuntimeError(f"all LLM providers failed: {last}")


def _parse(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def ask_json(cfg, system, user, max_tokens=1500, validate=None, tries=3, temperature=0.8):
    err = None
    for i in range(tries):
        try:
            data = _parse(chat(cfg, system, user + (f"\n\nPrevious attempt was invalid ({err}). Return ONLY valid JSON." if err else ""),
                               max_tokens, temperature))
            if validate:
                validate(data)
            return data
        except Exception as e:  # noqa: BLE001
            err = str(e)[:150]
            log.warning("ask_json attempt %d/%d failed: %s", i + 1, tries, err)
    raise RuntimeError(f"LLM could not produce valid JSON: {err}")


def unload():
    global _local
    _local = None
    gc.collect()
