from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .llm import LLMError
from .quick import router as quick_router
from .schemas import GenerateRequest, GenerateResponse
from .service import generate_content
from .shopify import router as shopify_router

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Store AI Writer")
app.include_router(shopify_router)
app.include_router(quick_router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui")


@app.get("/ui", include_in_schema=False)
def ui():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


# Plain `def` so FastAPI runs the blocking model call in a worker thread.
@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    try:
        result, provider, warnings = generate_content(req)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return GenerateResponse(result=result, provider=provider, warnings=warnings)
