#!/usr/bin/env python3
"""INSPECT-AI Pro Server (Port 8789) - 立讯/宁德时代级工业视觉质检终端.

Usage:
    python -m uvicorn service.api:app --host 0.0.0.0 --port 8789
    
Or:
    uv run python serve.py
"""

from __future__ import annotations

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# Create app
app = FastAPI(
    title="INSPECT-AI Pro",
    description="立讯/宁德时代级工业视觉质检终端",
    version="2.0.0"
)

# Mount static files with index_v2.html as default
STATIC_DIR = Path(__file__).parent / "src" / "service" / "static"

@app.get("/")
async def root():
    """Serve index_v2.html as default."""
    from fastapi.responses import FileResponse
    return FileResponse(str(STATIC_DIR / "index_v2.html"))

# Mount other static assets
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    print("=" * 70)
    print("🚀 INSPECT-AI Pro Server Starting...")
    print("=" * 70)
    print(f"📍 Address: http://localhost:8789")
    print(f"📍 Version: {app.version}")
    print(f"📍 Description: {app.description}")
    print("=" * 70)
    print("✅ All Stage 2 Features Ready:")
    print("   • 4K Defect Zoom (0.25x - 4.0x)")
    print("   • Physical Metric Caliper (mm/mm²)")
    print("   • ISO-9001 Certificate Export")
    print("   • Fourier/Sobel Heatmap Framework")
    print("=" * 70)
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8789)
