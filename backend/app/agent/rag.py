"""Local, persistent RAG over ``tactics_kb/`` (plan section 5).

Embeds the markdown notes under ``tactics_kb/`` with a small CPU
``sentence-transformers`` model and stores them in a Chroma collection on
disk. The index is rebuilt only when the source notes change (the index
records each note's content hash, so an unchanged ``tactics_kb/`` is a no-op).

Public surface:

- ``retrieve(query, top_k=3)`` — semantic search; returns the matching chunks
  with their note name and a similarity score.

Heavy deps (``chromadb``, ``sentence_transformers``) are imported lazily so
they only load the first time a tactics question is asked, keeping the
``ask.py`` CLI startup snappy for the other tools.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# repo root / tactics_kb. backend/app/agent/rag.py -> backend/app/agent -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = _REPO_ROOT / "tactics_kb"

# Persistent Chroma directory + collection name. Kept under backend/ so it ships
# with the code and lives outside data_cache/ (which is gitignored).
_CHROMA_DIR = Path(__file__).resolve().parents[2] / "data_cache" / "chroma"
_COLLECTION = "tactics_kb"

# Small, fast, CPU-friendly embedding model. ~80MB; downloaded once.
_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Cached modules / clients (lazy).
_collection = None  # chromadb collection
_embedder = None    # SentenceTransformer


def _load_notes() -> list[dict[str, Any]]:
    """Read every ``.md`` under ``tactics_kb/`` as a single chunk per file.

    The notes are deliberately short (a few hundred words each), so one chunk
    per file gives clean, self-contained retrieval. If notes grow long, swap
    this for a paragraph splitter — interface stays the same.
    """
    if not KB_DIR.exists():
        return []
    notes: list[dict[str, Any]] = []
    for path in sorted(KB_DIR.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue  # the placeholder index file is not retrievable content
        text = path.read_text().strip()
        if not text:
            continue
        notes.append(
            {
                "id": path.stem,
                "text": text,
                "source": path.name,
                "sha": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
            }
        )
    return notes


def _get_embedder():
    """Return the cached sentence-transformers model (loaded once)."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer  # local heavy import
        logger.info("Loading embedding model %s (CPU)", _EMBED_MODEL)
        _embedder = SentenceTransformer(_EMBED_MODEL)
    return _embedder


def _get_collection():
    """Return the persistent Chroma collection, building/refreshing the index if stale."""
    global _collection
    if _collection is not None:
        return _collection

    import chromadb  # local heavy import
    _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
    coll = client.get_or_create_collection(name=_COLLECTION)

    notes = _load_notes()
    # Build a content signature for the current notes and stash it on the
    # collection metadata. If it matches what's already in Chroma we skip
    # re-embedding entirely (the typical case after the first run).
    current_sig = hashlib.sha256(
        "|".join(f"{n['id']}:{n['sha']}" for n in notes).encode("utf-8")
    ).hexdigest()
    existing_sig = (coll.metadata or {}).get("kb_sig") if coll.metadata else None

    if existing_sig != current_sig or coll.count() != len(notes):
        logger.info("Rebuilding tactics_kb index (%d notes)", len(notes))
        # Clear + re-embed. Chroma's small collections rebuild in milliseconds
        # once the model is in memory; the slow part is just the first model load.
        existing_ids = coll.get()["ids"]
        if existing_ids:
            coll.delete(ids=existing_ids)
        if notes:
            embedder = _get_embedder()
            embeddings = embedder.encode(
                [n["text"] for n in notes],
                show_progress_bar=False,
                normalize_embeddings=True,
            ).tolist()
            coll.add(
                ids=[n["id"] for n in notes],
                documents=[n["text"] for n in notes],
                metadatas=[{"source": n["source"], "sha": n["sha"]} for n in notes],
                embeddings=embeddings,
            )
        # Persist the content signature on the collection so a subsequent run
        # with unchanged notes is a no-op (no model load, no re-embed).
        coll.modify(metadata={"kb_sig": current_sig})

    _collection = coll
    return _collection


def retrieve(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Semantic search over the tactics knowledge base.

    Returns a list of ``{id, source, text, score}`` dicts sorted by descending
    relevance. ``score`` is ``1 - cosine_distance`` so higher = more similar
    (Chroma returns squared L2 over normalised vectors; we map it back).
    Returns ``[]`` if the KB is empty.
    """
    coll = _get_collection()
    if coll.count() == 0:
        return []
    embedder = _get_embedder()
    q_emb = embedder.encode(
        [query], show_progress_bar=False, normalize_embeddings=True
    ).tolist()
    res = coll.query(query_embeddings=q_emb, n_results=min(top_k, coll.count()))
    hits: list[dict[str, Any]] = []
    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]
    for i, doc, meta, dist in zip(ids, docs, metas, dists):
        # With normalised embeddings, chroma's default L2-squared distance d
        # satisfies cos_sim = 1 - d/2. Clamp into [0, 1] for display.
        score = max(0.0, min(1.0, 1.0 - float(dist) / 2.0))
        hits.append(
            {
                "id": i,
                "source": (meta or {}).get("source", i),
                "text": doc,
                "score": round(score, 4),
            }
        )
    return hits
