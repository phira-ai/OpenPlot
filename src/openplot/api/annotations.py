from __future__ import annotations

from fastapi import APIRouter

from ..models import Annotation
from ..services import annotations as annotations_service
from .schemas import AnnotationUpdateRequest

router = APIRouter()


@router.post("/api/annotations")
async def add_annotation(annotation: Annotation):
    return await annotations_service.add_annotation(annotation)


@router.get("/api/annotations/{annotation_id}/export")
async def export_annotation_plot(annotation_id: str):
    return await annotations_service.export_annotation_plot(annotation_id)


@router.delete("/api/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str):
    return await annotations_service.delete_annotation(annotation_id)


@router.patch("/api/annotations/{annotation_id}")
async def update_annotation(annotation_id: str, updates: AnnotationUpdateRequest):
    return await annotations_service.update_annotation(annotation_id, updates)
