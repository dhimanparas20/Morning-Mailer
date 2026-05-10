#!/usr/bin/env python3
"""
Web-based OAuth setup for Gmail API.
Runs a local web server to handle the OAuth callback.

Usage:
    python -m modules.web_auth setup <keyword>
    uv run python -m modules.web_auth setup <keyword>
"""

import json
import os
import sys
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_DIR = Path("gauth/tokens")
CLIENT_SECRET_PATH = Path("gauth/client_secret.json")
CLIENT_SECRET_WEB_PATH = Path("gauth/client_secret_web.json")

DEFAULT_CALLBACK = "http://localhost:47433/callback"


def get_callback_url() -> str:
    """Get OAuth callback URL from env or default"""
    return os.getenv("OAUTH_CALLBACK_URL", DEFAULT_CALLBACK)


def get_credentials_path() -> Path:
    """Get path to client_secret.json (desktop)"""
    return CLIENT_SECRET_PATH


def get_web_credentials_path() -> Path:
    """Get path to client_secret_web.json (web app)"""
    return CLIENT_SECRET_WEB_PATH


def get_token_path(keyword: str) -> Path:
    """Get path for token file"""
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    return TOKEN_DIR / f"token_{keyword}.json"


def load_client_config() -> dict:
    """Load client configuration from web credentials, fallback to desktop"""
    # Try web first
    web_path = get_web_credentials_path()
    if web_path.exists():
        with open(web_path, "r") as f:
            return json.load(f)
    
    # Fallback to desktop
    creds_path = get_credentials_path()
    if creds_path.exists():
        with open(creds_path, "r") as f:
            return json.load(f)
    
    raise FileNotFoundError(
        f"No credentials found. Please download OAuth web app credentials "
        "from Google Cloud Console and save as gauth/client_secret_web.json"
    )


def get_auth_url(client_config: dict, state: str) -> str:
    """Generate OAuth URL"""
    client_id = client_config["web"]["client_id"]
    redirect_uri = get_callback_url()
    
    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "state": state,
        "prompt": "consent",
    }
    
    from urllib.parse import urlencode
    return f"https://accounts.google.com/o/oauth2/auth?{urlencode(auth_params)}"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handler for OAuth callback"""
    
    auth_code = None
    error = None
    
    def do_GET(self):
        """Handle GET request"""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        
        html_success = """
        <html><head><style>
        body { font-family: Arial, sans-serif; padding: 40px; text-align: center; }
        .success { color: green; font-size: 24px; }
        .box { border: 2px solid #ddd; border-radius: 8px; padding: 20px; max-width: 400px; margin: 40px auto; }
        </style></head><body>
        <div class="box">
        <p class="success">Authentication Successful!</p>
        <p>You can close this window and return to the terminal.</p>
        </div></body></html>
        """.encode("utf-8")
        
        html_error = """
        <html><body><p style='color:red;'>Error</p></body></html>
        """.encode("utf-8")
        
        html_invalid = b"<html><body><p>Invalid callback</p></body></html>"
        
        if "code" in params:
            OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(html_success)
        elif "error" in params:
            OAuthCallbackHandler.error = params["error"][0]
            self.send_response(400)
            self.end_headers()
            self.wfile.write(html_error)
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(html_invalid)
    
    def log_message(self, format, *args):
        """Suppress HTTP server logs"""
        pass


def start_oauth_server() -> str:
    """Start local OAuth callback server and return URL"""
    server = HTTPServer(("localhost", 47433), OAuthCallbackHandler)
    OAuthCallbackHandler.auth_code = None
    OAuthCallbackHandler.error = None
    
    # Get redirect URI from client config
    client_config = load_client_config()
    redirect_uri = client_config["web"]["redirect_uris"][0]
    
    thread = threading.Thread(target=server.handle_request)
    thread.daemon = True
    thread.start()
    
    return redirect_uri


def exchange_code_for_token(code: str, client_config: dict) -> dict:
    """Exchange authorization code for tokens"""
    import requests
    
    token_url = "https://oauth2.googleapis.com/token"
    
    client_id = client_config["web"]["client_id"]
    client_secret = client_config["web"]["client_secret"]
    redirect_uri = get_callback_url()
    
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    
    response = requests.post(token_url, data=data)
    response.raise_for_status()
    return response.json()


def setup_web_oauth(keyword: str = "default") -> bool:
    """Setup OAuth using web-based flow"""
    logger.info(f"Starting web OAuth setup for keyword: {keyword}")
    
    # Load client config
    try:
        client_config = load_client_config()
    except FileNotFoundError as e:
        logger.error(str(e))
        return False
    
    # Get redirect URI
    redirect_uri = client_config["web"]["redirect_uris"][0]
    logger.info(f"Redirect URI: {redirect_uri}")
    
    # Generate auth URL
    auth_url = get_auth_url(client_config, keyword)
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("OPEN THIS URL IN YOUR BROWSER:")
    logger.info("=" * 60)
    logger.info(auth_url)
    logger.info("=" * 60)
    logger.info("")
    
    # Try to open browser automatically
    try:
        webbrowser.open(auth_url)
        logger.info("Browser opened automatically!")
    except Exception as e:
        logger.warning(f"Could not open browser automatically: {e}")
    
    # Start local server to catch callback
    logger.info("Waiting for OAuth callback...")
    logger.info("(If browser didn't open, copy-paste the URL above into your browser)")
    
    server = HTTPServer(("localhost", 47433), OAuthCallbackHandler)
    OAuthCallbackHandler.auth_code = None
    OAuthCallbackHandler.error = None
    
    # Handle request with timeout
    server.handle_request()
    
    if OAuthCallbackHandler.error:
        logger.error(f"OAuth error: {OAuthCallbackHandler.error}")
        return False
    
    if not OAuthCallbackHandler.auth_code:
        logger.error("No authorization code received")
        return False
    
    logger.info("Got authorization code, exchanging for tokens...")
    
    # Exchange code for tokens
    try:
        tokens = exchange_code_for_token(OAuthCallbackHandler.auth_code, client_config)
    except Exception as e:
        logger.error(f"Failed to exchange code for tokens: {e}")
        return False
    
    # Save token
    token_path = get_token_path(keyword)
    
    # Convert to Google OAuth token format with required fields
    client_id = client_config["web"]["client_id"]
    client_secret = client_config["web"]["client_secret"]
    
    converted_token = {
        "token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": [tokens.get("scope", "https://www.googleapis.com/auth/gmail.readonly")],
        "universe_domain": "googleapis.com",
        "account": "",
        "expiry": None,
    }
    
    with open(token_path, "w") as f:
        json.dump(converted_token, f, indent=2)
    
    logger.success(f"Token saved to: {token_path}")
    return True


if __name__ == "__main__":
    import sys
    keyword = sys.argv[1] if len(sys.argv) > 1 else "default"
    setup_web_oauth(keyword)