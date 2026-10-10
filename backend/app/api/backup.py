"""备份、恢复与数据目录路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.services import backup_service

router = APIRouter(prefix="/api", tags=["backup"])


class RestoreRequest(BaseModel):
    name: str
    confirm: bool = False


@router.get("/data-dir")
def data_dir() -> dict:
    return backup_service.data_dir_info()


@router.post("/backup")
def create_backup(db: Session = Depends(get_db)) -> dict:
    return backup_service.create_backup(db)


@router.get("/backups")
def list_backups() -> dict:
    return {"items": backup_service.list_backups()}


@router.post("/restore")
def restore(payload: RestoreRequest, db: Session = Depends(get_db)) -> dict:
    if not payload.confirm:
        raise ValidationError("恢复会覆盖当前数据，必须显式确认（confirm=true）")
    return backup_service.restore_backup(db, payload.name)


@router.post("/cache/clean")
def clean_cache() -> dict:
    return backup_service.clean_cache()
