from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.database import connect_to_mongo, close_mongo_connection
from fastapi.middleware.cors import CORSMiddleware
from src.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Connect to MongoDB
    await connect_to_mongo()
    yield
    # Shutdown: Close MongoDB connection
    await close_mongo_connection()

from src.templates.router import router as templates_router
from src.auth.router import router as auth_router
from src.communication.router import router as communication_router
from src.reminders.router import router as reminders_router
from src.users.router import router as users_router
from src.recipients.router import router as recipients_router

app = FastAPI(
    title="CCIRP API",
    description="Central Communication and Intelligent Reminder Platform",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(templates_router)
app.include_router(auth_router)
app.include_router(communication_router)
app.include_router(reminders_router)
app.include_router(users_router)
app.include_router(recipients_router)

from src.config import settings

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

@app.get("/")
async def root():
    return {"message": "CCIRP Backend Running"}