#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Production entrypoint — serves the Flask app with Waitress.

IMPORTANT: run as a SINGLE process (Waitress is one process, multi-threaded).
The app keeps in-memory state (one scan at a time, the live log queue), so do NOT
run multiple workers/instances. Threads handle concurrency fine.

    pip install -r requirements.txt
    python serve.py            # serves on 0.0.0.0:8000 (override with HOST/PORT)
"""
import os

from waitress import serve

from app import app

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "7030"))
    threads = int(os.getenv("WAITRESS_THREADS", "8"))
    print(f"SERP Agent (production) — http://{host}:{port}  threads={threads}")
    # channel_timeout high so long scans / SSE streams aren't dropped.
    serve(app, host=host, port=port, threads=threads, channel_timeout=3600)
