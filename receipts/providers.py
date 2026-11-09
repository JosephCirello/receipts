"""Which endpoint a model name goes to, which key opens it, and what each token costs.

Keys come from the environment, or from the file named by RECEIPTS_ENV_FILE
(KEY=VALUE lines). This module never prints a key; `available()` says only
True or False per provider.

Prices are USD per million tokens, read from each provider's published price
page on the date given. A run's cost is its measured prompt and completion
tokens at these rates; every number in the cost finding comes from that.
"""
from __future__ import annotations

import os
from pathlib import Path

READ_ON = "2026-11-09"

# provider -> (prefixes, base_url or None for Anthropic's own SDK, key names tried in order, sampling)
# sampling: the temperature sent. The open models and Gemini take 0; the OpenAI and xAI reasoning
# models and the Claude 5.5 family reject a non-default temperature, so none is sent to them.
PROVIDERS = {
    "anthropic": {"prefixes": ("claude-",), "base_url": None, "keys": ("ANTHROPIC_API_KEY",), "temperature": None},
    "openai": {"prefixes": ("gpt-", "o1", "o3", "o4"), "base_url": "https://api.openai.com/v1", "keys": ("OPENAI_API_KEY",), "temperature": None},
    "google": {"prefixes": ("gemini-",), "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "keys": ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "temperature": 0},
    "xai": {"prefixes": ("grok-",), "base_url": "https://api.x.ai/v1", "keys": ("XAI_API_KEY", "GROK_API_KEY", "X_AI_API_KEY"), "temperature": None},
    "vultr": {"prefixes": (), "base_url": os.environ.get("RECEIPTS_BASE_URL", "https://api.vultrinference.com/v1"),
              "keys": ("RECEIPTS_API_KEY", "VULTR_INFERENCE_KEY"), "temperature": 0},
}

# (input, output) per 1M tokens, and where the number was read
PRICES = {
    # Vultr Serverless Inference bills every model at one rate: docs.vultr.com, "How do I monitor the usage and
    # cost of my Vultr Serverless Inference subscription", updated 26 Oct 2026
    "vultr": (0.55, 2.75, "docs.vultr.com serverless inference billing, updated 2026-10-26"),
    # Anthropic: platform.claude.com/docs/en/about-claude/pricing
    "claude-opus-5-5": (4.00, 20.00, "platform.claude.com pricing"),
    "claude-sonnet-5-5": (2.00, 10.00, "platform.claude.com pricing"),
    "claude-haiku-5-5": (0.10, 0.50, "platform.claude.com pricing (prompts up to 100K tokens)"),
    # OpenAI: developers.openai.com/api/docs/pricing (standard tier)
    "gpt-6-astra": (10.00, 50.00, "developers.openai.com pricing"),
    "gpt-6.1-sol": (2.00, 10.00, "developers.openai.com pricing"),
    "gpt-6-sol": (2.00, 10.00, "developers.openai.com pricing"),
    "gpt-6.1-terra": (1.00, 5.00, "developers.openai.com pricing"),
    "gpt-6-luna": (0.10, 0.50, "developers.openai.com pricing"),
    # Google: aistudio.google.com/docs/pricing (paid tier, prompts under 200K tokens)
    "gemini-3.1-pro-preview": (2.00, 12.00, "aistudio.google.com pricing"),
    "gemini-3.8-flash": (0.75, 3.75, "aistudio.google.com pricing (rate through 2026-12-31)"),
    "gemini-3.5-flash-lite": (0.30, 2.50, "aistudio.google.com pricing"),
    # xAI: docs.x.ai/docs/models (prompts under 200K tokens)
    "grok-4.7": (2.00, 6.00, "docs.x.ai models"),
    "grok-4.3": (1.25, 2.50, "docs.x.ai models"),
}

_LOADED = False


def load_env_file() -> None:
    """Read KEY=VALUE lines from RECEIPTS_ENV_FILE into the environment (existing values win)."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    p = Path(os.environ.get("RECEIPTS_ENV_FILE") or str(Path(__file__).resolve().parent.parent / ".env"))
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and not os.environ.get(k):
                os.environ[k] = v
    # the Vultr key file is read whether or not an env file exists (it was behind the env-file check once; measured 2026-11-09)
    keyfile = Path(os.environ.get("RECEIPTS_KEYFILE", str(Path.home() / ".vultr_inference_key")))
    if keyfile.exists() and not os.environ.get("VULTR_INFERENCE_KEY"):
        os.environ["VULTR_INFERENCE_KEY"] = keyfile.read_text(encoding="utf-8").strip()


def provider_for(model: str) -> str:
    for name, p in PROVIDERS.items():
        if any(model.startswith(x) for x in p["prefixes"]):
            return name
    return "vultr"


def key_for(provider: str) -> str | None:
    load_env_file()
    for k in PROVIDERS[provider]["keys"]:
        v = os.environ.get(k)
        if v:
            return v
    return None


def available() -> dict[str, bool]:
    """Which providers have a key. Booleans only."""
    return {name: key_for(name) is not None for name in PROVIDERS}


def price_for(model: str) -> tuple[float, float, str] | None:
    if model in PRICES:
        return PRICES[model]
    if provider_for(model) == "vultr":
        return PRICES["vultr"]
    return None


def usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    p = price_for(model)
    if not p:
        return None
    return round(prompt_tokens * p[0] / 1e6 + completion_tokens * p[1] / 1e6, 6)
