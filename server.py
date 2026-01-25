from fastapi import FastAPI, HTTPException, Request
import ollama
import json
from typing import Optional
import time

app = FastAPI()

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.perf_counter() # Paneb stopperi käima
    
    response = await call_next(request) # Ootab, kuni AI vastuse genereerib
    
    process_time = time.perf_counter() - start_time # Arvutab kulunud aja
    
    # Prindib aja terminali (et sa näeksid seda kohe)
    print(f"Päringu kestus: {process_time:.4f} sekundit")
    
    # Lisab aja ka vastuse päisesse (header), et klient (nt Axios) saaks seda näha
    response.headers["X-Process-Time"] = str(process_time)
    
    return response

@app.get("/api/{context}/{category}")
@app.get("/api/{context}/{category}/{item_id}")
async def simulate_api(context: str, category: str, item_id: Optional[int] = None):
    """
    Endpoint to simulate a real API response using Llama 3.2.
    It takes a context, category, and item_id (e.g., 'users', 'posts', 10) and returns a JSON object.
    """
    start_total_internal = time.perf_counter()
    
    # SYSTEM PROMPT: This is part of your research strategy to ensure valid output
    system_instructions = (
        f"You are a API for a {context}. "
        f"If you are given just '{category}', generate at least 5 different items. "
        f"If the {item_id} is provided, return data for that specific item. "
        "Respond ONLY with valid JSON. "
        "When you generate an array, every item MUST HAVE a unique 'id' field. "
        "STRICT CONTENT RULES: \n"
        "1. NEVER use generic placeholders like 'Title 1', 'User A', or 'test@test.com'. \n"
        "2. Use diverse, realistic human names, creative blog post titles, and natural-sounding content. \n"
        "3. Ensure dates, prices, and descriptions follow a logical context (e.g., a tech blog post should have tech-related content). \n"
        "4. Format the JSON purely without any markdown code blocks."
        "5. NO \n symbols in the JSON output."
        "6. If the request is 'users/10' or a similar pattern, generate a single object instead of an array."
    )
    
    user_prompt = f"Generate a JSON response for a REST API endpoint that returns: {context}/{category}/{item_id if item_id else ''}"

    attempts = 0
    max_attempts = 5 # Paneme igaks juhuks piiri ette, et ta lõputult ei ketraks
    
    while attempts < max_attempts:
        attempts += 1
        print(f"--- KATSE {attempts} ---", flush=True)
        
        try:
            # AI genereerimine
            start_ai = time.perf_counter()
            response = ollama.chat(
                model='qwen2.5:0.5b',
                messages=[{'role': 'system', 'content': system_instructions},
                          {'role': 'user', 'content': user_prompt}]
            )
            ai_duration = time.perf_counter() - start_ai

            # Järeltöötlus ja JSON-i parsimine
            start_parse = time.perf_counter()
            raw_content = response['message']['content'].strip()
            
            # Siin on see "puhastamise" koht, millest rääkisime
            if "```" in raw_content:
                raw_content = raw_content.split("```")[1]
                if raw_content.startswith("json"): raw_content = raw_content[4:]
                raw_content = raw_content.strip()

            # Proovime parsimist
            json_data = json.loads(raw_content)
            parse_duration = time.perf_counter() - start_parse
            
            # KUI ÕNNESTUB: Trükime logisse ja tagastame andmed
            print(f"ÕNNESTUS katsel {attempts}!", flush=True)
            print(f"AI genereerimise aeg: {ai_duration:.4f} sekundit", flush=True)
            print(f"JSON parsimise aeg: {parse_duration:.4f} sekundit", flush=True)
            total_duration = time.perf_counter() - start_total_internal
            print(f"Kogu päringu töötlemise aeg: {total_duration:.4f} sekundit", flush=True)
            return json_data
            
        except (json.JSONDecodeError, Exception) as e:
            print(f"Katse {attempts} ebaõnnestus: {str(e)}", flush=True)
            # Tsükkel jätkub automaatselt uue katsega

    # Kui jõuame siia, siis kõik katsed ebaõnnestusid
    return {"error": "Isegi pärast mitut katset ei suutnud AI korrektset JSON-it luua."}

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*50)
    print("RAKENDUS ON VALMIS!")
    print("Testi siit: http://localhost:8000/api/blog/posts")
    print("="*50 + "\n")
    # Starting the server on localhost:8000
    uvicorn.run(app, host="0.0.0.0", port=8000)