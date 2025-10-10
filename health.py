from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
def health_check():
    """
    Lightweight health check endpoint.
    Used by Render or uptime monitors to confirm the app is alive.
    """
    return {"status": "ok"}