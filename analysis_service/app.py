from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict
import os
from groq import Groq
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


def get_groq_client():
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY environment variable is not set"
        )
    return Groq(api_key=groq_api_key)


class AnalyzeRequest(BaseModel):
    owner: str
    repo: str
    ref: str
    contents: Dict[str, str]  # file_path -> file_content


def format_code_for_ai(contents: Dict[str, str]) -> str:
    formatted = []
    for file_path, content in contents.items():
        formatted.append(f"## File: {file_path}\n")
        formatted.append("```")
        if file_path.endswith('.py'):
            formatted.append("python")
        elif file_path.endswith(('.c', '.h')):
            formatted.append("c")
        elif file_path.endswith(('.js', '.jsx')):
            formatted.append("javascript")
        elif file_path.endswith(('.ts', '.tsx')):
            formatted.append("typescript")
        elif file_path.endswith('.java'):
            formatted.append("java")
        elif file_path.endswith('.go'):
            formatted.append("go")
        elif file_path.endswith('.rs'):
            formatted.append("rust")
        else:
            formatted.append("")
        formatted.append(f"\n{content}\n```\n")
    return "\n".join(formatted)


SYSTEM_PROMPT = """You are an expert code analyst and software architect. Your task is to analyze code repositories and provide comprehensive, structured feedback.

Analyze the provided code and provide a detailed assessment covering:

1. **Purpose & Functionality**: What does this code do? What is its main purpose and functionality?

2. **Architecture & Structure**: 
   - How is the code organized?
   - What design patterns are used?
   - Is the structure logical and maintainable?

3. **Languages & Technologies**: 
   - What programming languages are used?
   - What frameworks, libraries, or tools are identified?
   - Are there any build systems or configuration files?

4. **Code Quality**:
   - Readability and clarity
   - Code organization and modularity
   - Naming conventions
   - Error handling
   - Code complexity

5. **Best Practices**:
   - Adherence to language-specific best practices
   - Documentation quality
   - Code style consistency
   - Testing considerations

6. **Security Considerations**:
   - Potential security vulnerabilities
   - Safe coding practices
   - Input validation
   - Memory management (if applicable)

7. **Recommendations**:
   - Specific, actionable improvements
   - Areas that need attention
   - Potential refactoring opportunities
   - Missing features or considerations

Provide your analysis in a clear, structured format. Be specific and cite examples from the code when making points."""


@app.post("/analyze")
async def analyze_code(request: AnalyzeRequest):
    try:
        logger.info(f"Analyzing repository: {request.owner}/{request.repo} (ref: {request.ref})")
        logger.info(f"Number of files: {len(request.contents)}")
        
        formatted_code = format_code_for_ai(request.contents)
        
        max_length = 100000
        if len(formatted_code) > max_length:
            logger.warning(f"Code too long ({len(formatted_code)} chars), truncating to {max_length}")
            formatted_code = formatted_code[:max_length] + "\n\n[Code truncated due to length...]"
        
        user_message = f"""Please analyze the following code repository:

Repository: {request.owner}/{request.repo}
Branch/Ref: {request.ref}

Code Files:
{formatted_code}

Provide a comprehensive analysis following the guidelines in the system prompt."""
        
        logger.info("Calling Groq API...")
        groq_client = get_groq_client()
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            model="openai/gpt-oss-120b",
            temperature=0.3,
            max_tokens=4096
        )
        
        analysis_text = chat_completion.choices[0].message.content
        
        logger.info("Analysis completed successfully")
        
        return {
            "summary": analysis_text.split("\n")[0] if analysis_text else "Analysis completed",
            "analysis": analysis_text,
            "repository": {
                "owner": request.owner,
                "repo": request.repo,
                "ref": request.ref,
                "files_analyzed": len(request.contents)
            }
        }
        
    except Exception as e:
        logger.error(f"Error during analysis: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze code: {str(e)}"
        )


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "code-analysis"}

