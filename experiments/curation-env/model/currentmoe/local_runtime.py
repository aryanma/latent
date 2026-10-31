"""Resident local Qwen runtime for controlled research baselines.

No output repair, remote inference, tokenizer mutation, or model tuning.
The explicit non-thinking prefill matches the official Qwen3 template.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "model"
MODEL_REPOSITORY = "mlx-community/Qwen3.6-35B-A3B-4bit"
MODEL_REVISION = "38740b847e4cb78f352aba30aa41c76e08e6eb46"
WEIGHT_SHAS = {'model-00001-of-00004.safetensors': '09f3e6ecb0b7af6e6a38bc8169a134c821b0924c2679b2bb8f4426ad38d032b8', 'model-00002-of-00004.safetensors': '31dcdb1c49eebdb1505bd14e3cb33f9cf900bd2546b638f2464694ae763a033f', 'model-00003-of-00004.safetensors': '3e66de06a1f03dade16a612a368cfce4a4c9caa4efd7d28185454384082cec03', 'model-00004-of-00004.safetensors': 'a5d0cf03519c26f8b506df6b0ba60526e5c08c8cea22d0c21ce92950e58a5422'}
NONTHINKING_PREFILL = "<think>\n\n</think>\n\n"

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
network_attempts = []


class NetworkBlocked(BaseException):
    pass


def _guard(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        network_attempts.append(event)
        raise NetworkBlocked("Network access forbidden during local model baseline")


sys.addaudithook(_guard)

import mlx.core as mx
from mlx_lm import stream_generate, load
from mlx_lm.sample_utils import make_sampler


class LocalQwen:
    def __init__(self, adapter_path=None):
        for filename, expected in WEIGHT_SHAS.items():
            digest = hashlib.sha256()
            with (MODEL_DIR / filename).open("rb") as source:
                for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                    digest.update(chunk)
            assert digest.hexdigest() == expected, "Model shard hash mismatch: " + filename
        start = time.perf_counter()
        self.model, self.tokenizer = load(str(MODEL_DIR), adapter_path=str(adapter_path) if adapter_path else None)
        mx.eval(self.model.parameters())
        self.load_seconds = time.perf_counter() - start

    def complete(self, messages, *, max_tokens=256, seed=42, temperature=0.0):
        # Native Qwen3.6 nonthinking ChatML equivalence is verified in
        # native-template-verification.json. Preserve raw message bytes instead
        # of the native template's whitespace trimming/reasoning-span splitting.
        assert all(m["role"] in {"system", "user", "assistant"} and isinstance(m["content"], str) for m in messages)
        prompt = "".join(f'<|im_start|>{m["role"]}\n{m["content"]}<|im_end|>\n' for m in messages)
        prompt += "<|im_start|>assistant\n" + NONTHINKING_PREFILL
        assert all(m["content"] in prompt for m in messages), "Message content was lost"
        if len(self.tokenizer.encode(prompt)) + max_tokens > 32768:
            raise ValueError("Context budget exceeded; history was not truncated")
        mx.random.seed(seed)
        start = time.perf_counter()
        pieces, generated_token_ids, final = [], [], None
        for response in stream_generate(self.model, self.tokenizer, prompt=prompt,
                                        max_tokens=max_tokens, sampler=make_sampler(temp=temperature)):
            pieces.append(response.text)
            generated_token_ids.append(int(response.token))
            final = response
        raw = "".join(pieces)
        mx.synchronize()
        elapsed = time.perf_counter() - start
        try:
            parsed = json.loads(raw)
            parse_error = None
        except (ValueError, TypeError) as exc:
            parsed = None
            parse_error = str(exc)
        return {
            "raw": raw, "parsed": parsed, "parse_error": parse_error,
            "latency_seconds": elapsed,
            "prompt_tokens": final.prompt_tokens,
            "generation_tokens": final.generation_tokens,
            "generation_token_ids": generated_token_ids,
            "finish_reason": final.finish_reason,
            "prompt_text": prompt,
            "max_tokens": max_tokens, "seed": seed, "temperature": temperature,
            "enable_thinking": False, "explicit_assistant_prefill": NONTHINKING_PREFILL,
            "history_renderer": "qwen3.6-native-compatible-verbatim-chatml-v1",
            "peak_mlx_memory_bytes": mx.get_peak_memory(),
            "network_attempts": list(network_attempts),
        }
