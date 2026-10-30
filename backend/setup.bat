@echo off
echo === 1/4 Creating virtual environment ===
python -m venv .venv
call .venv\Scripts\activate
echo === 2/4 Installing packages ===
pip install -r requirements.txt
echo === 3/4 Downloading the model (about 2 GB, one time) ===
ollama pull gemma3:4b
echo === 4/4 Testing the model ===
python check_model.py
pause
