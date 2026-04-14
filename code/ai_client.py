import time
import os
import json
import math
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# Configuration: Toggle between OpenAI and local Ollama
USE_OPENAI = os.getenv("USE_OPENAI", "false").lower() == "true"

if USE_OPENAI:
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    MODEL = "gpt-4o-mini"
else:
    client = AsyncOpenAI(
        base_url='http://localhost:11434/v1',
        api_key='ollama',
    )
    MODEL = "llama3"

API_SPECIFICATION = os.getenv("API_SPECIFICATION", "You are a fast REST API mock server. Return only valid JSON.")

# Keep this block stable across requests so providers can cache the prefix.
BASE_INSTRUCTIONS = (
    f"{API_SPECIFICATION}\n"
    "Rules:\n"
    "1. If it is a list and no count is requested, provide exactly 5 items.\n"
    "2. Keep metadata minimal.\n"
    "3. Resource ID must always be a unique integer. "
    "For example, if the path is /posts, generate posts with IDs 1, 2, 3, etc.\n"
    "4. Do not include unrelated subresources by default.\n"
    "5. Keep structure simple and realistic for the requested resource.\n"
    "6. Check the path for spelling mistakes and typos. Give an error object if found, example:\n"
    "{\n"
    "  \"error\": \"Not Found\",\n"
    "  \"message\": \"Path '/bycycles' not found. Did you mean '/bicycles'?\",\n"
    "  \"status\": 404\n"
    "}\n"
    "7. If you are requested a specific resource that is not found yet, please generate a new resource with requested id, e.g. if the path is /books/999, generate a new book with \"id\": 999.\n"
)

def _estimate_tokens(text):
    """Rough fallback when provider does not return token usage."""
    if not text:
        return 0
    # Common approximation for English-like text.
    return max(1, math.ceil(len(text) / 4))

def _extract_response_text(response):
    """Extracts plain text from a Responses API result."""
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    output_items = getattr(response, "output", None) or []
    for item in output_items:
        if getattr(item, "type", None) != "message":
            continue
        content_items = getattr(item, "content", None) or []
        for content in content_items:
            text_value = getattr(content, "text", None)
            if text_value:
                return text_value
    return None

async def get_ai_content(path, parent_path=None, parent_data=None, expected_schema=None, requested_count=None):
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

    schema_block = ""
    if expected_schema:
        schema_block = (
            "Existing schema columns for this resource table:\n"
            f"{json.dumps(expected_schema, ensure_ascii=False)}\n"
            "Your response records must use only these columns. "
            "Do not invent new column names.\n"
        )

    count_block = ""
    if requested_count is not None:
        count_block = (
            f"If this endpoint returns a list, generate exactly {requested_count} new items. "
            "Do not repeat items already present in the context.\n"
        )

    user_input = (
        f"Generate a realistic JSON response for path: {path}.\n"
        f"{context_block}"
        f"{schema_block}"
        f"{count_block}"
    )

    try:
        response = await client.responses.create(
            model=MODEL,
            instructions=BASE_INSTRUCTIONS,
            input=user_input,
            text={"format": {"type": "json_object"}},
        )

        usage = getattr(response, "usage", None)
        if usage is not None:
            prompt_tokens = getattr(usage, "input_tokens", None)
            completion_tokens = getattr(usage, "output_tokens", None)
            total_tokens = getattr(usage, "total_tokens", None)

            print(
                "[AI] Token usage"
                f" | prompt: {prompt_tokens}"
                f" | completion: {completion_tokens}"
                f" | total: {total_tokens}"
            )
        else:
            estimated_prompt_tokens = _estimate_tokens(BASE_INSTRUCTIONS + user_input)
            print(
                "[AI] Token usage | prompt: unavailable from provider"
                f" | estimated_prompt: ~{estimated_prompt_tokens}"
            )

        content = _extract_response_text(response)
        if not content:
            raise ValueError("Responses API returned no text output")

        print(user_input)
        print("[AI] Raw response text start")
        print(content)
        print("[AI] Raw response text end")

        return json.loads(content)
    except Exception as e:
        print(f"AI Client Error: {e}")
        return {"error": "AI_COMMUNICATION_FAILED", "details": str(e)}
    
    finally:
        duration = time.time() - start_time
        print(f"\n[AI] Finished in {duration:.2f} seconds.")