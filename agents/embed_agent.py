"""
Embed Agent — semantic search over codebase analysis results.

After a successful analysis run, call `build_index(modules, job_id, docs_dir)`
to embed every file's analysis text into a ChromaDB collection stored alongside
the job results.  The `/ask/{job_id}` endpoint then queries this index to answer
natural-language questions about the codebase.

Embedding model priority (same BYOK chain philosophy as the rest of Arkhe):
  1. Gemini `models/text-embedding-004` — free tier, 768-dim
  2. OpenAI `text-embedding-3-small`    — cheap ($0.02/1M tokens), 1536-dim
  3. Chroma default (all-MiniLM-L6-v2) — local, no API key required, 384-dim

The Chroma collection is stored at <job_results_dir>/chroma/ — persists
across server restarts, no separate process required.
"""
import logging
import os
from pathlib import Path

logger = logging.getLogger("arkhe.embed")

_GEMINI_KEY      = os.getenv("GEMINI_API_KEY", "")
_OPENAI_KEY      = os.getenv("OPENAI_API_KEY", "")
_COLLECTION_NAME = "arkhe_codebase"


# ── Embedding function selection ──────────────────────────────────────────────

def _get_embedding_function():
    """Return the best available ChromaDB embedding function."""
    if _GEMINI_KEY:
        try:
            from chromadb.utils.embedding_functions import GoogleGenerativeAiEmbeddingFunction
            logger.info("[embed] using Gemini text-embedding-004")
            return GoogleGenerativeAiEmbeddingFunction(
                api_key=_GEMINI_KEY,
                model_name="models/text-embedding-004",
            )
        except Exception as e:
            logger.warning(f"[embed] Gemini embedding unavailable: {e}")

    if _OPENAI_KEY:
        try:
            from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
            logger.info("[embed] using OpenAI text-embedding-3-small")
            return OpenAIEmbeddingFunction(
                api_key=_OPENAI_KEY,
                model_name="text-embedding-3-small",
            )
        except Exception as e:
            logger.warning(f"[embed] OpenAI embedding unavailable: {e}")

    # Local fallback — only if sentence_transformers is actually installed
    try:
        import sentence_transformers  # noqa: F401
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        logger.info("[embed] using local all-MiniLM-L6-v2 (no API key)")
        return SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    except ImportError:
        logger.warning("[embed] sentence-transformers not installed, skipping local embed")
    except Exception as e:
        logger.warning(f"[embed] sentence-transformers unavailable: {e}")

    # No embedding backend available — don't let ChromaDB download ONNX models
    return False


# ── Index builder ─────────────────────────────────────────────────────────────

def build_index(modules: list[dict], job_results_dir: str | Path) -> bool:
    """
    Embed each file's analysis text and store in a persistent ChromaDB collection.

    Args:
        modules:         list of module dicts from the analysis pipeline
                         (each needs at least 'path' and 'analysis').
        job_results_dir: the job's results directory (chroma/ subfolder created here).

    Returns True on success, False if no embeddable content or ChromaDB error.
    """
    import chromadb

    ef = _get_embedding_function()
    if ef is False:
        logger.info("[embed] no embedding backend available, skipping index build")
        return False

    embeddable = [m for m in modules if m.get("analysis")]
    if not embeddable:
        logger.info("[embed] no analysis content to index")
        return False

    chroma_dir = Path(job_results_dir) / "chroma"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    try:
        client     = chromadb.PersistentClient(path=str(chroma_dir))
        collection = client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

        # Build docs to upsert — use file path as the document ID
        ids       = []
        documents = []
        metadatas = []

        for m in embeddable:
            path     = m.get("path", "")
            analysis = m.get("analysis", "")
            # Prepend path so the embedding captures file name context
            doc = f"File: {path}\n\n{analysis}"
            ids.append(path)
            documents.append(doc[:8000])  # ChromaDB document size limit
            metadatas.append({
                "path":       path,
                "ext":        m.get("ext", ""),
                "tokens":     m.get("tokens", 0),
                "complexity": m.get("complexity", 0),
                "functions":  ",".join(m.get("structure", {}).get("functions", [])[:20]),
                "classes":    ",".join(m.get("structure", {}).get("classes", [])[:10]),
            })

        # Upsert in batches of 100
        batch = 100
        for i in range(0, len(ids), batch):
            collection.upsert(
                ids=ids[i:i+batch],
                documents=documents[i:i+batch],
                metadatas=metadatas[i:i+batch],
            )

        logger.info(f"[embed] indexed {len(ids)} files into {chroma_dir}")
        return True

    except Exception as e:
        logger.error(f"[embed] failed to build index: {e}")
        return False


# ── Query ─────────────────────────────────────────────────────────────────────

def query_index(
    question: str,
    job_results_dir: str | Path,
    n_results: int = 8,
) -> list[dict]:
    """
    Return the top-N most relevant files for a natural-language question.

    Returns a list of dicts: {path, ext, tokens, complexity, functions, classes, excerpt}
    sorted by relevance (most relevant first).  Returns [] if no index exists.
    """
    import chromadb

    chroma_dir = Path(job_results_dir) / "chroma"
    if not chroma_dir.exists():
        return []

    try:
        client     = chromadb.PersistentClient(path=str(chroma_dir))
        ef         = _get_embedding_function()
        collection = client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=ef,
        )

        if collection.count() == 0:
            return []

        results = collection.query(
            query_texts=[question],
            n_results=min(n_results, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        items = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            # Convert cosine distance to similarity score 0–1
            score   = round(1 - dist, 3)
            excerpt = doc[doc.find("\n\n")+2 :][:400] if "\n\n" in doc else doc[:400]
            items.append({
                "path":        meta.get("path", ""),
                "ext":         meta.get("ext", ""),
                "tokens":      meta.get("tokens", 0),
                "complexity":  meta.get("complexity", 0),
                "functions":   [f for f in meta.get("functions", "").split(",") if f],
                "classes":     [c for c in meta.get("classes", "").split(",") if c],
                "relevance":   score,
                "excerpt":     excerpt,
            })

        return items

    except Exception as e:
        logger.error(f"[embed] query failed: {e}")
        return []


def index_exists(job_results_dir: str | Path) -> bool:
    """Return True if an embedding index exists for this job."""
    chroma_dir = Path(job_results_dir) / "chroma"
    return chroma_dir.exists() and any(chroma_dir.iterdir())
