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

async def get_ai_content(path):
    """
    Requests JSON content from the AI based on the provided URL path.
    """
    start_time = time.time()
    print(f"\n[AI] Starting AI content generation for path: {path}")
    prompt = (
        f"You are a REST API server. Generate a realistic JSON response for the path: {path}. "
        "Include a '_schema' field listing 2-3 logical sub-resources (e.g., if path is /car, "
        "sub-resources could be engine, wheels)."
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