import time
import os
import json
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# Configuration: Toggle between OpenAI and local Ollama
USE_OPENAI = os.getenv("USE_OPENAI", "false").lower() == "true"

if USE_OPENAI:
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    MODEL = "gpt-5-mini"
else:
    client = AsyncOpenAI(
        base_url='http://localhost:11434/v1',
        api_key='ollama',
    )
    MODEL = "llama3"

async def get_ai_content(path, parent_path=None, parent_data=None):
    """
    Requests JSON content from the AI based on the provided URL path.
    """
    start_time = time.time()
    print(f"\n[AI] Starting AI content generation for path: {path}")

    context_block = ""
    if parent_data is not None:
        context_json = json.dumps(parent_data, ensure_ascii=False)
        if len(context_json) > 4000:
            context_json = context_json[:4000] + " ...[truncated]"
        context_block = (
            f"Parent context (from {parent_path}):\n"
            f"{context_json}\n"
            "Use this parent context to keep child-resource data consistent. "
            "For example, comments under /books/2 should clearly belong to book 2.\n"
        )

    prompt = (
        f"You are a fast REST API mock server. Generate a realistic JSON response for: {path}. "
        f"{context_block}"
        "Rules:\n"
        "1. If it is a list, provide exactly 5 items.\n"
        "2. Keep metadata etc minimal.\n"
        "3. Resource ID must always be a unique integer. For example, if the path is /posts, generate posts with IDs 1, 2, 3, etc.\n"
        "4. Do not include any subresources like comments or tags to posts, just the main resource.\n"
        "5. Keep the structure simple, for example, posts should have fields like id, title, content, author, created_at, but not nested comments or similar.\n"
        "6. Check the path for spelling mistakes and typos. Give an error message if found. Example:\n"
        "{\n"
        "    \"error\": \"Not Found\",\n"
        "    \"message\": \"Path '/bycycles' not found. Did you mean '/bicycles'?\",\n"
        "    \"status\": 404\n"
        "}\n"
    )

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        print(f"AI Client Error: {e}")
        return {"error": "AI_COMMUNICATION_FAILED", "details": str(e)}
    
    finally:
        duration = time.time() - start_time
        print(f"\n[AI] Finished in {duration:.2f} seconds.")