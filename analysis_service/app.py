from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Tuple
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


def estimate_tokens(text: str) -> int:
    return len(text) // 4

def create_batches(contents: Dict[str, str], max_tokens_per_batch: int = 6000) -> List[Dict[str, str]]:
    batches = []
    current_batch = {}
    current_batch_tokens = 0
    
    for file_path, content in contents.items():
        file_tokens = estimate_tokens(content)
        formatted_file_tokens = file_tokens + 100
        
        if file_tokens > max_tokens_per_batch:
            if current_batch:
                batches.append(current_batch)
                current_batch = {}
                current_batch_tokens = 0
            batches.append({file_path: content})
        elif current_batch_tokens + formatted_file_tokens <= max_tokens_per_batch:
            current_batch[file_path] = content
            current_batch_tokens += formatted_file_tokens
        else:
            if current_batch:
                batches.append(current_batch)
            current_batch = {file_path: content}
            current_batch_tokens = formatted_file_tokens
    
    if current_batch:
        batches.append(current_batch)
    
    return batches

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


PER_FILE_SUMMARY_PROMPT = """You are a code analyst. Analyze the provided code files and create a concise summary for each file.

For each file, provide:
1. **Purpose**: What does this file do? (1-2 sentences)
2. **Key Components**: Main classes, functions, or modules (bullet points)
3. **Dependencies**: Important imports or external dependencies
4. **Quality Notes**: Brief observations about code quality, patterns, or notable features (1-2 sentences)

Keep each file summary concise (100-200 words). Format as:
## File: [path]
- Purpose: [description]
- Key Components: [list]
- Dependencies: [list]
- Quality Notes: [observations]

[Next file...]"""

SYNTHESIS_PROMPT = """You are an expert code analyst and software architect. You have been provided with summaries of individual files from a code repository. Your task is to synthesize these summaries into a comprehensive, structured analysis.

Based on the file summaries provided, create a detailed assessment covering:

1. **Purpose & Functionality**: What does this codebase do? What is its main purpose and functionality?

2. **Architecture & Structure**: 
   - How is the code organized?
   - What design patterns are used?
   - Is the structure logical and maintainable?
   - How do the files relate to each other?

3. **Languages & Technologies**: 
   - What programming languages are used?
   - What frameworks, libraries, or tools are identified?
   - Are there any build systems or configuration files?

4. **Code Quality**:
   - Overall readability and clarity
   - Code organization and modularity
   - Naming conventions
   - Error handling patterns
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

Provide your analysis in a clear, structured format. Synthesize patterns across files and provide a holistic view of the codebase."""

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
        
        groq_client = get_groq_client()
        batches = create_batches(request.contents)
        logger.info(f"Created {len(batches)} batches for processing")
        
        batch_summaries = []
        failed_batches = 0
        
        for i, batch in enumerate(batches, 1):
            try:
                logger.info(f"Processing batch {i}/{len(batches)} ({len(batch)} files)")
                formatted_code = format_code_for_ai(batch)
                
                batch_tokens = estimate_tokens(formatted_code)
                if batch_tokens > 6000:
                    logger.warning(f"Batch {i} too large ({batch_tokens} tokens), truncating")
                    formatted_code = formatted_code[:24000] + "\n\n[Code truncated due to length...]"
                
                user_message = f"""Please analyze the following code files from repository {request.owner}/{request.repo}:

Code Files:
{formatted_code}

Provide concise summaries for each file following the guidelines."""
                
                chat_completion = groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": PER_FILE_SUMMARY_PROMPT},
                        {"role": "user", "content": user_message}
                    ],
                    model="openai/gpt-oss-120b",
                    temperature=0.3,
                    max_tokens=2048
                )
                
                batch_summary = chat_completion.choices[0].message.content
                batch_summaries.append(batch_summary)
                logger.info(f"Batch {i} processed successfully")
                
            except Exception as e:
                logger.error(f"Error processing batch {i}: {str(e)}")
                failed_batches += 1
                continue
        
        if not batch_summaries:
            raise HTTPException(
                status_code=500,
                detail="All batches failed to process"
            )
        
        if failed_batches > 0:
            logger.warning(f"{failed_batches} batches failed, proceeding with {len(batch_summaries)} successful summaries")
        
        logger.info("Starting final synthesis...")
        all_summaries = "\n\n".join(batch_summaries)
        
        synthesis_message = f"""Repository: {request.owner}/{request.repo}
Branch/Ref: {request.ref}
Total Files Analyzed: {len(request.contents)}

File Summaries:
{all_summaries}

Synthesize these summaries into a comprehensive analysis."""
        
        try:
            synthesis_completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYNTHESIS_PROMPT},
                    {"role": "user", "content": synthesis_message}
                ],
                model="openai/gpt-oss-120b",
                temperature=0.3,
                max_tokens=4096
            )
            
            analysis_text = synthesis_completion.choices[0].message.content
            logger.info("Final synthesis completed successfully")
            
        except Exception as e:
            logger.error(f"Error during final synthesis: {str(e)}")
            logger.info("Falling back to concatenated summaries")
            analysis_text = f"# Repository Analysis Summary\n\n{all_summaries}\n\n[Note: Final synthesis failed, showing individual file summaries]"
        
        return {
            "summary": analysis_text.split("\n")[0] if analysis_text else "Analysis completed",
            "analysis": analysis_text,
            "repository": {
                "owner": request.owner,
                "repo": request.repo,
                "ref": request.ref,
                "files_analyzed": len(request.contents),
                "batches_processed": len(batches),
                "batches_failed": failed_batches
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

