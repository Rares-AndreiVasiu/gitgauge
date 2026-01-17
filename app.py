from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi import Request
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
APP_URL = os.getenv("APP_URL")  # e.g. http://localhost:8000

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_USER_URL = "https://api.github.com/user"

# OPTIONAL: Scopes you want to request
SCOPES = "read:user user:email"

##
## 1) Login redirect
##
@app.get("/login")
async def login():
    """
    Redirect the user to GitHub's OAuth authorize page.
    """
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": f"{APP_URL}/auth/callback",
       "scope": SCOPES,
        "state": "random_csrf_state",   # For CSRF protection in production
    }
    url = httpx.URL(GITHUB_AUTHORIZE_URL, params=params)
    return RedirectResponse(str(url))


##
## 2) GitHub callback
##
@app.get("/auth/callback")
async def auth_callback(code: str = None, state: str = None):
    """
    This endpoint is called by GitHub after the user authorized.
    """
    if not code:
        raise HTTPException(400, "No code provided")

    # Exchange the code for an access token
    async with httpx.AsyncClient() as client:
        headers = {"Accept": "application/json"}
        token_resp = await client.post(
            GITHUB_ACCESS_TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{APP_URL}/auth/callback",
            },
            headers=headers,
        )
        token_resp.raise_for_status()
        token_json = token_resp.json()

    access_token = token_json.get("access_token")
    if not access_token:
        raise HTTPException(400, "No access token in response")

    return {
        "access_token": access_token,
        "user": user_json
    }

