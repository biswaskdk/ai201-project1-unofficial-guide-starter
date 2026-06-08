"""
retriever.py — Milestone 4: embed chunks and test retrieval.

Loads the chunks produced by ingest.py (documents/chunks.json), embeds each
chunk's `text` with all-MiniLM-L6-v2 (local, no API key, no rate limits), stores
them in a persistent ChromaDB collection with source metadata, and provides a
retrieve() function plus a CLI that runs the evaluation-plan queries and prints
the top-k chunks with their cosine distance scores.

The collection uses cosine distance, so scores run ~0 (identical) to ~1
(unrelated); per the milestone, < ~0.6 is a solid match and > ~0.6-0.7 is weak.

Usage:
    python retriever.py                       # build index if needed, run test queries
    python retriever.py --rebuild             # re-embed everything from scratch
    python retriever.py "your question here"  # ad-hoc query
"""

import json
import os
import sys

import chromadb
from sentence_transformers import SentenceTransformer

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(HERE, "documents")
CHUNKS_PATH = os.path.join(DOCS_DIR, "chunks.json")
CHROMA_DIR = os.path.join(DOCS_DIR, "chroma")      # persisted vector store on disk

MODEL_NAME = "all-MiniLM-L6-v2"
COLLECTION = "berkeley_cs_reviews"
TOP_K = 5                 # planning.md > Retrieval Approach
WEAK_MATCH = 0.6          # cosine distance above this = flag as a weak match

# Evaluation queries (from planning.md > Evaluation Plan), phrased as a user would ask.
EVAL_QUERIES = [
    "Which upper-division CS courses are must-takes?",
    "Why do students quit or leave the CS major?",
    "What qualities make a CS professor great?",
    "Which professors are approachable and good to talk to?",
    "What happens if you take a hard professor for an intro CS class?",
]

# The model is heavy to load, so load it once and reuse it.
_model = None


def get_model():
    global _model
    if _model is None:
        print(f"Loading embedding model: {MODEL_NAME} ...")
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def load_chunks():
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_client():
    return chromadb.PersistentClient(path=CHROMA_DIR)


def build_index(rebuild=False):
    """Embed all chunks and (re)create the ChromaDB collection. Skips re-embedding
    if the collection already holds exactly the current number of chunks."""
    client = get_client()
    existing = [getattr(c, "name", c) for c in client.list_collections()]
    chunks = load_chunks()

    if COLLECTION in existing:
        col = client.get_collection(COLLECTION)
        if not rebuild and col.count() == len(chunks):
            print(f"Index ready: {col.count()} chunks already embedded "
                  f"(use --rebuild to re-embed).")
            return col
        reason = "forced" if rebuild else f"stale ({col.count()} vs {len(chunks)} chunks)"
        print(f"Rebuilding index ({reason}) ...")
        client.delete_collection(COLLECTION)

    # cosine space so distances match the milestone's 0..1 interpretation
    col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})

    model = get_model()
    texts = [c["text"] for c in chunks]   # `text` carries the [Thread: title] prefix
    print(f"Embedding {len(texts)} chunks ...")
    embeddings = model.encode(texts, normalize_embeddings=True,
                              show_progress_bar=True, batch_size=64)

    # Store source metadata with every chunk for later attribution (Milestone 5).
    # `context` (thread title + post) rides along but is NOT embedded.
    col.add(
        ids=[str(c["chunk_id"]) for c in chunks],
        embeddings=[e.tolist() for e in embeddings],
        documents=texts,
        metadatas=[{
            "source_id": c["source_id"],
            "source_title": c["source_title"],
            "source_url": c["source_url"],
            "type": c["type"],
            "author": c["author"],
            "part": c["part"],
            "char_len": c["char_len"],
            "context": c["context"],
        } for c in chunks],
    )
    print(f"Stored {col.count()} chunks in ChromaDB at "
          f"{os.path.relpath(CHROMA_DIR, HERE)}")
    return col


def retrieve(query, k=TOP_K, col=None):
    """Return the top-k chunks for a query as a list of
    {text, metadata, distance} dicts, nearest first."""
    col = col or get_client().get_collection(COLLECTION)
    q_emb = get_model().encode([query], normalize_embeddings=True)[0].tolist()
    res = col.query(query_embeddings=[q_emb], n_results=k,
                    include=["documents", "metadatas", "distances"])
    hits = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0],
                               res["distances"][0]):
        hits.append({"text": doc, "metadata": meta, "distance": dist})
    return hits


def print_hits(query, hits):
    print("\n" + "=" * 74)
    print(f"QUERY: {query}")
    print("=" * 74)
    for i, h in enumerate(hits, 1):
        m = h["metadata"]
        flag = "" if h["distance"] <= WEAK_MATCH else "   <-- weak match (>0.6)"
        print(f"\n[{i}] distance {h['distance']:.3f}{flag}")
        print(f"    source {m['source_id']} \"{m['source_title']}\" | "
              f"{m['type']} | u/{m['author']}")
        # strip the [Thread: ...] prefix line for readability when printing
        body = h["text"].split("\n", 1)[1] if "\n" in h["text"] else h["text"]
        print(f"    {body[:300]}{'...' if len(body) > 300 else ''}")


def main():
    rebuild = "--rebuild" in sys.argv
    query_args = [a for a in sys.argv[1:] if not a.startswith("--")]

    build_index(rebuild=rebuild)
    col = get_client().get_collection(COLLECTION)

    if query_args:                       # ad-hoc single query
        q = " ".join(query_args)
        print_hits(q, retrieve(q, col=col))
        return

    for q in EVAL_QUERIES:               # default: run the evaluation-plan queries
        print_hits(q, retrieve(q, col=col))


if __name__ == "__main__":
    main()
