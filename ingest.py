"""
ingest.py — Document pipeline for "The Unofficial Guide" (Milestone 3)

Domain: student-generated Berkeley CS professor/course reviews from Reddit.

This script does two jobs (per the milestone):
  1. LOAD   — read each Reddit thread from a locally saved file in documents/raw/
              (a .json export of the thread, or a plain .txt copy).
  2. CHUNK  — clean the text and split it using the comment-based strategy
              from planning.md (each comment = one chunk; post body and very
              long comments are split on paragraph boundaries at MAX_CHARS).

Cleaning is light because Reddit JSON gives us the substantive text directly
(no nav menus, ads, cookie banners, or HTML to strip). We still unescape any
HTML entities, drop deleted/removed/bot comments, and normalize whitespace.

Why no live web fetch? Reddit blocks unauthenticated requests (HTTP 403); the
only working programmatic route is the OAuth API (a registered app + client
id/secret), which adds credentials and a dependency that are outside the scope
of this project. So we load from files you save once: open each thread URL with
".json" appended in your browser, save it into documents/raw/ using the printed
filename (or paste the visible text into a .txt), then run this script.
"""

import html
import json
import os
import re
import statistics
import sys

# --- Configuration ------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(HERE, "documents")
RAW_DIR = os.path.join(DOCS_DIR, "raw")
CHUNKS_PATH = os.path.join(DOCS_DIR, "chunks.json")

# Verbose tracer. Set to 1 to print every step (which load step is tried, whether
# it failed and what is tried next, plus cleaning/chunking/report details). Set to
# 0 for the normal quiet run. You can also flip it from the command line:
#     python ingest.py --debug      (forces DEBUG on)
DEBUG = 0

# Comment-based chunking with a size cap (see planning.md > Chunking Strategy).
# MAX_CHARS is tuned to the embedding model's context window: all-MiniLM-L6-v2 only
# encodes its first 256 tokens (~1000 chars), so anything longer is silently truncated
# and becomes unsearchable. We split posts/comments above this so every chunk embeds in
# full. Pieces of one split item also carry ~OVERLAP_CHARS of trailing context (see
# split_long), so a chunk's effective max is ~MAX_CHARS + OVERLAP_CHARS, still < ~1000.
MAX_CHARS = 800           # split post body / long comments above this length
OVERLAP_CHARS = 120       # ~1 sentence carried into the next piece of the SAME item
MIN_USEFUL_CHARS = 30     # comments shorter than this are usually noise ("lol", "+1")

# Context enrichment (option 3): each comment chunk carries the thread's post text
# (the original question/topic) in a separate `context` field. This is NOT embedded
# -- it is meant to be shown to the LLM at generation time so a terse reaction like
# "Sharma being the goat" can be interpreted against the question it answered. We cap
# it so the generation prompt stays bounded when several chunks share a thread.
CONTEXT_MAX_CHARS = 600

# Bot / automated authors whose comments are not student opinions.
SKIP_AUTHORS = {"AutoModerator", "[deleted]", "sneakpeekbot", "RemindMeBot"}

# 10 sources from planning.md. `id` drives the cache filename and chunk ids.
SOURCES = [
    {"id": 1,  "title": "CS profs on reddit",
     "url": "https://www.reddit.com/r/berkeley/comments/fa120e/cs_profs_on_reddit/"},
    {"id": 2,  "title": "Best/worst STEM professors?",
     "url": "https://www.reddit.com/r/berkeley/comments/1k5ncfq/bestworst_stem_professors/"},
    {"id": 3,  "title": "Why I Quit CS",
     "url": "https://www.reddit.com/r/berkeley/comments/rrn14k/why_i_quit_cs/"},
    {"id": 4,  "title": "The difference between this professor and that one CS 189 professor",
     "url": "https://www.reddit.com/r/berkeley/comments/1ct2pq6/the_difference_between_this_professor_and_that/"},
    {"id": 5,  "title": "CS Major Advice",
     "url": "https://www.reddit.com/r/berkeley/comments/1s6iarl/cs_major_advice/"},
    {"id": 6,  "title": "my opinion on cs classes",
     "url": "https://www.reddit.com/r/berkeley/comments/1btbpq5/my_opinion_on_cs_classes/"},
    {"id": 7,  "title": "Best Professors",
     "url": "https://www.reddit.com/r/berkeley/comments/tzjiou/best_professors/"},
    {"id": 8,  "title": "Must-take CS upper divs?",
     "url": "https://www.reddit.com/r/berkeley/comments/122ea3o/musttake_cs_upper_divs/"},
    {"id": 9,  "title": "Cool Professors to Talk To",
     "url": "https://www.reddit.com/r/berkeley/comments/1ieu3ha/cool_professors_to_talk_to/"},
    {"id": 10, "title": "Who are the best Engineering Professors to take?",
     "url": "https://www.reddit.com/r/berkeley/comments/c0yo6t/who_are_the_best_engineering_professors_to_take/"},
]


def dbg(msg):
    """Print a tracer line, but only when DEBUG is on."""
    if DEBUG:
        print(f"    [trace] {msg}")


# --- Loading ------------------------------------------------------------------

def reddit_id(url):
    """Extract the short thread id (e.g. 'fa120e') from a Reddit comments URL."""
    m = re.search(r"/comments/([a-z0-9]+)/", url)
    return m.group(1) if m else "unknown"


def raw_path_for(source):
    return os.path.join(RAW_DIR, f"{source['id']:02d}_{reddit_id(source['url'])}.json")


def txt_path_for(source):
    return os.path.join(RAW_DIR, f"{source['id']:02d}_{reddit_id(source['url'])}.txt")


def load_source(source):
    """Locate this source's input and return (kind, payload):
      ("json", parsed_obj)  - a saved Reddit .json export of the thread (preferred)
      ("text", raw_string)  - a plain .txt copy of the thread (fallback)
      (None,   None)        - no local file found for this source

    Preference order: saved .json  ->  .txt copy.

    There is intentionally NO live web fetch here. Reddit blocks unauthenticated
    requests (HTTP 403); the only working programmatic route is the OAuth API
    (a registered app + client id/secret), which adds credentials and a
    dependency that are outside the scope of this project. So you save each
    thread to documents/raw/ once (see the message printed when a file is
    missing) and the pipeline reads from disk.
    """
    json_path = raw_path_for(source)
    txt_path = txt_path_for(source)

    # 1. Saved / browser-exported JSON (keeps comment structure).
    dbg(f"step 1/2: look for JSON -> {os.path.basename(json_path)}")
    if os.path.exists(json_path):
        dbg("step 1/2: found JSON, parsing")
        with open(json_path, "r", encoding="utf-8") as f:
            text = f.read()
        try:
            print(f"  [{source['id']:>2}] json:  {os.path.basename(json_path)}")
            return "json", json.loads(text)
        except json.JSONDecodeError:
            print(f"    ! {os.path.basename(json_path)} is not valid JSON "
                  f"(did the browser save the HTML page instead of the .json view?)")
            return None, None
    dbg("step 1/2: no JSON file -> trying step 2")

    # 2. Plain-text copy of the thread.
    dbg(f"step 2/2: look for TXT  -> {os.path.basename(txt_path)}")
    if os.path.exists(txt_path):
        dbg("step 2/2: found TXT, reading")
        with open(txt_path, "r", encoding="utf-8") as f:
            print(f"  [{source['id']:>2}] text:  {os.path.basename(txt_path)}")
            return "text", f.read()
    dbg("step 2/2: no TXT file -> source is MISSING (live fetch is out of scope)")

    # No local file. We do NOT fetch from the web: Reddit requires OAuth API auth
    # (a registered app + client id/secret), which is outside this project's scope.
    print(f"  [{source['id']:>2}] MISSING — no local file. Live fetch is out of scope "
          f"(Reddit needs OAuth API auth).")
    print(f"        To add it: save  {os.path.basename(json_path)}  (or "
          f"{os.path.basename(txt_path)})  into documents/raw/")
    print(f"        from {source['url']}")
    return None, None


def iter_comments(children):
    """Yield (author, body) for every real comment in a Reddit comment listing,
    recursing into replies. Skips 'more' stubs, bots, and deleted/removed text."""
    for child in children:
        if child.get("kind") != "t1":          # skip "more" load-more stubs
            continue
        data = child.get("data", {})
        body = (data.get("body") or "").strip()
        author = data.get("author") or "[unknown]"

        if author in SKIP_AUTHORS or data.get("stickied"):
            pass  # skip this comment's body, but still walk its replies
        elif body and body not in ("[deleted]", "[removed]"):
            yield author, body

        replies = data.get("replies")
        if isinstance(replies, dict):
            yield from iter_comments(replies.get("data", {}).get("children", []))


# --- Cleaning -----------------------------------------------------------------

_ZERO_WIDTH = re.compile(r"[​‌‍﻿ ]")
_MULTI_BLANK = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t]+\n")


def clean_text(text):
    """Normalize one piece of Reddit text into clean, readable plain text."""
    text = html.unescape(text)                 # &amp; -> &, &#39; -> ', etc.
    text = _ZERO_WIDTH.sub(" ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_WS.sub("\n", text)
    text = _MULTI_BLANK.sub("\n\n", text)      # collapse big gaps to one blank line
    return text.strip()


# --- Chunking -----------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def split_long(text, max_chars=MAX_CHARS, overlap=OVERLAP_CHARS):
    """Split text exceeding max_chars on paragraph boundaries, then sentences,
    then (last resort) a hard character cut. Consecutive pieces of the same split
    item share ~`overlap` chars of trailing context so a thought cut across a
    boundary stays coherent (see planning.md > Chunking Strategy)."""
    if len(text) <= max_chars:
        return [text]

    units, buf = [], ""
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        # Paragraph itself too big -> break it into sentences.
        pieces = [para] if len(para) <= max_chars else _resplit(para, _SENTENCE_SPLIT, max_chars)
        for piece in pieces:
            if not buf:
                buf = piece
            elif len(buf) + 2 + len(piece) <= max_chars:
                buf += "\n\n" + piece
            else:
                units.append(buf)
                buf = piece
    if buf:
        units.append(buf)
    return _add_overlap(units, overlap)


def _overlap_tail(text, max_overlap):
    """Return up to `max_overlap` trailing chars of `text` to carry into the next
    piece, starting at a sentence boundary where possible (so the carried context
    reads as a whole sentence, not a mid-word fragment)."""
    if max_overlap <= 0 or not text:
        return ""
    tail = text[-max_overlap:]
    m = re.search(r"[.!?]\s+(.+)$", tail, re.S)   # start after the first sentence end
    if m and m.group(1).strip():
        return m.group(1).strip()
    return tail.strip()


def _add_overlap(pieces, overlap):
    """Prepend each piece (after the first) with the overlap tail of the previous
    piece. The first piece is unchanged; only multi-piece splits gain overlap."""
    if len(pieces) <= 1 or overlap <= 0:
        return pieces
    out = [pieces[0]]
    for prev, cur in zip(pieces, pieces[1:]):
        tail = _overlap_tail(prev, overlap)
        out.append(f"{tail} {cur}".strip() if tail else cur)
    return out


def _resplit(text, pattern, max_chars):
    """Split text by `pattern`, regrouping into <=max_chars pieces; hard-cut anything
    still too long (e.g. a single 2000+ char sentence with no breaks)."""
    out, buf = [], ""
    for part in pattern.split(text):
        part = part.strip()
        if not part:
            continue
        if len(part) > max_chars:
            # Pathological: a single "sentence" longer than the cap. Merge any pending
            # buffer in front (so a short lead-in isn't orphaned as a fragment) and
            # hard-cut the combined text into max_chars blocks.
            combined = part if not buf else buf + " " + part
            while len(combined) > max_chars:
                out.append(combined[:max_chars])
                combined = combined[max_chars:].lstrip()
            buf = combined
            continue
        # Normal case: group whole sentences up to the cap, flushing on overflow so we
        # break on a sentence boundary rather than mid-thought.
        if not buf:
            buf = part
        elif len(buf) + 1 + len(part) <= max_chars:
            buf += " " + part
        else:
            out.append(buf)
            buf = part
    if buf:
        out.append(buf)
    return out


def make_context(title, post_body):
    """Build the generation-time context string for a thread: the title plus the
    original post (the question/topic), capped at CONTEXT_MAX_CHARS. This is stored
    on each comment chunk but is NOT embedded -- see CONTEXT_MAX_CHARS note above."""
    if len(post_body) >= MIN_USEFUL_CHARS:
        snippet = post_body[:CONTEXT_MAX_CHARS]
        if len(post_body) > CONTEXT_MAX_CHARS:
            snippet = snippet.rstrip() + " ..."
        return f"Thread title: {title}\nOriginal post: {snippet}"
    return f"Thread title: {title}"  # link/image post with no usable body


def build_chunks(source, data):
    """Turn one parsed Reddit thread into a list of chunk dicts."""
    chunks = []
    title = source["title"]

    def add(text, ctype, author, context):
        pieces = split_long(text)
        if len(pieces) > 1:
            dbg(f"chunking: {ctype} by u/{author} is {len(text)} chars "
                f"(> {MAX_CHARS}) -> split into {len(pieces)} pieces")
        for i, piece in enumerate(pieces):
            chunks.append({
                "source_id": source["id"],
                "source_title": title,
                "source_url": source["url"],
                "type": ctype,
                "author": author,
                # `text` is what gets EMBEDDED: the title prefix keeps it self-contained
                # on retrieval; we deliberately keep it lean (no full post body here).
                "text": f"[Thread: {title}]\n{piece}",
                # `context` is NOT embedded; it is the thread's question/topic, attached
                # so the LLM can interpret this chunk at generation time (option 3).
                "context": context,
                "char_len": len(piece),
                "part": i,
            })

    # data[0] = post listing, data[1] = comment listing
    post = data[0]["data"]["children"][0]["data"]
    raw_post = post.get("selftext") or ""
    body = clean_text(raw_post)
    dbg(f"cleaning: post body {len(raw_post)} -> {len(body)} chars after clean")

    # The post is the thread's question/topic -> it becomes the context for comments.
    thread_context = make_context(title, body)

    if len(body) >= MIN_USEFUL_CHARS:
        # The post chunk IS the topic, so it carries no extra context of its own.
        add(body, "post", post.get("author") or "[unknown]", "")
    else:
        dbg(f"cleaning: post body dropped (< {MIN_USEFUL_CHARS} chars; likely a link/image post)")

    comment_children = data[1]["data"]["children"]
    seen = kept = dropped = 0
    for author, raw in iter_comments(comment_children):
        seen += 1
        body = clean_text(raw)
        if len(body) >= MIN_USEFUL_CHARS:
            kept += 1
            add(body, "comment", author, thread_context)
        else:
            dropped += 1
    dbg(f"comments: {seen} real comments -> {kept} kept, {dropped} dropped (< {MIN_USEFUL_CHARS} chars)")
    dbg(f"chunking: thread {source['id']} produced {len(chunks)} chunks total")

    return chunks


def build_chunks_from_text(source, raw):
    """Fallback chunker for a plain-text copy of a thread (no comment structure).
    Chunks on blank-line paragraph boundaries, grouping up to MAX_CHARS with no
    overlap -- the same size policy as the JSON path, applied to flat text."""
    chunks = []
    title = source["title"]
    cleaned = clean_text(raw)
    dbg(f"cleaning: text file {len(raw)} -> {len(cleaned)} chars after clean")

    # Treat each blank-line-separated block as a unit; split_long regroups/caps them.
    pieces = split_long(cleaned)
    dbg(f"chunking: text grouped into {len(pieces)} pieces (cap {MAX_CHARS} chars)")
    dropped = 0
    for i, piece in enumerate(pieces):
        piece = piece.strip()
        if len(piece) < MIN_USEFUL_CHARS:
            dropped += 1
            continue
        chunks.append({
            "source_id": source["id"],
            "source_title": title,
            "source_url": source["url"],
            "type": "text",
            "author": "[from .txt]",
            "text": f"[Thread: {title}]\n{piece}",
            # A flat .txt copy has no separable post, so context is just the title.
            "context": f"Thread title: {title}",
            "char_len": len(piece),
            "part": i,
        })
    dbg(f"chunking: thread {source['id']} produced {len(chunks)} chunks "
        f"({dropped} short pieces dropped)")
    return chunks


# --- Inspection / reporting ---------------------------------------------------

def report(all_chunks, loaded, missing):
    print("\n" + "=" * 70)
    print("PIPELINE SUMMARY")
    print("=" * 70)
    print(f"Documents loaded : {loaded} / {len(SOURCES)}")
    if missing:
        print(f"Documents MISSING: {sorted(missing)}  "
              f"(save their .json into documents/raw/ and re-run)")

    if not all_chunks:
        print("\nNo chunks produced. Save each thread's .json into documents/raw/ "
              "(see the MISSING messages above) and re-run.")
        return

    lengths = [c["char_len"] for c in all_chunks]
    print(f"Total chunks     : {len(all_chunks)}")
    print(f"Chunk length     : min {min(lengths)} | "
          f"median {int(statistics.median(lengths))} | "
          f"mean {int(statistics.mean(lengths))} | max {max(lengths)} chars")

    tiny = sum(1 for n in lengths if n < 100)
    print(f"Chunks < 100 char: {tiny}  (watch for fragments with no standalone meaning)")

    print("\nChunks per source:")
    for s in SOURCES:
        n = sum(1 for c in all_chunks if c["source_id"] == s["id"])
        print(f"  [{s['id']:>2}] {n:>4}  {s['title']}")

    # 5 representative chunks: closest to the median length, one per source for variety.
    med = statistics.median(lengths)
    ordered = sorted(all_chunks, key=lambda c: abs(c["char_len"] - med))
    picked, seen = [], set()
    for c in ordered:
        if c["source_id"] not in seen:
            picked.append(c)
            seen.add(c["source_id"])
        if len(picked) == 5:
            break

    print("\n" + "=" * 70)
    print("5 REPRESENTATIVE CHUNKS  (read each: does it stand on its own?)")
    print("=" * 70)
    for c in picked:
        print(f"\n--- source {c['source_id']} | {c['type']} | u/{c['author']} | "
              f"{c['char_len']} chars ---")
        print(c["text"])


# --- Main ---------------------------------------------------------------------

def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    print(f"Loading documents...  (DEBUG={'on' if DEBUG else 'off'})")

    all_chunks = []
    loaded = 0
    missing = []
    for source in SOURCES:
        dbg(f"=== source {source['id']}: {source['title']} ===")
        kind, payload = load_source(source)
        if kind is None:
            missing.append(source["id"])
            continue
        try:
            if kind == "json":
                chunks = build_chunks(source, payload)
            else:  # "text"
                chunks = build_chunks_from_text(source, payload)
        except (KeyError, IndexError, TypeError) as e:
            print(f"    ! could not parse thread {source['id']}: {e}")
            missing.append(source["id"])
            continue
        loaded += 1
        all_chunks.append((source["id"], chunks))

    # flatten, then assign stable ids in source order
    flat = []
    for _sid, chunks in sorted(all_chunks, key=lambda x: x[0]):
        flat.extend(chunks)
    for i, c in enumerate(flat):
        c["chunk_id"] = i

    dbg(f"writing {len(flat)} chunks to {CHUNKS_PATH}")
    with open(CHUNKS_PATH, "w", encoding="utf-8") as f:
        json.dump(flat, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {len(flat)} chunks -> {os.path.relpath(CHUNKS_PATH, HERE)}")

    report(flat, loaded, missing)


if __name__ == "__main__":
    # --debug forces the tracer on without editing the DEBUG constant above.
    if "--debug" in sys.argv:
        DEBUG = 1
    main()
