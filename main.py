import time
from flask import Flask, request, jsonify
import database
import ai_client
import reset_db

app = Flask(__name__)
app.json.sort_keys = False  # Preserve the order of JSON keys as they are defined in the database

# On startup, initialize the database
database.init_db()

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "message": "Tere tulemast API simulatorisse!",
        "instructions": "Siia tuleb hiljem lisainfo",
        "links": "github repo, dokumentatsioon, jne"
    }), 200

@app.route('/delete-all')
def delete_all():
    reset_db.clear_database()
    return jsonify({"message": "All data deleted."}), 200

@app.route('/<path:subpath>')
async def handle_api_request(subpath):
    start_time = time.time()  # Käivitame stopperi
    full_path = "/" + subpath.strip('/')
    
    # 1. Otsime andmebaasist
    existing_data = database.get_resource_by_path(full_path)
    
    if existing_data:
        duration = (time.time() - start_time) * 1000  # Arvutame kestuse millisekundites
        print(f"CACHE HIT: {full_path} kätte saadud {duration:.2f} ms-ga.")
        
        # Lisame vastuse päisesse (header), et näha seda ka brauseris/inspektoris
        response = jsonify(existing_data)
        response.headers['X-Response-Time-MS'] = f"{duration:.2f}"
        return response, 200

    # 2. Kui pole andmebaasis, siis AI
    print(f"CACHE MISS: {full_path} läheb AI-le...")
    new_data = await ai_client.get_ai_content(full_path)
    
    if "error" not in new_data:
        database.save_structured_resource(full_path, new_data)
    
    duration = time.time() - start_time  # AI puhul mõõdame pigem sekundites
    print(f"AI GENERAATOR: Valmis {duration:.2f} sekundiga.")
    
    response = jsonify(new_data)
    response.headers['X-Response-Time-Seconds'] = f"{duration:.2f}"
    return response, 200

if __name__ == '__main__':
    # Start the Flask app
    app.run(debug=True, port=5000)