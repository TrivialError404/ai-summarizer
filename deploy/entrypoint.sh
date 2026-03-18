#!/bin/bash
ollama serve &

echo "Waiting for Ollama to be ready..."
until curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do
    sleep 1
done
echo "Ollama ready. Container is running."

#python3 main.py    # run python script
tail -f /dev/null   # keep container alive