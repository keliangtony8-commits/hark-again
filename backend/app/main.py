from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .preview import PREFIX as PREVIEW_PREFIX

from . import turn_journal
from .agent.tools import load_builtin
from .routes import auth, browser, catalog, connectors, conversations, files, home, host, inbox, jobs, memory_digest, pages, preview, resources, tasks, usage, vault, voice, ws


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_builtin()
    await turn_journal.recover_all("backend")  # 上次进程被杀时没答完的回答 → interrupted 消息
    yield


class AppCORS(CORSMiddleware):
    """App 自己的跨源规则；端口预览（/api/preview/…）跳过：那里的跨源头由 preview.py 自己给（预览页是不透明源，Origin: null）。"""
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(PREVIEW_PREFIX + "/"):
            return await self.app(scope, receive, send)
        return await super().__call__(scope, receive, send)


app = FastAPI(title="Assistant", lifespan=lifespan)
app.add_middleware(AppCORS, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
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
app.include_router(preview.router)
app.include_router(preview.public)
app.include_router(voice.router)
app.include_router(inbox.router)
app.include_router(jobs.router)
app.include_router(home.router)
app.include_router(host.router)
app.include_router(usage.router)
app.include_router(memory_digest.router)
for r in resources.routers:
    app.include_router(r)


@app.get("/api/health")
async def health():
    return {"ok": True}
