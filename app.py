from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import RedirectResponse
from fastapi import Request
import httpx
import os
from dotenv import load_dotenv
import json
import requests 

load_dotenv()

app = FastAPI()

user_data = {}

CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
APP_URL = os.getenv("APP_URL")  # e.g. http://localhost:8000

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_USER_URL = "https://api.github.com/user"

# OPTIONAL: Scopes you want to request
SCOPES = "read:user user:email public_repo"

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

    # Optional: Use token to get user info
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            GITHUB_API_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        user_resp.raise_for_status()
        user_json = user_resp.json()

    user_data[access_token] = user_json
    

    return {
        "access_token": access_token,
        "user_json": user_json
    }



##
## 3) Dependency to get bearer token
##
async def get_bearer_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must be Bearer token")
    return authorization.split(" ", 1)[1]
    



@app.get("/repos/list")
async def list_repos(token: str = Depends(get_bearer_token)):
    """
    Lists public repositories of the authenticated user.
    """
    url = f"https://api.github.com/user/repos?visibility=public"

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    return resp.json()
    
