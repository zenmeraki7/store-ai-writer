@echo off
call .venv\Scripts\activate
echo Open http://127.0.0.1:8000/ui in your browser
uvicorn app.main:app --reload
