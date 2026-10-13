"""
API Routers Package
"""
from backend.api.auth import router as auth_router
from backend.api.repos import router as repos_router
from backend.api.chat import router as chat_router
from backend.api.bugs import router as bugs_router
from backend.api.patches import router as patches_router
from backend.api.graph import router as graph_router
from backend.api.analytics import router as analytics_router
from backend.api.docs import router as docs_router
from backend.api.review import router as review_router
from backend.api.query import router as query_router
from backend.api.concurrency import router as concurrency_router, gpu_manager
from backend.api.multi_repo import router as multi_repo_router
from backend.api.org_memory import router as org_memory_router
