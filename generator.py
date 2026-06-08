"""
generator.py — Milestone 5: grounded answer generation.

Ties retrieval (retriever.py) to an LLM (Groq, llama-3.3-70b-versatile) to answer
questions about Berkeley CS courses/professors using ONLY the retrieved student
reviews. Grounding is enforced two ways:
  1. A strict system prompt: answer only from the provided CONTEXT; if the answer
     isn't there, reply exactly "I don't have enough information on that."
  2. Source attribution is guaranteed programmatically — the returned `sources`
     list is built from the retrieved chunks' metadata, not invented by the model.

Requires GROQ_API_KEY in .env (see .env.example). The ChromaDB index must already
exist (run `python retriever.py` first).

Usage:
    python generator.py                       # run the test queries (+ an out-of-domain one)
    python generator.py "your question here"  # ask a single question
"""

import os
import sys

from dotenv import load_dotenv
from groq import Groq

from retriever import retrieve, TOP_K

load_dotenv()

MODEL = "llama-3.3-70b-versatile"
# Chunks above this cosine distance are too weak to trust as evidence. If EVERY
# retrieved chunk is above it, we decline rather than feed the model loosely
# related text — this is what makes out-of-domain questions get declined.
RELEVANCE_CUTOFF = 0.7
NO_INFO = "I don't have enough information on that."

SYSTEM_PROMPT = (
    "You are an assistant that answers questions about UC Berkeley computer science "
    "courses and professors using ONLY the student-review excerpts provided in the "
    "CONTEXT. Follow these rules strictly:\n"
    "1. Use only information found in the CONTEXT. Do not use any outside or prior "
    "knowledge, and do not guess or extrapolate.\n"
    f'2. If the CONTEXT does not contain enough information to answer, reply with '
    f'exactly this sentence and nothing else: "{NO_INFO}"\n'
    "3. Cite the sources you used by their bracket number inline, e.g. [1] or [2][3], "
    "right after the claims they support.\n"
    "4. Keep the answer concise and specific, and quote professor and course names "
    "exactly as they appear in the CONTEXT."
)

_client = None


def client():
    global _client
    if _client is None:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError(
                "GROQ_API_KEY not set. Copy .env.example to .env and add your key."
            )
        _client = Groq(api_key=key)
    return _client


def build_context(hits):
    """Format retrieved chunks into a numbered CONTEXT block for the prompt.
    Includes each chunk's `context` metadata (thread title + original post) so the
    model can interpret terse comments — the option-3 enrichment from ingestion."""
    blocks = []
    for i, h in enumerate(hits, 1):
        m = h["metadata"]
        body = h["text"].split("\n", 1)[1] if "\n" in h["text"] else h["text"]
        blocks.append(
            f'[{i}] Source: "{m["source_title"]}" ({m["source_url"]})\n'
            f'{m["context"]}\n'
            f'Student comment (u/{m["author"]}): {body}'
        )
    return "\n\n".join(blocks)


def sources_from(hits):
    """Unique source list (title + url) in retrieval order — guaranteed attribution."""
    seen, out = set(), []
    for h in hits:
        m = h["metadata"]
        key = (m["source_title"], m["source_url"])
        if key not in seen:
            seen.add(key)
            out.append(f'{m["source_title"]} — {m["source_url"]}')
    return out


def ask(question, k=TOP_K, source_id=None):
    """End-to-end: retrieve -> ground -> generate. Returns {answer, sources, hits}.

    `source_id` (optional) restricts retrieval to a single source thread via a
    ChromaDB metadata filter (stretch: metadata filtering)."""
    where = {"source_id": source_id} if source_id is not None else None
    hits = retrieve(question, k=k, where=where)
    relevant = [h for h in hits if h["distance"] <= RELEVANCE_CUTOFF]
    if not relevant:
        # Nothing close enough to trust -> decline without inventing sources.
        return {"answer": NO_INFO, "sources": [], "hits": hits}

    user_msg = (
        f"CONTEXT:\n{build_context(relevant)}\n\n"
        f"QUESTION: {question}\n\n"
        "Answer using only the CONTEXT above, following the rules."
    )
    resp = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        max_tokens=500,
    )
    answer = resp.choices[0].message.content.strip()
    # If the model declined, attach no sources (nothing was actually used).
    sources = [] if answer == NO_INFO else sources_from(relevant)
    return {"answer": answer, "sources": sources, "hits": relevant}


TEST_QUERIES = [
    "Which upper-division CS courses are must-takes?",
    "Why do students quit or leave the CS major?",
    "Which professors are approachable and good to talk to?",
    "What is the best dorm dining hall on campus?",  # out-of-domain: should decline
]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    queries = [" ".join(args)] if args else TEST_QUERIES
    for q in queries:
        r = ask(q)
        print("\n" + "=" * 74)
        print(f"Q: {q}")
        print("-" * 74)
        print(r["answer"])
        if r["sources"]:
            print("\nSources:")
            for s in r["sources"]:
                print(f"  - {s}")
        else:
            print("\n(no sources - declined or no relevant context)")


if __name__ == "__main__":
    main()
