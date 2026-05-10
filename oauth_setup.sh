#!/bin/bash

# Morning Mailer - OAuth Setup Script
# Run this to authenticate multiple users with Google before running Docker
# 
# Usage:
#   ./oauth_setup.sh              # Auto-setup all users
#   ./oauth_setup.sh web          # Use web OAuth (recommended)
#   ./oauth_setup.sh desktop      # Use desktop OAuth
#   ./oauth_setup.sh <keyword>     # Setup specific keyword

MODE=""
KEYWORD=""

# Parse arguments
for arg in "$@"; do
    case $arg in
        web|desktop)
            MODE="$arg"
            ;;
        *)
            KEYWORD="$arg"
            ;;
    esac
done

echo "=========================================="
echo "Morning Mailer - OAuth Setup"
echo "=========================================="
echo ""

# Function to check if token exists for a keyword
check_token() {
    local keyword="$1"
    if [ -f "gauth/tokens/token_${keyword}.json" ]; then
        return 0
    else
        return 1
    fi
}

# Function to run OAuth for a keyword
run_oauth() {
    local keyword="$1"
    echo "Starting OAuth flow for keyword: $keyword"
    echo ""

    if [ "$MODE" = "web" ] || [ -z "$MODE" ]; then
        uv run python -m modules.web_auth "$keyword"
    else
        uv run python -c "
from modules.fetch_emails import get_gmail_service
get_gmail_service('$keyword')
"
    fi

    if check_token "$keyword"; then
        echo "Token created: gauth/tokens/token_${keyword}.json"
    else
        echo "Failed to create token for: $keyword"
    fi
    echo ""
}

# Determine mode based on available credentials
if [ -z "$MODE" ]; then
    if [ -f "gauth/client_secret_web.json" ]; then
        MODE="web"
    elif [ -f "gauth/client_secret.json" ]; then
        MODE="desktop"
    fi
fi

# Show mode info
if [ "$MODE" = "web" ]; then
    echo "Using: Web OAuth (gauth/client_secret_web.json)"
elif [ "$MODE" = "desktop" ]; then
    echo "Using: Desktop OAuth (gauth/client_secret.json)"
else
    echo "No credentials found!"
    echo "Please download OAuth credentials from Google Cloud Console:"
    echo "  - Web app: save as gauth/client_secret_web.json"
    echo "  - Desktop app: save as gauth/client_secret.json"
    exit 1
fi
echo ""

# If keyword provided, just setup that one
if [ -n "$KEYWORD" ]; then
    run_oauth "$KEYWORD"
    exit 0
fi

# Check if users.json exists
if [ -f "users.json" ]; then
    echo "Found users.json - checking all users..."
    echo ""

    # Get all keywords from users.json
    KEYWORDS=$(python3 -c "
import json
try:
    with open('users.json', 'r') as f:
        users = json.load(f)
    for user in users:
        print(user.get('keyword', ''))
except:
    pass
" 2>/dev/null)

    if [ -z "$KEYWORDS" ]; then
        echo "No keywords found in users.json"
        KEYWORDS="default"
    fi

    # Process each keyword
    for keyword in $KEYWORDS; do
        if [ -z "$keyword" ]; then
            continue
        fi

        echo "Checking token for user: $keyword"

        if check_token "$keyword"; then
            echo "  Token exists (gauth/tokens/token_${keyword}.json)"
        else
            echo "  Token not found"
            echo "  Running OAuth flow..."
            run_oauth "$keyword"
        fi
        echo ""
    done
else
    echo "No users.json found - checking for existing tokens..."
    echo ""

    # Check for any existing tokens
    TOKEN_COUNT=$(ls -1 gauth/tokens/token_*.json 2>/dev/null | wc -l)

    if [ "$TOKEN_COUNT" -gt 0 ]; then
        echo "Found $TOKEN_COUNT token(s):"
        ls -1 gauth/tokens/token_*.json 2>/dev/null | while read f; do
            echo "  $(basename $f)"
        done
    else
        echo "No tokens found. Running OAuth for default keyword..."
        run_oauth "default"
    fi
fi

echo "=========================================="
echo "OAuth Setup Complete!"
echo "=========================================="
echo ""
echo "To add a new user token:"
echo "  ./oauth_setup.sh web work        # Use web OAuth"
echo "  ./oauth_setup.sh desktop work    # Use desktop OAuth"
echo ""
echo "Or in IPython:"
echo "  %setup_web_oauth work   (web)"
echo "  %setup_oauth work        (desktop)"