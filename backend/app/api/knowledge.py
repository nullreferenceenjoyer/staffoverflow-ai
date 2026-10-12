import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import APPROVERS, audit, get_current_user, require_roles
from app.models import KnowledgeChunk, KnowledgeDocument, Norm, Role, User
from app.services import rag

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

MAX_UPLOAD_BYTES = 30 * 1024 * 1024


@router.get("/documents")
def list_documents(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    chunks = dict(db.execute(
        select(KnowledgeChunk.document_id, func.count()).group_by(KnowledgeChunk.document_id)
    ).all())
    norms: dict[int, list[dict]] = {}
    for norm in db.scalars(select(Norm).where(Norm.document_id.is_not(None))):
        norms.setdefault(norm.document_id, []).append({"id": norm.id, "title": norm.title})
    documents = db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.title)).all()
    return [
        {
            "id": d.id,
            "title": d.title,
            "doc_type": d.doc_type,
            "source_ref": d.source_ref,
            "is_summary": d.is_summary,
            "has_file": bool(d.file_path),
            "chunks": chunks.get(d.id, 0),
            "norms": norms.get(d.id, []),
            "created_at": d.created_at,
        }
        for d in documents
    ]


@router.get("/search")
def search(q: str, limit: int = 5, db: Session = Depends(get_db),
           _: User = Depends(get_current_user)):
    if len(q.strip()) < 3:
        return []
    return rag.search(db, q.strip(), min(max(limit, 1), 20))


@router.post("/documents", status_code=status.HTTP_201_CREATED)
def upload_document(request: Request, file: UploadFile = File(...), title: str = Form(...),
                    source_ref: str = Form(""), db: Session = Depends(get_db),
                    user: User = Depends(require_roles(*APPROVERS))):
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Файл больше 30 МБ")
    filename = file.filename or "document.txt"
    try:
        text = rag.extract_text(filename, content)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # Имя файла на диске генерируем сами: пользовательское имя в путь не попадает
    relative = Path("knowledge") / f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    target = Path(get_settings().storage_dir) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    document = KnowledgeDocument(title=title.strip()[:400], source_ref=source_ref.strip() or None,
                                 file_path=relative.as_posix())
    try:
        chunks = rag.index_document(db, document, text)
    except ValueError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    db.flush()
    audit(db, user, "knowledge_document_uploaded", entity="knowledge_document",
          entity_id=document.id, details={"title": document.title, "chunks": chunks},
          request=request)
    db.commit()
    return {"id": document.id, "chunks": chunks}


@router.get("/documents/{document_id}/file")
def download_file(document_id: int, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    document = db.get(KnowledgeDocument, document_id)
    if document is None or not document.file_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден")
    path = Path(get_settings().storage_dir) / document.file_path
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден в хранилище")
    return FileResponse(path, filename=f"{document.title[:80]}{path.suffix}")


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(*APPROVERS))):
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    if document.file_path:
        (Path(get_settings().storage_dir) / document.file_path).unlink(missing_ok=True)
    audit(db, user, "knowledge_document_deleted", entity="knowledge_document",
          entity_id=document.id, details={"title": document.title}, request=request)
    db.delete(document)
    db.commit()


@router.post("/reindex")
def reindex(request: Request, db: Session = Depends(get_db),
            user: User = Depends(require_roles(Role.admin))):
    count = rag.reindex_all(db)
    audit(db, user, "knowledge_reindexed", details={"chunks": count}, request=request)
    db.commit()
    return {"chunks": count}
