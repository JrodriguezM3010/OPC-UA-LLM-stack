#!/bin/bash


if [ -f /home/node/.n8n/imported.flag ]; then
  echo "n8n credentials and workflow already imported, skipping..."
else
  echo "Importing workflow into n8n..."
  n8n import:workflow --input=/files/workflows/workflow_GPT.json || true
  n8n import:workflow --input=/files/workflows/workflow_Ollama.json || true

  echo "Preprocessing credentials..."
  mkdir -p /tmp/credentials
  for cred in /files/credentials/*.json; do
    sed -e "s|\${POSTGRES_DB}|$POSTGRES_DB|g" \
        -e "s|\${POSTGRES_USER}|$POSTGRES_USER|g" \
        -e "s|\${POSTGRES_PASSWORD}|$POSTGRES_PASSWORD|g" \
        -e "s|\${POSTGRES_HOST}|$POSTGRES_HOST|g" \
        -e "s|\${OLLAMA_URL}|$OLLAMA_URL|g" \
        -e "s|\${OPENAI_API_KEY}|$OPENAI_API_KEY|g" \
        "$cred" > "/tmp/credentials/$(basename $cred)"
  done

  echo "Importing credentials into n8n..."
  n8n import:credentials --separate --input=/tmp/credentials || true

  mkdir -p /home/node/.n8n
  touch /home/node/.n8n/imported.flag
fi

n8n update:workflow --id=AI_Stack_GPT --active=true

echo "🚀 Starting n8n..."

n8n start

echo "n8n started"