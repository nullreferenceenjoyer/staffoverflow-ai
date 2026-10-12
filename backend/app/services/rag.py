"""База знаний: разбор документов, эмбеддинги и поиск по смыслу (pgvector)."""

from __future__ import annotations

import io
import math
import re
import zlib

import httpx
from docx import Document as DocxDocument
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import KnowledgeChunk, KnowledgeDocument, Norm

HASH_DIM = 512
CHUNK_SIZE = 900
CHUNK_OVERLAP = 150

_WORD = re.compile(r"[a-zа-я0-9]+")


def hashing_embedding(text: str) -> list[float]:
    """Вектор без нейросети: хэшированные слова и символьные триграммы.

    Триграммы сглаживают русскую морфологию («логопеда», «логопедов» дают
    почти одинаковые векторы). Это заметно слабее настоящей модели эмбеддингов,
    зато работает офлайн и без лишних гигабайт памяти. Для боевого контура
    стоит включить EMBEDDING_BACKEND=openai с моделью вроде bge-m3.
    """
    vector = [0.0] * HASH_DIM
    words = _WORD.findall(text.lower().replace("ё", "е"))
    for word in words:
        features = [word]
        padded = f" {word} "
        features += [padded[i:i + 3] for i in range(len(padded) - 2)]
        for feature in features:
            digest = zlib.crc32(feature.encode())
            sign = 1.0 if digest & 1 else -1.0
            vector[(digest >> 1) % HASH_DIM] += sign
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


def embed(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    if settings.embedding_backend != "openai":
        return [hashing_embedding(t) for t in texts]
    response = httpx.post(
        f"{settings.embedding_base_url.rstrip('/')}/embeddings",
        json={"model": settings.embedding_model, "input": texts},
        timeout=120,
    )
    response.raise_for_status()
    return [item["embedding"] for item in response.json()["data"]]


def extract_text(filename: str, content: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if name.endswith(".docx"):
        document = DocxDocument(io.BytesIO(content))
        return "\n".join(p.text for p in document.paragraphs)
    if name.endswith((".txt", ".md")):
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return content.decode("cp1251")
    raise ValueError("Поддерживаются файлы .pdf, .docx, .txt и .md")


def split_into_chunks(text: str) -> list[str]:
    """Режет текст на куски по границам абзацев с небольшим перекрытием."""
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n|\n", text)]
    chunks: list[str] = []
    current = ""
    for paragraph in filter(None, paragraphs):
        # Абзац длиннее чанка (сплошной текст из PDF) режем принудительно
        while len(paragraph) > CHUNK_SIZE:
            head, paragraph = paragraph[:CHUNK_SIZE], paragraph[CHUNK_SIZE - CHUNK_OVERLAP:]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        if len(current) + len(paragraph) + 1 > CHUNK_SIZE and current:
            chunks.append(current)
            current = current[-CHUNK_OVERLAP:]
        current = f"{current} {paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks


def index_document(db: Session, document: KnowledgeDocument, text: str) -> int:
    chunks = split_into_chunks(text)
    if not chunks:
        raise ValueError("В документе не найден текст")
    document.chunks = [
        KnowledgeChunk(ordinal=i, content=chunk, embedding=vector)
        for i, (chunk, vector) in enumerate(zip(chunks, embed(chunks), strict=True))
    ]
    db.add(document)
    return len(chunks)


def reindex_all(db: Session) -> int:
    """Пересчитывает все эмбеддинги — нужно после смены EMBEDDING_BACKEND."""
    chunks = db.scalars(select(KnowledgeChunk).order_by(KnowledgeChunk.id)).all()
    for start in range(0, len(chunks), 32):
        batch = chunks[start:start + 32]
        for chunk, vector in zip(batch, embed([c.content for c in batch]), strict=True):
            chunk.embedding = vector
    return len(chunks)


def search(db: Session, query: str, limit: int = 5) -> list[dict]:
    query_vector = embed([query])[0]
    distance = KnowledgeChunk.embedding.cosine_distance(query_vector)
    rows = db.execute(
        select(KnowledgeChunk, KnowledgeDocument, distance.label("distance"))
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .where(KnowledgeChunk.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    ).all()

    document_ids = {document.id for _, document, _ in rows}
    linked: dict[int, list[dict]] = {}
    if document_ids:
        for norm in db.scalars(select(Norm).where(Norm.document_id.in_(document_ids))):
            linked.setdefault(norm.document_id, []).append(
                {"id": norm.id, "code": norm.code, "title": norm.title}
            )
    return [
        {
            "document_id": document.id,
            "title": document.title,
            "source_ref": document.source_ref,
            "is_summary": document.is_summary,
            "content": chunk.content,
            "score": round(1 - float(dist), 3),
            "norms": linked.get(document.id, []),
        }
        for chunk, document, dist in rows
    ]
