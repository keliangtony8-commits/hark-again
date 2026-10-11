from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings

from .agent.tools import load_builtin
from .routes import auth, browser, catalog, connectors, conversations, files, home, inbox, memory_digest, pages, resources, tasks, usage, vault, voice, ws


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_builtin()
    yield


app = FastAPI(title="Assistant", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(ws.router)
app.include_router(catalog.router)
app.include_router(files.router)
app.include_router(tasks.router)
app.include_router(vault.router)
app.include_router(connectors.router)
app.include_router(connectors.public)
app.include_router(browser.router)
app.include_router(pages.router)
app.include_router(pages.public)
app.include_router(voice.router)
app.include_router(inbox.router)
app.include_router(home.router)
app.include_router(usage.router)
app.include_router(memory_digest.router)
for r in resources.routers:
    app.include_router(r)


@app.get("/api/health")
async def health():
    return {"ok": True}
