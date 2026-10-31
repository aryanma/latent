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
MODEL_REPOSITORY = "Qwen/Qwen3-8B-MLX-4bit"
MODEL_REVISION = "383413e909f3bc5303ce195ebbdf0339c5a1a2a3"
WEIGHT_SHA256 = "fcc83d7537bee76cc143be3e25f8954b816798f93528103db1cddb02977c5617"
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
        digest = hashlib.sha256((MODEL_DIR / "model.safetensors").read_bytes()).hexdigest()
        assert digest == WEIGHT_SHA256, "Model weight hash mismatch"
        start = time.perf_counter()
        self.model, self.tokenizer = load(str(MODEL_DIR), adapter_path=str(adapter_path) if adapter_path else None)
        mx.eval(self.model.parameters())
        self.load_seconds = time.perf_counter() - start

    def complete(self, messages, *, max_tokens=256, seed=42, temperature=0.0):
        # The pinned tokenizer template strips earlier text preceding </think>.
        # Use its plain ChatML delimiters while preserving every history byte.
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
            "history_renderer": "verbatim-chatml-v1",
            "peak_mlx_memory_bytes": mx.get_peak_memory(),
            "network_attempts": list(network_attempts),
        }
