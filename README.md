# AI-põhine REST API simulaator

See projekt on dünaamiline REST API simulaator, mis kasutab generatiivset tehisintellekti andmete genereerimiseks siis, kui vastavat ressurssi pole veel andmebaasis olemas.

Rakendus toetab:
- automaatset andmete genereerimist kasutaja soovitud lõpp-punktidele
- SQLite-põhist cache'i ja dünaamilisi tabeleid
- andmeskeemi valideerimist (uued kirjed peavad sobituma olemasoleva struktuuriga)
- kustutatud ressursside blacklisti (et neid ei genereeritaks uuesti)
- kollektsioonipäringute limit parameetrit

## Tehniline stack
- Flask 3 (async route toega)
- OpenAI Python SDK (AsyncOpenAI)
- SQLite
- python-dotenv
- pytest

## Kaustastruktuur
Töökood asub kaustas code.

Peamised failid:
- code/main.py - Flask API lõpp-punktid
- code/database.py - cache, dünaamilised tabelid, andmeskeemi (schema) velideerimine, blacklist
- code/ai_client.py - AI päringud (OpenAI voi Ollama OpenAI-compatible endpoint)
- code/reset_db.py - andmebaasi nullimine
- code/tests - testid

## Nõuded
- Python 3.10+
- (Valikuline) OpenAI API voti
  - või lokaalne Ollama server OpenAI-compatible endpointiga

## Seadistamine (Windows / PowerShell)
1. Mine projekti kausta:
  cd code
2. Loo virtuaalkeskkond:
  py -m venv .venv
3. Aktiveeri virtuaalkeskkond:
  .\.venv\Scripts\Activate.ps1
4. Installi sõltuvused:
  pip install -r requirements.txt

## Keskkonnamuutujad
Failis code/.env:

- USE_OPENAI=true kasutab OpenAI-t
- USE_OPENAI=false kasutab lokaalset Ollama endpointi
- OPENAI_API_KEY vajalik ainult siis, kui USE_OPENAI=true

Näidis:

USE_OPENAI=true
OPENAI_API_KEY=your-api-key

## Rakenduse käivitamine
Kaustas code:

python main.py

Vaikimisi aadress:
- http://127.0.0.1:5000

## Lõpp-punktid

### GET /
Tagastab lihtsa API tutvustuse

### GET / path
Otsib andmed järgmises järjekorras:
1. cached_responses
2. dünaamilised tabelid
3. AI genereerimine

Oluline:
- kui path on blacklistis, tagastatakse 404 RESOURCE_DELETED
- nested collection puhul (nt /books/999/comments) genereeritakse parent ressurss tehisintellekti poolt automaatselt
- andmestruktuuri vastuolu korral tagastatakse 422 SCHEMA_MISMATCH

### GET / collection?limit=N
Toetatud ainult kollektsioonidel (path ei tohi lõppeda numbriga).

**Reeglid**:
- N peab olema positiivne täisarv
- kui olemasolevaid kirjeid on vähem kui limit ette näeb, genereeritakse (ainult) puuduolev arv ressursse juurde
- kui olemasolevaid on rohkem, tagastatakse soovitud pikkusega nimekiri
- korduv limit parameetri kasutamine annab error 400

### POST / collection
Lisab uue kirje.

Reeglid:
- POST item endpointile (nt /books/1) on keelatud (403)
- request body peab olema korrektne JSON
- id genereeritakse automaatselt, kui puudub
- nested kollektsioonis lisatakse parent foreign key automaatselt (nt book_id)
- kui schema on juba olemas, peab payload schema'ga sobima

### PUT / item
Uuendab olemasolevat itemit.

Reeglid:
- lubatud ainult pathidele, mis loppavad numbriga
- kustutatud (blacklistis) itemit ei saa uuendada (404 RESOURCE_DELETED)
- payload id peab klappima path id-ga
- nested puhul peab parent fk klappima pathiga
- tundmatud valjad annavad 422 SCHEMA_MISMATCH

### DELETE / item
Kustutab itemi ja lisab selle blacklisti.

Reeglid:
- lubatud ainult item endpointidel (numbriline lopp)
- kollektsiooni kustutamine on keelatud (403)
- kui item puudub, tagastatakse 404
- korduv kustutamine tagastab 200 koos already_deleted=true
- nested itemi kustutamisel blokeeritakse ka alias (nt /comments/1)

### DELETE /delete-all
Kustutab kogu andmebaasi (cache + blacklist) ja initsialiseerib uuesti.

Teised meetodid sellele endpointile tagastavad 405.

## Vastuse päised
Rakendus lisab ajamõõtmise paiseid:
- X-Response-Time-MS (kui vastus tuleb otse rakenduselt)
- X-Response-Time-Seconds (kui vastus genereeritakse tehisintellekti poolt)

## Testimine
Kaustas code:

- Kõik testid:
  - pytest (näeb testide edenemist)
  - pytest -q (näeb ainult lõpptulemust)
  - pytest -s (näeb ka rakenduse antud vastuseid ja logisid)

- Järjestatud endpoint testid:
  python tests/run_ordered_endpoint_tests.py

Testid katavad muuhulgas:
- cache hit/miss loogika
- nested ressursside parent context
- schema mismatch käitumine
- delete + blacklist kaitumine
- POST/PUT valideerimine
- limit parameetri käitumine

## Levinud probleemid
- Flask async route toeks peab olema Flask[async] (see on requirements failis olemas).
- Kui kasutad OpenAI-t, kontrolli et OPENAI_API_KEY on seadistatud.
- Kui kasutad Ollama't, kontrolli et server töötab ja base_url sobib failis code/ai_client.py.
