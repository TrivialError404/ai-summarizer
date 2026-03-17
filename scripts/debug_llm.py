"""
Debug script for the Ollama LLM client.

Lists available models and runs a test query with metrics.

Usage (from project root):
    python scripts/debug_llm.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

from lib.llm_ollama import list_local_models, query_ollama, DEFAULT_MODEL

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
