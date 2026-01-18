from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import RedirectResponse
from fastapi import Request
import httpx
import os
from dotenv import load_dotenv
import json
import requests
import base64 

load_dotenv()

app = FastAPI()

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

    return {
        "access_token": access_token,
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
    Returns a list of dictionaries with 'owner' and 'repo' keys.
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

    repos = resp.json()
    
    # Extract only owner and repo name
    return [
        {
            "owner": repo["owner"]["login"],
            "repo": repo["name"]
        }
        for repo in repos
    ]


@app.get("/repos/{owner}/{repo}/contents")
async def get_repo_contents(
    owner: str,
    repo: str,
    ref: str = Query("", description="Branch, tag, or commit SHA (defaults to default branch)"),
    token: str = Depends(get_bearer_token)
):
    """
    Gets all source code contents of a repository recursively.
    Returns a JSON object with file paths as keys and file contents as values.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}"
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Get repository info to determine default branch if ref not provided
        if not ref:
            repo_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=headers
            )
            if repo_resp.status_code != 200:
                raise HTTPException(status_code=repo_resp.status_code, detail=repo_resp.text)
            repo_info = repo_resp.json()
            ref = repo_info.get("default_branch", "main")
        
        # Check if ref looks like a commit SHA (40 hex characters)
        # If so, use it directly; otherwise try as branch/tag
        commit_sha = None
        if len(ref) == 40 and all(c in '0123456789abcdef' for c in ref.lower()):
            # Looks like a commit SHA, use it directly
            commit_sha = ref
        else:
            # Try as branch first
            ref_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{ref}",
                headers=headers
            )
            
            if ref_resp.status_code == 200:
                ref_data = ref_resp.json()
                commit_sha = ref_data["object"]["sha"]
            else:
                # Try as tag
                ref_resp = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/git/ref/tags/{ref}",
                    headers=headers
                )
                if ref_resp.status_code == 200:
                    ref_data = ref_resp.json()
                    commit_sha = ref_data["object"]["sha"]
                else:
                    # Try as commit SHA anyway (might be short SHA)
                    commit_sha = ref
        
        # Get the commit to get tree SHA
        commit_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/commits/{commit_sha}",
            headers=headers
        )
        if commit_resp.status_code != 200:
            raise HTTPException(status_code=commit_resp.status_code, detail=f"Invalid ref: {ref}")
        
        commit_data = commit_resp.json()
        tree_sha = commit_data["tree"]["sha"]
        
        # Get recursive tree
        tree_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{tree_sha}",
            headers=headers,
            params={"recursive": "1"}
        )
        if tree_resp.status_code != 200:
            raise HTTPException(status_code=tree_resp.status_code, detail=tree_resp.text)
        
        tree_data = tree_resp.json()
        
        # Filter for files (blobs) only
        files = [item for item in tree_data.get("tree", []) if item.get("type") == "blob"]
        
        if not files:
            return {}
        
        # Fetch blob contents for each file
        result = {}
        for file_item in files:
            file_path = file_item["path"]
            blob_sha = file_item["sha"]
            
            blob_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{blob_sha}",
                headers=headers
            )
            
            if blob_resp.status_code != 200:
                # Skip files that can't be fetched
                continue
            
            blob_data = blob_resp.json()
            
            # Decode base64 content if present
            if blob_data.get("encoding") == "base64" and "content" in blob_data:
                try:
                    decoded_content = base64.b64decode(blob_data["content"]).decode("utf-8")
                    result[file_path] = decoded_content
                except (UnicodeDecodeError, ValueError):
                    # Skip binary files that can't be decoded as UTF-8
                    continue
                except Exception as e:
                    # Skip files with other decoding errors
                    continue
            else:
                # If no content or different encoding, skip
                continue
        
        return result

