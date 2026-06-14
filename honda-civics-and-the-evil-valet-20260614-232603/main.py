#!/usr/bin/env python3
"""Honda Civics and the Evil Valet — REST API
Source: [HN] https://juniperspring.org/posts/honda-evil-valet/
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn, json, time
from datetime import datetime

app = FastAPI(title="Honda Civics and the Evil Valet", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Models ──
class Item(BaseModel):
    id: int | None = None
    name: str
    data: dict = {}

# ── Store ──
items: dict[int, Item] = {}
next_id = 1

# ── Routes ──
@app.get("/")
def root():
    return {"service": "Honda Civics and the Evil Valet", "version": "0.1.0", "uptime": time.time() - START}

@app.get("/health")
def health():
    return {"ok": True, "items": len(items)}

@app.get("/items")
def list_items():
    return list(items.values())

@app.post("/items")
def create_item(item: Item):
    global next_id
    item.id = next_id
    items[next_id] = item
    next_id += 1
    return item

@app.get("/items/{item_id}")
def get_item(item_id: int):
    if item_id not in items:
        raise HTTPException(404, "Not found")
    return items[item_id]

@app.delete("/items/{item_id}")
def delete_item(item_id: int):
    if item_id not in items:
        raise HTTPException(404, "Not found")
    del items[item_id]
    return {"ok": True}

START = time.time()

if __name__ == "__main__":
    print(f"🚀 {{title}} API starting on :8083")
    uvicorn.run(app, host="0.0.0.0", port=8083)
