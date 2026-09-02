# -*- coding: utf-8 -*-
"""Minimal OpenAI-compatible chat client for a local Ollama server.

Mirrors fair_ocean_agent's llm/ design principles (see its README) without
importing that package directly (separate repo/venv): provider-independent
wire protocol (never an OpenAI-operated host), model set explicitly by the
caller (no hard-coded default), JSON-mode retry, and -- critically for the
"don't burn tokens" goal of this pipeline -- callers are expected to keep
prompts short (abstract-only triage, keyword-anchored spans only) rather
than feeding full papers to the model.

Uses qwen3:4b-instruct-16k specifically because fair_ocean_agent's own
README documents a real bug: Ollama's OpenAI-compatible endpoint silently
ignores the `num_ctx` request parameter, capping every model at 4096
tokens regardless of what's requested -- this -16k variant has num_ctx
baked into its own Modelfile instead, so it actually gets a working
16k-token context. See fair_ocean_agent/README.md "Text-extraction speed
fix" section for the full story.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

import requests

# Ollama (Mac dev default) speaks this same OpenAI-compatible wire protocol
# at :11434/v1 with its own model tags (e.g. "qwen3:4b-instruct-16k", a
# custom Modelfile build with num_ctx actually baked in -- see the module
# docstring). vLLM (cluster GPU) speaks the identical protocol at whatever
# --port it's started with (run_extraction.sbatch uses :8000) and loads a
# real Hugging Face Hub repo id instead of an Ollama tag (e.g.
# "Qwen/Qwen3-4B-Instruct-2507"). Both endpoints are env-var overridable so
# the exact same script runs unmodified on a Mac against Ollama or on the
# cluster against vLLM -- only cluster/local.env (gitignored, cluster-side)
# differs.
DEFAULT_BASE_URL = os.environ.get("GENETIC_TRACTABILITY_LLM_BASE_URL", "http://localhost:11434/v1")
DEFAULT_MODEL = os.environ.get("GENETIC_TRACTABILITY_LLM_MODEL", "qwen3:4b-instruct-16k")

_session = requests.Session()


class LLMError(RuntimeError):
    pass


def chat(
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    retries: int = 2,
    timeout: int = 120,
) -> str:
    """One chat completion call; returns the raw assistant message text."""
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = _session.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001 -- surfaced via LLMError below
            last_err = e
            # Printed here (not just raised) because a caller that catches
            # LLMError and silently falls back (scripts 13/15 both do, to
            # keep one bad paper from killing a whole batch) would
            # otherwise produce zero log output on failure -- confirmed as
            # the real explanation for a job that looked "stopped" with an
            # empty .err: the LLM server was actually failing/timing out on
            # every call, each one retried silently for minutes, with
            # nothing ever printed to say why.
            print(f"  [llm_client] attempt {attempt + 1}/{retries + 1} failed: {e}", flush=True)
            time.sleep(1.0 * (attempt + 1))
    raise LLMError(f"LLM call failed after {retries + 1} attempts: {last_err}")


def strip_think_tags(text: str) -> str:
    """qwen3 instruct models sometimes emit <think>...</think> scratch text
    before the real answer even at temperature 0; drop it defensively."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def extract_json(text: str) -> Optional[dict | list]:
    """Best-effort JSON extraction: strip think-tags/code fences, then find
    the first balanced {...} or [...] block and parse it."""
    text = strip_think_tags(text)
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in [("{", "}"), ("[", "]")]:
        start = text.find(open_ch)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == open_ch:
                depth += 1
            elif text[i] == close_ch:
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    return None


def extract_json_array_lenient(text: str) -> list:
    """Like extract_json, but recovers as many top-level array elements as
    possible even if the response was cut off mid-object by max_tokens --
    confirmed as a real failure mode live: a 6-attempt array truncated
    during the 6th object caused extract_json's balanced-bracket fallback
    to return only the FIRST object as a bare dict (the outer '[' never
    found its matching ']'), silently discarding 5 valid, verified attempts.
    Scans for the first top-level '[', then walks its immediate child
    '{...}' objects by brace depth, json.loads'ing each independently and
    keeping only the ones that parse -- a trailing truncated object is
    dropped, but everything complete before it survives."""
    stripped = strip_think_tags(text)
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped.strip(), flags=re.MULTILINE)
    start = stripped.find("[")
    if start == -1:
        return []
    items = []
    depth = 0
    obj_start = None
    in_string = False
    escape = False
    for i in range(start + 1, len(stripped)):
        ch = stripped[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    items.append(json.loads(stripped[obj_start:i + 1]))
                except json.JSONDecodeError:
                    pass
                obj_start = None
        elif ch == "]" and depth == 0:
            break
    return items


def ping(base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL) -> bool:
    try:
        out = chat("You are a test.", "Reply with exactly: OK", model=model, base_url=base_url, max_tokens=10)
        return "OK" in out
    except LLMError:
        return False
