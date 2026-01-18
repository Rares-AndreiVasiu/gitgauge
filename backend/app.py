from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import RedirectResponse
import httpx
import os
from dotenv import load_dotenv
import base64
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__) 

load_dotenv()

app = FastAPI()

CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
APP_URL = os.getenv("APP_URL")

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_USER_URL = "https://api.github.com/user"

SCOPES = "read:user user:email public_repo"


@app.get("/login")
async def login():
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": f"{APP_URL}/auth/callback",
        "scope": SCOPES,
        "state": "random_csrf_state",
    }
    url = httpx.URL(GITHUB_AUTHORIZE_URL, params=params)
    return RedirectResponse(str(url))


@app.get("/login/url")
async def get_login_url():
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": f"{APP_URL}/auth/callback",
        "scope": SCOPES,
        "state": "random_csrf_state",
    }
    url = httpx.URL(GITHUB_AUTHORIZE_URL, params=params)
    return {"auth_url": str(url)}


@app.get("/auth/callback")
async def auth_callback(code: str = None, state: str = None):
    if not code:
        raise HTTPException(400, "No code provided")

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



async def get_bearer_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must be Bearer token")
    return authorization.split(" ", 1)[1]
    



@app.get("/repos/list")
async def list_repos(token: str = Depends(get_bearer_token)):
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
    
    return [
        {
            "owner": repo["owner"]["login"],
            "repo": repo["name"]
        }
        for repo in repos
    ]


async def get_repo_contents(
    owner: str,
    repo: str,
    ref: str,
    token: str
) -> tuple[dict, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}"
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        if not ref:
            repo_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=headers
            )
            if repo_resp.status_code != 200:
                raise HTTPException(status_code=repo_resp.status_code, detail=repo_resp.text)
            repo_info = repo_resp.json()
            ref = repo_info.get("default_branch", "main")
        
        commit_sha = None
        if len(ref) == 40 and all(c in '0123456789abcdef' for c in ref.lower()):
            commit_sha = ref
        else:
            ref_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{ref}",
                headers=headers
            )
            
            if ref_resp.status_code == 200:
                ref_data = ref_resp.json()
                commit_sha = ref_data["object"]["sha"]
            else:
                ref_resp = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/git/ref/tags/{ref}",
                    headers=headers
                )
                if ref_resp.status_code == 200:
                    ref_data = ref_resp.json()
                    commit_sha = ref_data["object"]["sha"]
                else:
                    commit_sha = ref
        
        commit_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/commits/{commit_sha}",
            headers=headers
        )
        if commit_resp.status_code != 200:
            raise HTTPException(status_code=commit_resp.status_code, detail=f"Invalid ref: {ref}")
        
        commit_data = commit_resp.json()
        tree_sha = commit_data["tree"]["sha"]
        
        tree_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{tree_sha}",
            headers=headers,
            params={"recursive": "1"}
        )
        if tree_resp.status_code != 200:
            raise HTTPException(status_code=tree_resp.status_code, detail=tree_resp.text)
        
        tree_data = tree_resp.json()
        
        files = [item for item in tree_data.get("tree", []) if item.get("type") == "blob"]
        
        if not files:
            raise HTTPException(status_code=404, detail="No files found in repository")
        
        repo_contents = {}
        for file_item in files:
            file_path = file_item["path"]
            blob_sha = file_item["sha"]
            
            blob_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{blob_sha}",
                headers=headers
            )
            
            if blob_resp.status_code != 200:
                continue
            
            blob_data = blob_resp.json()
            
            if blob_data.get("encoding") == "base64" and "content" in blob_data:
                try:
                    decoded_content = base64.b64decode(blob_data["content"]).decode("utf-8")
                    repo_contents[file_path] = decoded_content
                except (UnicodeDecodeError, ValueError):
                    continue
                except Exception as e:
                    continue
            else:
                continue
        
        return repo_contents, ref


@app.post("/repos/{owner}/{repo}/analyze")
async def analyze_repo(
    owner: str,
    repo: str,
    ref: str = Query("", description="Branch, tag, or commit SHA (defaults to default branch)"),
    token: str = Depends(get_bearer_token)
):
    repo_contents, actual_ref = await get_repo_contents(owner, repo, ref, token)
    
    analysis_service_url = os.getenv("ANALYSIS_SERVICE_URL", "http://analysis-service:8001")
    analysis_endpoint = f"{analysis_service_url}/analyze"
    
    logger.info(f"Calling analysis service at: {analysis_endpoint}")
    logger.info(f"Repository: {owner}/{repo}, Ref: {actual_ref}, Files: {len(repo_contents)}")
    
    analysis_payload = {
        "owner": owner,
        "repo": repo,
        "ref": actual_ref,
        "contents": repo_contents
    }
    
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            logger.info(f"Sending POST request to {analysis_endpoint}")
            analysis_resp = await client.post(
                analysis_endpoint,
                json=analysis_payload,
                timeout=180.0
            )
            logger.info(f"Analysis service response status: {analysis_resp.status_code}")
            analysis_resp.raise_for_status()
            return analysis_resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Analysis service HTTP error: {e.response.status_code} - {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Analysis service error: {e.response.text}"
            )
        except httpx.RequestError as e:
            logger.error(f"Analysis service connection error: {str(e)}")
            raise HTTPException(
                status_code=503,
                detail=f"Failed to connect to analysis service at {analysis_endpoint}: {str(e)}"
            )

