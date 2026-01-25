# AI-põhine REST API simulaator (Rakendusinformaatika lõputöö projekt)

See projekt simuleerib dünaamilist REST API-t, kasutades Llama 3.2 (1b) mudelit. 
Süsteem suudab genereerida realistlikke JSON-vastuseid vastavalt etteantud kontekstile.

## Tehniline lahendus
- **FastAPI**: Kiire ja moodne veebiraamistik.
- **Ollama**: Lokaalne LLM-i jooksutamise keskkond.
- **Robustsus**: Rakendatud on `while`-tsüklil põhinev enesekorrigeerimise loogika ja regex/string puhastusfilter, et tagada korrektne JSON väljund ka mudeli ebatäpsuste korral.

## Enne rakenduse kasutamist
- **Installi arvutisse Ollama**
- Installi Python (13.4.2)
- Veendu, et mõlemad oleksid lisatud süsteemi otsinguteele (PATH), et võimaldada käskude `pip`, `python` ja `ollama` kasutamist käsureal

## Seadistamine
1. Loo virtuaalkeskkond: `python -m venv venv`
2. Aktiveeri: `venv\Scripts\activate` (Windows)
3. Installi sõltuvused: `pip install -r requirements.txt`
4. Veendu, et Ollama on käivitatud ja mudel tõmmatud: `ollama pull llama3.2:1b`

## Käivitamine
```bash
python server.py
```

## Kasutamine
- Rakenduse baasaadress: `http://localhost:8000/api`
- Päringute struktuur: `/api/{context}/{category}/{id}`
  - context - mis API-ga on tegemist (blogi)
  - category - mis ressurssi soovitakse (nt postitused)
  - id - ühe konkreetse ressursi detailid
- Testimine: Päringuid saab sisestada otse veebibrauseri aadressiribale või kasutada HTTP-kliente (nt Axios).
