"""Liveness endpoint."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Report that the process is serving requests."""
    return {"status": "ok"}
