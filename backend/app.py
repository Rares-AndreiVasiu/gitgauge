from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import RedirectResponse
import httpx
import os
from dotenv import load_dotenv
import base64
import logging
import zipfile
import io

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


GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_DEVICE_TOKEN_URL = "https://github.com/login/oauth/access_token"


@app.post("/auth/device/initiate")
async def initiate_device_flow():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GITHUB_DEVICE_CODE_URL,
            data={
                "client_id": CLIENT_ID,
                "scope": SCOPES,
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()


@app.post("/auth/device/poll")
async def poll_device_flow(device_code: str = Query(..., description="Device code from initiate endpoint")):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GITHUB_DEVICE_TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"Accept": "application/json"},
        )
        
        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get("access_token")
            if access_token:
                async with httpx.AsyncClient() as user_client:
                    user_response = await user_client.get(
                        GITHUB_API_USER_URL,
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    user_response.raise_for_status()
                    user_data = user_response.json()
                    return {
                        "access_token": access_token,
                        "user": user_data,
                    }
        
        error_data = response.json()
        error = error_data.get("error", "unknown_error")
        
        if error == "authorization_pending":
            return {"status": "pending"}
        elif error == "slow_down":
            return {"status": "slow_down"}
        else:
            raise HTTPException(status_code=400, detail=error_data)


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
            "id": repo.get("id", 0),
            "name": repo.get("name", ""),
            "description": repo.get("description"),
            "html_url": repo.get("html_url", ""),
            "stargazers_count": repo.get("stargazers_count", 0)
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

    async with httpx.AsyncClient(timeout=180.0) as client:
        if not ref:
            repo_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=headers
            )
            if repo_resp.status_code != 200:
                raise HTTPException(status_code=repo_resp.status_code, detail=repo_resp.text)
            repo_info = repo_resp.json()
            ref = repo_info.get("default_branch", "main")
        
        archive_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{ref}.zip"
        
        archive_resp = await client.get(archive_url, headers=headers, follow_redirects=True)
        
        if archive_resp.status_code != 200:
            raise HTTPException(
                status_code=archive_resp.status_code,
                detail=f"Failed to download archive: {archive_resp.text}"
            )
        
        zip_data = archive_resp.content
        repo_contents = {}
        
        try:
            with zipfile.ZipFile(io.BytesIO(zip_data), 'r') as zip_file:
                prefix = f"{repo}-{ref}/"
                
                for file_info in zip_file.filelist:
                    if file_info.is_dir():
                        continue
                    
                    file_path = file_info.filename
                    
                    if not file_path.startswith(prefix):
                        continue
                    
                    relative_path = file_path[len(prefix):]
                    
                    try:
                        file_content = zip_file.read(file_path).decode('utf-8')
                        repo_contents[relative_path] = file_content
                    except (UnicodeDecodeError, ValueError):
                        continue
                    except Exception as e:
                        logger.warning(f"Error reading file {relative_path}: {e}")
                        continue
        
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file received from GitHub")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error processing zip file: {str(e)}")
        
        if not repo_contents:
            raise HTTPException(status_code=404, detail="No files found in repository archive")
        
        return repo_contents, ref


@app.post("/repos/{owner}/{repo}/analyze")
async def analyze_repo(
    owner: str,
    repo: str,
    ref: str = Query("", description="Branch, tag, or commit SHA (defaults to default branch)"),
    force_reanalysis: bool = Query(False, description="Force reanalysis even if cached result exists"),
    token: str = Depends(get_bearer_token)
):
    repo_contents, actual_ref = await get_repo_contents(owner, repo, ref, token)
    
    analysis_service_url = os.getenv("ANALYSIS_SERVICE_URL", "http://analysis-service:8001")
    analysis_endpoint = f"{analysis_service_url}/analyze"
    
    logger.info(f"Calling analysis service at: {analysis_endpoint}")
    logger.info(f"Repository: {owner}/{repo}, Ref: {actual_ref}, Files: {len(repo_contents)}, Force reanalysis: {force_reanalysis}")
    
    analysis_payload = {
        "owner": owner,
        "repo": repo,
        "ref": actual_ref,
        "contents": repo_contents,
        "force_reanalysis": force_reanalysis
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

