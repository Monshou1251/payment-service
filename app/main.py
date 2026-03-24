from fastapi import FastAPI

from app.api.v1.payments import router as payments_router

app = FastAPI(
    title="Payment Processing Service",
    description="Async payment processing microservice",
    version="1.0.0",
)

app.include_router(payments_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
