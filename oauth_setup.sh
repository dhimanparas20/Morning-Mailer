#!/bin/bash

# Morning Mailer - OAuth Setup Script
# Run this once locally to authenticate with Google before running Docker

echo "=========================================="
echo "Morning Mailer - OAuth Setup"
echo "=========================================="
echo ""

# Check if token already exists
if [ -f "gauth/token.json" ]; then
    echo "✓ Token already exists at gauth/token.json"
    echo "  No need to re-authenticate."
    echo ""
    echo "To verify it works, run:"
    echo "  uv run python -c 'from modules.fetch_emails import get_gmail_service; get_gmail_service()'"
    exit 0
fi

echo "No token found. Starting OAuth flow..."
echo ""

# Run the OAuth flow
uv run python -c "
from modules.fetch_emails import get_gmail_service
get_gmail_service()
"

echo ""
echo "=========================================="
echo "OAuth Setup Complete!"
echo "=========================================="
echo ""
echo "You can now run the Docker container:"
echo "  docker compose up -d"