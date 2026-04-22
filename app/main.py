"""
FastAPI 主入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.config import settings
from app.database import Base, engine
from app.datasets.router import router as datasets_router
from app.sts.router import router as sts_router

# 创建所有数据库表（生产环境建议使用 alembic migrate）
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="EvoData API",
    description="EvoData 机器人数据平台后端 API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由注册
app.include_router(auth_router)
app.include_router(datasets_router)
app.include_router(sts_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "evo-data-backend"}
