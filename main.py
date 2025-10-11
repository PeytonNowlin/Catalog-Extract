#!/usr/bin/env python3
"""
Catalog Extractor - Main entry point
Launches the FastAPI web server with UI
"""
import uvicorn
from api import app

if __name__ == "__main__":
    print("=" * 60)
    print("Catalog Extractor - Starting Server")
    print("=" * 60)
    print()
    print("Web UI:       http://localhost:8000")
    print("API Docs:     http://localhost:8000/docs")
    print("Health Check: http://localhost:8000/api/health")
    print()
    print("Press CTRL+C to stop the server")
    print("=" * 60)
    print()
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )

