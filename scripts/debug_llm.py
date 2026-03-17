"""
Debug script for the Ollama LLM client.

Toggle individual functions by commenting/uncommenting in the __main__ block.

Usage (from project root):
    python scripts/debug_llm.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

from lib.llm_ollama import list_local_models, query_ollama, DEFAULT_MODEL


def show_models():
    """List all locally available Ollama models."""
    print("Available models:", list_local_models())


def test_query():
    """Run a test query with streaming and metrics."""
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


if __name__ == "__main__":
    show_models()
    test_query()
