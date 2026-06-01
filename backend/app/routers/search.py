from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import SearchRequest, SearchResponse
from app.services.search import execute_search

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
def search(body: SearchRequest, db: Session = Depends(get_db)):
    try:
        return execute_search(db, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
