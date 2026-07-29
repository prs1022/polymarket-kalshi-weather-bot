#!/usr/bin/env python3
"""Run the trading bot backend server."""
import os
import logging
import uvicorn
from backend.models.database import init_db

# Configure file logging
log_dir = os.path.join(os.path.dirname(__file__), ".run", "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "app.log")

file_handler = logging.FileHandler(log_file, encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
logging.getLogger().addHandler(file_handler)
logging.getLogger("trading_bot").addHandler(file_handler)
logging.getLogger("uvicorn").addHandler(file_handler)

if __name__ == "__main__":
    print("Initializing database...")
    init_db()

    port = int(os.environ.get("PORT", 8000))
    print(f"Starting server on http://0.0.0.0:{port}")
    print(f"API docs available at http://localhost:{port}/docs")
    print(f"Log file: {log_file}")

    uvicorn.run(
        "backend.api.main:app",
        host="0.0.0.0",
        port=port,
        reload=os.environ.get("RAILWAY_ENVIRONMENT") is None
    )
