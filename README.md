# The Unofficial Guide — Project 1

> **How to use this template:**
> Complete each section *after* you've built and tested the corresponding part of your system.
> Do not write placeholder text — if a section isn't done yet, leave it blank and come back.
> Every section below is required for submission. One-liners will not receive full credit.

---

## Domain

Student-generated course and professor reviews for UC Berkeley Computer Science classes, drawn from r/berkeley Reddit threads. Official course catalogs and department pages describe *what* is taught, but not *how* a given instructor grades, whether they give useful feedback, or which professors make a class worth its workload. This knowledge lives in informal student discussions and is scattered across many threads — hard to find through official channels and impossible to query directly. This system surfaces that lived student experience in response to natural-language questions.

---

## Document Sources

All ten sources are r/berkeley Reddit threads, saved locally as `.json` exports in `documents/raw/` (filename shown). Together they cover different angles: head-to-head professor comparisons, "best/worst" lists, must-take course advice, why students leave the major, and approachable research faculty.

| # | Source (thread title) | Type | URL or file path |
|---|--------|------|-----------------|
| 1 | CS profs on reddit | Reddit thread (r/berkeley) | https://www.reddit.com/r/berkeley/comments/fa120e/cs_profs_on_reddit/ → `documents/raw/01_fa120e.json` |
| 2 | Best/worst STEM professors? | Reddit thread (r/berkeley) | https://www.reddit.com/r/berkeley/comments/1k5ncfq/bestworst_stem_professors/ → `documents/raw/02_1k5ncfq.json` |
| 3 | Why I Quit CS | Reddit thread (r/berkeley) | https://www.reddit.com/r/berkeley/comments/rrn14k/why_i_quit_cs/ → `documents/raw/03_rrn14k.json` |
| 4 | The difference between this professor and that one CS 189 professor | Reddit thread (r/berkeley) | https://www.reddit.com/r/berkeley/comments/1ct2pq6/the_difference_between_this_professor_and_that/ → `documents/raw/04_1ct2pq6.json` |
| 5 | CS Major Advice | Reddit thread (r/berkeley) | https://www.reddit.com/r/berkeley/comments/1s6iarl/cs_major_advice/ → `documents/raw/05_1s6iarl.json` |
| 6 | my opinion on cs classes | Reddit thread (r/berkeley) | https://www.reddit.com/r/berkeley/comments/1btbpq5/my_opinion_on_cs_classes/ → `documents/raw/06_1btbpq5.json` |
| 7 | Best Professors | Reddit thread (r/berkeley) | https://www.reddit.com/r/berkeley/comments/tzjiou/best_professors/ → `documents/raw/07_tzjiou.json` |
| 8 | Must-take CS upper divs? | Reddit thread (r/berkeley) | https://www.reddit.com/r/berkeley/comments/122ea3o/musttake_cs_upper_divs/ → `documents/raw/08_122ea3o.json` |
| 9 | Cool Professors to Talk To | Reddit thread (r/berkeley) | https://www.reddit.com/r/berkeley/comments/1ieu3ha/cool_professors_to_talk_to/ → `documents/raw/09_1ieu3ha.json` |
| 10 | Who are the best Engineering Professors to take? | Reddit thread (r/berkeley) | https://www.reddit.com/r/berkeley/comments/c0yo6t/who_are_the_best_engineering_professors_to_take/ → `documents/raw/10_c0yo6t.json` |

---

## Chunking Strategy

My approach is **comment-based chunking with an embedding-aware size cap and overlap**. Each Reddit comment (and reply) becomes one chunk so that a complete student opinion stays together as a single retrievable unit. Posts and any comment longer than the cap are split on paragraph → sentence boundaries (never mid-word).

**Chunk size:** 800 characters (effective max ~921 with overlap). I tuned this to the embedding model: `all-MiniLM-L6-v2` only encodes its first 256 tokens (~1,000 characters), so anything longer is silently truncated and unsearchable. My original 2,000-char cap left 13 long posts/reviews (8% of the corpus) with their tails dropped at embedding time; the 800-char cap keeps every chunk fully inside the model's window.

**Overlap:** ~120 characters (≈1 sentence), carried from the end of one piece into the start of the next — but **only between pieces of the same split item**, never between separate comments. This preserves continuity when a long review is split mid-argument, without bloating short standalone comments. (This is a deliberate change from my original "no overlap" plan.)

**Preprocessing before chunking:** Loaded each thread from a saved Reddit `.json` export, then unescaped HTML entities (`&#39;` → `'`), normalized whitespace, and dropped `[deleted]`/`[removed]` text, bot comments (AutoModerator, etc.), stickied moderator comments, and anything under 30 characters (one-word noise like "lol"/"+1"). Each comment chunk also stores the thread title + original post in a separate `context` field that is **not embedded** — it is attached for the generation step to interpret terse chunks.

**Why these choices fit your documents:** Reddit professor reviews are discrete student opinions, so comment boundaries are the natural chunk boundaries — they keep results interpretable (one opinion per chunk) and make source attribution clean (one chunk → one comment). Most comments are short, so they pass through whole; only the handful of long posts/reviews get split.

**Final chunk count:** 185 chunks across 10 documents (chunk lengths range 30–921 characters), up from 160 under the original 2,000-character cap.

---

## Embedding Model

<!-- Name the embedding model you used and explain your choice.
     Then answer: if you were deploying this system for real users and cost wasn't a constraint,
     what tradeoffs would you weigh in choosing a different model?
     Consider: context length limits, multilingual support, accuracy on domain-specific text,
     latency, and local vs. API-hosted. -->

**Model used:** `all-MiniLM-L6-v2` (sentence-transformers), run locally — no API key, no rate limits. It produces 384-dimensional embeddings. I embed each chunk's `text` field and store the vectors in a persistent ChromaDB collection using cosine distance, with the source metadata attached to every chunk. I chose it as the recommended lightweight default: it is fast on CPU, free, and accurate enough on short student-opinion text. Its 256-token (~1,000-character) context window also directly shaped my chunking — it is why I capped chunks at 800 characters, so no chunk is truncated at embedding time.

**Production tradeoff reflection:** If I were deploying this for real users and cost weren't a constraint, I would weigh a larger or domain-tuned embedding model, or a hosted embedding API. The tradeoffs: (1) **Context length** — a model with a larger window would let me keep long reviews whole instead of splitting them, preserving more semantic context per vector. (2) **Domain accuracy** — MiniLM can treat professor nicknames and course codes (e.g. "61B", "Hilfinger") as low-signal tokens; a stronger or fine-tuned model would capture that nuance better. (3) **Latency & local vs. API** — local embedding is private (these are student opinions) and has no rate limits, whereas a hosted API adds latency and a privacy consideration but may improve quality. I saw the model's limits concretely in testing: it retrieved well on topical queries, but ranked a generic, referent-less reply chunk highly because a small model leans on surface lexical overlap — a more capable model would likely down-weight it (see Failure Case Analysis).

---

## Grounded Generation

<!-- Explain how your system enforces grounding — how does it prevent the LLM from answering
     beyond the retrieved documents?
     Describe both your system prompt (what instruction you gave the model) and any structural
     choices (e.g., how you formatted the context, whether you filtered low-relevance chunks).
     Do not just say "I told it to use the documents" — show the actual instruction or explain
     the mechanism. -->

**System prompt grounding instruction:**

**How source attribution is surfaced in the response:**

---

## Evaluation Report

<!-- Run your 5 test questions from planning.md through your system and record the results.
     Be honest — a partially accurate or inaccurate result that you explain well is more
     valuable than a suspiciously perfect result. -->

| # | Question | Expected answer | System response (summarized) | Retrieval quality | Response accuracy |
|---|----------|-----------------|------------------------------|-------------------|-------------------|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |
| 5 | | | | | |

**Retrieval quality:** Relevant / Partially relevant / Off-target  
**Response accuracy:** Accurate / Partially accurate / Inaccurate

---

## Failure Case Analysis

<!-- Identify at least one question where retrieval or generation did not work as expected.
     Write a specific explanation of *why* it failed, tied to a part of the pipeline.

     "The answer was wrong" is not an explanation.

     "The relevant information was split across a chunk boundary, so retrieval returned
     only half the context — the model didn't have enough to answer correctly" is an explanation.

     "The embedding model treated the professor's nickname as out-of-vocabulary and returned
     results from an unrelated review" is an explanation. -->

**Question that failed:** "What happens if you take a hard professor for an intro CS class?" (the same chunk also wrongly topped "What qualities make a CS professor great?").

**What the system returned:** The #1 retrieved chunk (cosine distance ~0.377) was a reply from the "Best Professors" thread: *"I second this. I recommend that everyone, not just cs majors take at least one of his classes."* This says nothing about hard professors or intro classes — it is a generic endorsement. The same chunk surfaced as a top hit across three different queries.

**Root cause (tied to a specific pipeline stage):** The ingestion/chunking stage. My chunking is comment-based, so each comment becomes a chunk independently of its parent. This reply was severed from the comment it was agreeing with, so "his classes" lost its referent (which professor?). What remains is a generic recommendation phrase whose embedding sits close to many professor/class queries. Retrieval then did its job correctly — it returned a genuinely nearby vector — but the chunk had no standalone meaning, and the small embedding model matched it on surface lexical overlap ("cs", "classes", "recommend") rather than topical relevance. The defect is upstream of retrieval, not in it.

**What you would change to fix it:** Preserve the referent during ingestion. The cleanest fix is to attach the parent comment (or at least the professor name it mentions) to a reply chunk's `context`, the same way I already attach the thread's original post — so a reply like "I second this" carries what it is seconding. A cheaper alternative is to drop or merge referent-less short replies that begin with "I second", "agreed", "this", etc., though that risks discarding some real signal.

---

## Spec Reflection

<!-- Reflect on how planning.md shaped your implementation.
     Answer both questions with at least 2–3 sentences each. -->

**One way the spec helped you during implementation:**

**One way your implementation diverged from the spec, and why:**

---

## AI Usage

<!-- Describe at least 2 specific instances where you used an AI tool during this project.
     For each: what did you give the AI as input, what did it produce, and what did you
     change, override, or direct differently?

     "I used Claude to help me code" is not sufficient.
     "I gave Claude my Chunking Strategy section from planning.md and asked it to implement
     chunk_text(). It returned a function using a fixed character split. I overrode the
     chunk size from 500 to 200 because my documents are short reviews, not long guides." -->

**Instance 1**

- *What I gave the AI:*
- *What it produced:*
- *What I changed or overrode:*

**Instance 2**

- *What I gave the AI:*
- *What it produced:*
- *What I changed or overrode:*
