# Store AI Writer – backend (Ollama edition, local and free)

Writes product titles, descriptions, SEO titles/descriptions and tags for ANY kind of store
(dresses, toys, books, kitchen, electronics, food, beauty, home, jewelry, sports, or anything else).

## Before you start
1. Install Python 3.10+ (python.org) and tick "Add Python to PATH".
2. Install Ollama from https://ollama.com and make sure it is running.

## Run it (Windows, easy way)
1. Open the `backend` folder.
2. Double-click `setup.bat` (creates the environment, installs packages, downloads the model, tests it).
3. Double-click `run.bat`, then open http://127.0.0.1:8000/ui
4. Open POST /generate -> "Try it out" -> replace the body with an example below -> Execute.

## Run it (manual)
Always run commands INSIDE the `backend` folder.
```
cd backend
python -m venv .venv
.venv\Scripts\activate            # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
ollama pull gemma3:4b
python check_model.py             # should print [ollama:...] and a sentence
python -m pytest                  # all tests should pass (offline)
uvicorn app.main:app --reload     # keep this terminal open
```

## Rules to avoid common mistakes
- Never `pip install app` or `pip install app.service`. `app` is this project's own folder.
- Run tests with `python -m pytest` or `pytest`.
- `http://127.0.0.1:8000/` redirects automatically to `/docs`.

## Example requests
```json
{
  "product": {"title": "Women Red Maxi Dress", "product_type": "Dress",
              "attributes": {"color": "red", "length": "full length"}},
  "options": {"category": "auto", "tone": "professional", "paragraphs": 2, "detail": "detailed"},
  "fields": ["title", "description", "seo_title", "seo_description", "tags"]
}
```
```json
{
  "product": {"title": "Wooden Building Blocks Toy", "attributes": {"material": "wood", "pieces": "50"}},
  "options": {"category": "auto", "paragraphs": 1},
  "fields": ["description", "tags"]
}
```

## Modules
- `app/llm.py` providers (Ollama, optional NVIDIA), rate limit, failover
- `app/prompts.py` prompt builder
- `app/categories.py` per-store-type rules, risky words, auto-detection (add new store types here)
- `app/validators.py` JSON parsing, length / paragraph checks, invented-detail and invented-number checks
- `app/service.py` generate -> check -> retry loop
- `app/main.py`, `app/schemas.py`, `app/config.py` API, formats, settings

## Tips for a 4GB GPU
- Close heavy apps and browser tabs while generating.
- Too slow or out of memory? Set `OLLAMA_MODEL=qwen2.5:1.5b` in `.env` and run `ollama pull qwen2.5:1.5b`.
- Try other models by changing `OLLAMA_MODEL` (for example `gemma3:4b`, `llama3.2:3b`).
- Optional: add a free NVIDIA key and set `PROVIDER_ORDER=nvidia,ollama` to compare quality.
