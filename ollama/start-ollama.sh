#!/bin/bash
set -e

echo "Initializing Ollama in background..."
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to be truly ready (performing health check)
echo "Waiting for Ollama to be ready at http://localhost:11434..."

until ollama list >/dev/null 2>&1; do
    echo "   Not responding yet... retrying in 2 seconds"
    sleep 2
done

echo "Ollama is up and running!"

# ←←← MODEL ←←←
MODEL_NAME="llama3.2:3b-instruct-q4_K_M"

# Check if the model is already downloaded
if ! ollama list | grep -q "$MODEL_NAME"; then
    echo "Downloading $MODEL_NAME..."
    ollama pull "$MODEL_NAME"
    echo "$MODEL_NAME downloaded and ready!"
else
    echo "$MODEL_NAME was already downloaded, skipping..."
fi

# Keep the container alive by waiting on the main process
wait $OLLAMA_PID



