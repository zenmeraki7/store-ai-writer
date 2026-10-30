#!/usr/bin/env bash
set -e
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen2.5:3b
python check_model.py
