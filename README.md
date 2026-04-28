# TI-põhine REST API simulaator

See projekt on dünaamiline REST API simulaator, mis kasutab generatiivset tehisintellekti andmete genereerimiseks siis, kui vastavat ressurssi pole veel andmebaasis olemas.

Rakendus toetab:
- automaatset andmete genereerimist kasutaja soovitud lõpp-punktidele
- CRUD operatsioone (ressursside lugemine, loomine, muutmine ning kustutamine)
- dünaamilist lõpp-punktide haldust SQLite dünaamiliste tabelitega
- andmeskeemi valideerimist (uued kirjed peavad sobituma olemasoleva struktuuriga)
- kustutatud ressursside musta nimekirja (blacklisti) (et neid ei genereeritaks uuesti)
- päringuparameetrite kasutamist
  - ``` limit ``` parameeter konkreetse arvu objektide saamiseks
  - ``` schema ``` parameeter soovitud andmeskeemi ette andmiseks
  - dünaamilised parameetrid andmete sorteerimiseks ja filtreerimiseks

## Käivitamine Dockeri konteineris
- Veendu, et sul on arvutisse installitud Docker ning et see töötab
- ``` /code ``` kausta
- Loo ``` .env ``` fail näidise põhjal
- Veendu, et oled terminaliga ``` code ``` kaustas ning sisesta järgnevad käsud:
  - ```bash
    docker build -t ai-simulaator .
    ```
  - ```bash
    docker run -p 5000:5000 --env-file .env ai-simulaator
    ```

## Projektis kasutatud tehnoloogiad
- Programmeerimiskeel Python
- Flask 3 (async toega)
- OpenAI Python SDK (AsyncOpenAI)
- SQLite
- Python-dotenv
- Pytest

## Kaustastruktuur
Rakendus asub kaustas code.

Peamised failid:
- code/main.py - Flask API lõpp-punktid, rakenduse põhiloogika
- code/database.py - dünaamilised tabelid, andmete valideerimine ja salvestamine/muutmine/kustutamine, must nimekiri (blacklist)
- code/ai_client.py - TI päringud (OpenAI GPT 4o-mini) ja kõik sellega seonduv
- code/reset_db.py - andmebaasi nullimine
- code/tests - testid
- code/templates - testrakenduse ja dokumentatsiooni HTML failid

## Nõuded
- Python 3.10+
- OpenAI API võti

## Ilma dockerita seadistamine ja käivitamine (Windows / PowerShell)
1. Mine projekti kausta:
  ``` cd code ```
2. Loo virtuaalkeskkond:
  ``` py -m venv .venv ```
3. Aktiveeri virtuaalkeskkond:
  ``` .\.venv\Scripts\Activate.ps1 ```
4. Installi sõltuvused:
  ``` pip install -r requirements.txt ```
5. Loo näidise põhjal .env fail
6. Käivita rakendus: ``` python main.py ```

## Keskkonnamuutujad
Failis code/.env:

- USE_OPENAI=true kasutab OpenAI-d
- USE_OPENAI=false kasutab lokaalset Ollama endpointi (võimalus on olemas, kuid rakendus on testitud OpenAI GPT-4o-mini mudeliga)
- OPENAI_API_KEY vajalik ainult siis, kui USE_OPENAI=true
- API_SPECIFICATION sisaldab esialgset infot selle kohta, mis API-t simuleeritakse

Näidis:

```
USE_OPENAI=true
OPENAI_API_KEY=your-api-key
API_SPECIFICATION="You are an API for Student Homework Management. Key domains: Users (Admin/Student), Assignments (Deadlines/Content), Tags (Academic Platforms), Comments, and Personal Task Statuses. Generate consistent, linked data suitable for testing a student-facing web application."
```
> **NB!** Testrakenduse töötamiseks on vajalik kasutada ülaltoodud API spetsifikatsiooni.


# Lõpp-punktid

## GET /
Tagastab API tutvustuse

## GET /documentation
Tagastab API hetkeseisu (ressursid, spetsifikatsioon, ka kõik staatilised lõpp-punktid jms)

## GET/POST /specification
Tagastab ning võimaldab muuta API kirjeldust, mida rakendus simuleerib.

## GET /tester
Seal asub koolitööde haldamise näidisrakendus ning API tööriist, millega API-t testida. NB! Koolitööde rakenduse töötamiseks taasta vaikeseaded ning tühjenda andmebaas.

## GET /path
Otsib andmed järgmises järjekorras:
1. dünaamilised tabelid
2. TI genereerimine

>**Oluline:**
>  - kui tee on mustas nimekirjas, tagastatakse 404 RESOURCE_DELETED
>  - pesastatud kollektsiooni puhul (nt /books/999/comments) genereeritakse vanemressurss tehisintellekti poolt automaatselt
>  - andmestruktuuri vastuolu korral tagastatakse 422 SCHEMA_MISMATCH
>  - kui tegemist on esimese genereerimisega, saab kasutaja anda schema päringu (query) parameetriga ette oodatud väljad

GET päringute puhul võib päringukeha (request body) jääda tühjaks.

### Schema päringuparameeter
Andmeskeemi päringuparameeter (esimene genereerimine):
- `GET /movies?schema=title,genre`
- `GET /movies?schema=title&schema=genre`
> Kui tabeli schema on juba olemas ja antud schema erineb olemasolevast, tagastatakse 409 SCHEMA_CONFLICT

### Limit päringuparameeter
- Nt: `/movies?limit=7`
- Toetatud ainult kollektsioonidel (tee ei tohi lõppeda numbriga).

>**Reeglid**:
>- N peab olema positiivne täisarv
>- kui olemasolevaid kirjeid on vähem kui `limit` ette näeb, genereeritakse (ainult) puuduolev arv ressursse juurde
>- kui olemasolevaid ressursse on rohkem, tagastatakse soovitud pikkusega nimekiri
>- korduv `limit` parameetri kasutamine annab vastuseks error 400

### Muud päringuparameetrid
- Nt: `/movies?genre=horror,fiction&language=english`
- Esimese parameetri ette käib ? ja edaspidiste ette &
>Kui sisestada komaga mitu sama parameetri alla käivad otsingusõna, otsitakse andmebaasist täpselt seda kombinatsiooni
> - nt parameetri `?ingredients=chicken,egg` puhul otsitakse retseptid, kus on `chicken` JA `egg` (sama retsepti) sees
> - parameetri `?ingredients=cihken&ingredients=egg` puhul otsitakse retsepte, kus on `chicken`, ja retsepte, kus on `egg`, eraldi

## POST /collection (/books)
Lisab uue kirje.

**Näide POST /assignments:**
```
  {
  "created_at": "2023-10-05T16:00:00Z",
  "id": "5",
  "title": "Computer Science Programming Assignment",
  "deadline": "2023-10-12T23:59:59Z",
  "status": "pending",
  "description": "Develop a simple calculator application in Python."
  }
```

>Reeglid:
>- POST item lõpp-punktile (nt /books/1) on keelatud (403)
>- päringukeha (request body) peab olema korrektne JSON, kus on kirjeldatud ressurss, mida soovitakse lisada
>- id genereeritakse automaatselt, kui puudub
>- pesastatud kollektsioonis lisatakse parent foreign key automaatselt (nt book_id)
>- kui andmeskeem on juba olemas, peavad andmed sellega sobima

## PATCH /item (/books/1)
Uuendab olemasolevat üksikobjekti.

**Näide PATCH /assignments/5:**
```
  {
    "created_at": "2026-10-05T16:00:00Z",
    "id": "5",
    "status": "ready",
    "description": "Develop a simple calculator application in Python."
  }
```

>Reeglid:
>- lubatud ainult teedele, mis lõpevad numbriga
>- kustutatud objekti ei saa uuendada (404 RESOURCE_DELETED)
>- payload id peab klappima path id-ga
>- pesastatud objekti puhul peab parent fk (vanemobjektile viitav võõrvõti) klappima tees olevaga
>- tundmatud väljad annavad 422 SCHEMA_MISMATCH

## DELETE /item (books/1)
Kustutab objekti ja lisab selle musta nimekirja.

>Reeglid:
>- lubatud ainult üksikobjekti lõpp-punktidel (numbriline lõpp)
>- kollektsiooni kustutamine on keelatud `(error 403)`
>- kui objekt puudub, tagastatakse `error 404`
>- korduv kustutamine tagastab `200` koos sõnumiga already_deleted=true
>- pesastatud objekti kustutamisel blokeeritakse ka alias (nt /comments/1)

## DELETE /delete-all
Kustutab kogu andmebaasi (tables + blacklist) ja initsialiseerib selle uuesti.

Teised meetodid sellele endpointile tagastavad `error 405`.

# Vastuse päised
Rakendus lisab ajamõõtmise päiseid:
- `X-Response-Time-MS` (kui vastus tuleb otse rakenduselt)
- `X-Response-Time-Seconds` (kui vastus genereeritakse tehisintellekti poolt)

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
- delete + blacklist käitumine
- POST/PATCH valideerimine
- limit parameetri käitumine

## Levinud probleemid
- Flask async route toeks peab olema installitud Flask[async] (see on requirements failis olemas).
- Kui kasutad OpenAI-d, kontrolli et OPENAI_API_KEY on seadistatud.
- Kui kasutad Ollama't, kontrolli et server töötab ja base_url sobib failis code/ai_client.py.
