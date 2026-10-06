"""
IntelliCodeX Enterprise FastAPI Backend Application Entry Point
"""
import logging
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from backend.config import settings
from backend.auth import get_current_user
from backend.api import (
    auth_router, repos_router, chat_router, bugs_router,
    patches_router, graph_router, analytics_router, docs_router, review_router
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="IntelliCodeX Enterprise AI Repository Analysis and Automated Software Maintenance Framework",
)

# Enable CORS for local React development & cross-origin access
# Security: Never allow "*" together with credentials
cors_origins = settings.get_cors_origins()
allow_credentials = True
if "*" in cors_origins:
    logging.warning("CORS configured with wildcard origin ('*'). Disabling allow_credentials for security.")
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Include Enterprise Modular Routers under /api
# auth_router handles /register and /login without token, and /me, /promote with token
app.include_router(auth_router, prefix=settings.API_PREFIX)

# All other modular routers require get_current_user
app.include_router(repos_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])
app.include_router(chat_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])
app.include_router(bugs_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])
app.include_router(patches_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])
app.include_router(graph_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])
app.include_router(analytics_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])
app.include_router(docs_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])
app.include_router(review_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])


@app.get("/")
def root():
    return {
        "title": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "online",
        "docs_url": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok", "version": settings.VERSION}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.API_HOST, port=8000, reload=True)
