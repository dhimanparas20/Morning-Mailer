#!/bin/sh
set -e

# Start Ollama server in background initially to allow model pull
ollama serve &
SERVER_PID=$!

# Wait for the server to become available (timeout after 60s)
echo "Waiting for Ollama server to start..."
TRIES=0
until curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do
  TRIES=$((TRIES + 1))
  if [ "$TRIES" -ge 60 ]; then
    echo "ERROR: Ollama server failed to start within 60s"
    exit 1
  fi
  sleep 1
done
echo "Server is up."

# Pull the model if not already present
MODEL=${OLLAMA_MODEL:-llama3.2:3b}
if ! ollama list | grep -q "$MODEL"; then
  echo "Pulling model $MODEL..."
  ollama pull "$MODEL"
else
  echo "Model $MODEL already exists."
fi

# Stop the background server and restart it in foreground (for signal handling)
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null

# Now run the server in foreground (so signals from Docker work)
exec ollama serve
