"""
Ollama LLM Client
==================
Thin wrapper around the Ollama /api/generate endpoint.
Prompt construction and business logic live outside this module.

PREREQUISITES:
    - Ollama installed and running: https://ollama.com
    - At least one model pulled, e.g.: ollama pull llama3.2

ENVIRONMENT VARIABLES (.env):
    OLLAMA_HOST  = http://localhost:11434   (optional, default shown)
    OLLAMA_MODEL = llama3.2                 (optional, fallback if not passed)
"""

import json
import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_HOST  = os.environ.get("OLLAMA_HOST",  "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def list_local_models(host: str = DEFAULT_HOST) -> list[str]:
    """
    Returns the names of all models available in the local Ollama instance.

    Args:
        host: Ollama base URL.

    Returns:
        Sorted list of model name strings (e.g. ['llama3.2', 'mistral']).

    Raises:
        ConnectionError: If Ollama is not reachable.
    """
    try:
        response = requests.get(f"{host}/api/tags", timeout=5)
        response.raise_for_status()
        return sorted(m["name"] for m in response.json().get("models", []))
    except requests.exceptions.ConnectionError:
        raise ConnectionError(
            f"Cannot reach Ollama at {host}. Is 'ollama serve' running?"
        )


def is_model_available(model: str, host: str = DEFAULT_HOST) -> bool:
    """
    Checks whether a specific model is available locally.

    Args:
        model: Model name (e.g. 'llama3.2', 'mistral:latest').
        host:  Ollama base URL.

    Returns:
        True if the model is found, False otherwise.
    """
    try:
        available = list_local_models(host)
        return any(m.startswith(model.split(":")[0]) for m in available)
    except ConnectionError:
        return False


def pull_model(model: str, host: str = DEFAULT_HOST) -> None:
    """
    Pulls a model from the Ollama registry if not available locally.

    Args:
        model: Model name (e.g. 'llama3.2', 'mistral').
        host:  Ollama base URL.
    """
    logger.info(f"Pulling model '{model}' – this may take a few minutes...")
    response = requests.post(
        f"{host}/api/pull",
        json={"name": model},
        stream=True,
        timeout=600
    )
    response.raise_for_status()
    for line in response.iter_lines():
        if line:
            data = json.loads(line)
            status = data.get("status", "")
            if status == "success":
                logger.info(f"Model '{model}' pulled successfully.")
            elif status:
                print(".", end="", flush=True)  # ← ein Punkt pro chunk
    print()


# ──────────────────────────────────────────────
# Core query
# ──────────────────────────────────────────────

def _query_blocking(host: str, payload: dict, timeout: int) -> str:
    """Sends a non-streaming request and returns the full response at once."""
    response = requests.post(f"{host}/api/generate", json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"Ollama error: {data['error']}")
    return data.get("response", "").strip()


def _query_streaming(host: str, payload: dict, timeout: int) -> str:
    """Sends a streaming request, prints tokens to stdout, returns full text."""
    tokens = []
    with requests.post(
        f"{host}/api/generate", json=payload, stream=True, timeout=timeout
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            if "error" in chunk:
                raise RuntimeError(f"Ollama error: {chunk['error']}")
            token = chunk.get("response", "")
            print(token, end="", flush=True)
            tokens.append(token)
            if chunk.get("done"):
                break
    return "".join(tokens).strip()


def query_ollama(
    prompt: str,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
    temperature: float = 0.3,
    stream: bool = True,
    timeout: int = 240,
) -> str:
    """
    Sends a prompt to a local Ollama model and returns the response.

    Args:
        prompt:      The full prompt string to send.
        model:       Ollama model name (e.g. 'llama3.2', 'mistral').
        host:        Ollama base URL.
        temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).
        stream:      If True, tokens are printed to stdout as they arrive.
        timeout:     HTTP request timeout in seconds.

    Returns:
        Complete response string from the model.

    Raises:
        ConnectionError: If Ollama is not reachable.
        ValueError:      If the requested model is not available locally.
        RuntimeError:    If the Ollama API returns an error.
    """
    if not is_model_available(model, host):
        logger.info(f"Model '{model}' not found locally – pulling ...")
        pull_model(model, host)

    payload = {
        "model":   model,
        "prompt":  prompt,
        "stream":  stream,
        "options": {"temperature": temperature},
    }

    logger.info(f"Querying '{model}' (stream={stream}) ...")
    try:
        return _query_streaming(host, payload, timeout) if stream else _query_blocking(host, payload, timeout)
    except requests.exceptions.ConnectionError:
        raise ConnectionError(
            f"Cannot reach Ollama at {host}. Is 'ollama serve' running?"
        )


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("Available models:", list_local_models())

    result = query_ollama(
        prompt="Hello world",
        model=DEFAULT_MODEL,
        stream=True,
    )
    print(result)