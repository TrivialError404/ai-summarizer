"""
Ollama LLM Client
==================
Thin wrapper around the Ollama /api/generate endpoint.
Prompt construction and business logic live outside this module.

PREREQUISITES:
    - Ollama installed and running: https://ollama.com

ENVIRONMENT VARIABLES (.env):
    OLLAMA_HOST  = http://localhost:11434   (optional, default shown)
    OLLAMA_MODEL = llama3.2                 (optional, fallback if not passed)
"""

import json
import logging
import os
import time
import psutil

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
    Logs start and end, with a progress indicator while waiting.

    Args:
        model: Model name (e.g. 'llama3.2', 'mistral').
        host:  Ollama base URL.
    """
    logger.info(f"Pulling model '{model}' - this may take a few minutes...")
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
                print(".", end="", flush=True)
    print()


# ──────────────────────────────────────────────
# System metrics
# ──────────────────────────────────────────────

def _collect_system_metrics() -> dict:
    """
    Collects current system resource usage.

    Returns:
        Dict with memory_usage_mb, cpu_usage_percent, and gpu_usage if available.
    """
    metrics = {
        "memory_usage_mb": round(psutil.Process().memory_info().rss / 1024 / 1024, 2),
        "cpu_usage_percent": psutil.cpu_percent(interval=0.1),
        "gpu_usage": None,
    }

    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            metrics["gpu_usage"] = {
                "utilization_percent": int(parts[0]),
                "memory_used_mb":      int(parts[1]),
                "memory_total_mb":     int(parts[2]),
            }
    except Exception:
        pass  # No GPU or nvidia-smi not available

    return metrics


# ──────────────────────────────────────────────
# Core query
# ──────────────────────────────────────────────

def _query_blocking(host: str, payload: dict, timeout: int, collect_metrics: bool) -> dict:
    """
    Sends a non-streaming request and returns response with optional metrics.

    Args:
        host:             Ollama base URL.
        payload:          Request payload dict.
        timeout:          HTTP timeout in seconds.
        collect_metrics:  Whether to collect and return performance metrics.

    Returns:
        Dict with 'response' and optionally token/latency/system metrics.
    """
    t_request_start = time.perf_counter()
    response = requests.post(f"{host}/api/generate", json=payload, timeout=timeout)
    response.raise_for_status()
    t_request_end = time.perf_counter()

    data = response.json()
    if "error" in data:
        raise RuntimeError(f"Ollama error: {data['error']}")

    response = data.get("response", "").strip()
    result  = {"response": response}

    if collect_metrics:
        request_time   = t_request_end - t_request_start
        input_tokens   = data.get("prompt_eval_count", 0)
        output_tokens  = data.get("eval_count", 0)
        total_tokens   = input_tokens + output_tokens

        # Ollama returns durations in nanoseconds
        model_load_ns  = data.get("load_duration", 0)
        eval_ns        = data.get("eval_duration", 0)

        tokens_per_sec = round(output_tokens / (eval_ns / 1e9), 2) if eval_ns > 0 else None
        time_per_token = round((eval_ns / 1e9) / output_tokens, 4) if output_tokens > 0 else None

        result["metrics"] = {
            "token": {
                "input_tokens":  input_tokens,
                "output_tokens": output_tokens,
                "total_tokens":  total_tokens,
            },
            "latency": {
                "request_time":       round(request_time, 3),
                "time_to_first_token": None,  # Not available in blocking mode
                "time_per_token":     time_per_token,
                "tokens_per_second":  tokens_per_sec,
            },
            "system": {
                "model_load_time_s": round(model_load_ns / 1e9, 3),
                **_collect_system_metrics(),
            },
        }

    return result


def _query_streaming(host: str, payload: dict, timeout: int, collect_metrics: bool) -> dict:
    """
    Sends a streaming request, prints tokens to stdout, returns response with optional metrics.

    Args:
        host:             Ollama base URL.
        payload:          Request payload dict.
        timeout:          HTTP timeout in seconds.
        collect_metrics:  Whether to collect and return performance metrics.

    Returns:
        Dict with 'response' and optionally token/latency/system metrics.
    """
    tokens            = []
    t_request_start   = time.perf_counter()
    t_first_token     = None
    final_chunk       = {}

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

            if token and t_first_token is None:
                t_first_token = time.perf_counter()

            print(token, end="", flush=True)
            tokens.append(token)

            if chunk.get("done"):
                final_chunk = chunk
                break

    t_request_end = time.perf_counter()
    response = "".join(tokens).strip()
    result  = {"response": response}

    if collect_metrics:
        request_time   = t_request_end - t_request_start
        ttft           = round(t_first_token - t_request_start, 3) if t_first_token else None
        input_tokens   = final_chunk.get("prompt_eval_count", 0)
        output_tokens  = final_chunk.get("eval_count", 0)
        total_tokens   = input_tokens + output_tokens

        eval_ns        = final_chunk.get("eval_duration", 0)
        model_load_ns  = final_chunk.get("load_duration", 0)
        tokens_per_sec = round(output_tokens / (eval_ns / 1e9), 2) if eval_ns > 0 else None
        time_per_token = round((eval_ns / 1e9) / output_tokens, 4) if output_tokens > 0 else None

        result["metrics"] = {
            "token": {
                "input_tokens":  input_tokens,
                "output_tokens": output_tokens,
                "total_tokens":  total_tokens,
            },
            "latency": {
                "request_time":        round(request_time, 3),
                "time_to_first_token": ttft,
                "time_per_token":      time_per_token,
                "tokens_per_second":   tokens_per_sec,
            },
            "system": {
                "model_load_time_s": round(model_load_ns / 1e9, 3),
                **_collect_system_metrics(),
            },
        }

    return result


def query_ollama(
    prompt: str,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
    temperature: float = 0.3,
    stream: bool = True,
    timeout: int = 240,
    collect_metrics: bool = False,
) -> dict:
    """
    Sends a prompt to a local Ollama model and returns the response.

    Args:
        prompt:           The full prompt string to send.
        model:            Ollama model name (e.g. 'llama3.2', 'mistral').
        host:             Ollama base URL.
        temperature:      Sampling temperature (0.0 = deterministic, 1.0 = creative).
        stream:           If True, tokens are printed to stdout as they arrive.
        timeout:          HTTP request timeout in seconds.
        collect_metrics:  If True, token/latency/system metrics are included in result.

    Returns:
        Dict with:
            - 'response' (str): The model's response text.
            - 'metrics' (dict, optional): Performance data, only if collect_metrics=True.
              - 'token':   input_tokens, output_tokens, total_tokens
              - 'latency': request_time, time_to_first_token, time_per_token, tokens_per_second
              - 'system':  model_load_time_s, memory_usage_mb, cpu_usage_percent, gpu_usage

    Raises:
        ConnectionError: If Ollama is not reachable.
        ValueError:      If the requested model is not available locally.
        RuntimeError:    If the Ollama API returns an error.

    Example:
        >>> result = query_ollama("Hello!", collect_metrics=True)
        >>> print(result["response"])
        >>> print(result["metrics"]["token"]["total_tokens"])
    """
    if not is_model_available(model, host):
        pull_model(model, host)

    payload = {
        "model":   model,
        "prompt":  prompt,
        "stream":  stream,
        "options": {"temperature": temperature},
    }

    logger.info(f"Querying '{model}' (stream={stream}, metrics={collect_metrics}) ...")
    try:
        if stream:
            return _query_streaming(host, payload, timeout, collect_metrics)
        else:
            return _query_blocking(host, payload, timeout, collect_metrics)
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
        collect_metrics=True,
    )

    print("\n--- Result ---")
    print("response:", result["response"])
    if "metrics" in result:
        print("Metrics:", json.dumps(result["metrics"], indent=2))
