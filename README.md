# The Unofficial Guide — Project 1

A retrieval-augmented question-answering system over student reviews of UC Berkeley CS courses and professors. Ask a natural-language question and get an answer grounded **only** in r/berkeley student discussions, with the source threads cited.

**Pipeline:** `ingest.py` (load + clean + chunk) → `retriever.py` (embed + ChromaDB) → `generator.py` (grounded Groq answer) → `app.py` (Gradio UI).
**Run:** `python ingest.py` → `python retriever.py` → `python app.py` (needs `GROQ_API_KEY` in `.env`).

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

**Model used:** `all-MiniLM-L6-v2` (sentence-transformers), run locally — no API key, no rate limits. It produces 384-dimensional embeddings. I embed each chunk's `text` field and store the vectors in a persistent ChromaDB collection using cosine distance, with the source metadata attached to every chunk. I chose it as the recommended lightweight default: it is fast on CPU, free, and accurate enough on short student-opinion text. Its 256-token (~1,000-character) context window also directly shaped my chunking — it is why I capped chunks at 800 characters, so no chunk is truncated at embedding time.

**Production tradeoff reflection:** If I were deploying this for real users and cost weren't a constraint, I would weigh a larger or domain-tuned embedding model, or a hosted embedding API. The tradeoffs: (1) **Context length** — a model with a larger window would let me keep long reviews whole instead of splitting them, preserving more semantic context per vector. (2) **Domain accuracy** — MiniLM can treat professor nicknames and course codes (e.g. "61B", "Hilfinger") as low-signal tokens; a stronger or fine-tuned model would capture that nuance better. (3) **Latency & local vs. API** — local embedding is private (these are student opinions) and has no rate limits, whereas a hosted API adds latency and a privacy consideration but may improve quality. I saw the model's limits concretely in testing: it retrieved well on topical queries, but ranked a generic, referent-less reply chunk highly because a small model leans on surface lexical overlap — a more capable model would likely down-weight it (see Failure Case Analysis).

---

## Grounded Generation

**System prompt grounding instruction:** The system prompt gives the model four hard rules (see `generator.py` → `SYSTEM_PROMPT`): (1) *"Use only information found in the CONTEXT. Do not use any outside or prior knowledge, and do not guess or extrapolate."* (2) *"If the CONTEXT does not contain enough information to answer, reply with exactly this sentence and nothing else: 'I don't have enough information on that.'"* (3) cite sources inline by bracket number, e.g. `[1]` or `[2][3]`. (4) quote professor and course names exactly as they appear. The model runs at `temperature=0.1` to minimize improvisation. The instruction is an enforced *requirement* (the model must reply with the exact decline sentence), not a soft suggestion.

Beyond the prompt, grounding is enforced **structurally**: before generation, retrieved chunks with a cosine distance above `RELEVANCE_CUTOFF = 0.7` are dropped, and if *no* chunk clears that bar the system declines programmatically without ever calling the LLM. This is why an out-of-domain question ("What is the best dorm dining hall on campus?") returns the decline sentence — the retrieved chunks are too far away to count as evidence.

**How source attribution is surfaced in the response:** Attribution is **guaranteed programmatically**, not left to the model. After generation, `ask()` builds the `sources` list directly from the retrieved chunks' metadata (`source_title` + `source_url`), deduplicated in retrieval order — so the cited sources always correspond to real documents that were actually in the context, even if the model forgot to add `[n]` markers. The interface (`app.py`) shows these under a "Retrieved from" panel alongside the answer. When the system declines (no relevant context), the source list is empty. The model *also* cites bracket numbers inline as a readability aid, but the programmatic list is the source of truth.

---

## Evaluation Report

| # | Question | Expected answer | System response (summarized) | Retrieval quality | Response accuracy |
|---|----------|-----------------|------------------------------|-------------------|-------------------|
| 1 | Which upper-division CS courses are must-takes? | Specific course numbers (e.g. CS 170/189/164) | Named CS 162, CS 70, CS 189, EECS 127, Data C102, CS 188; noted the thread itself disputes the word "must-take". Cited sources. | Relevant (src 8 "Must-take CS upper divs?") | Partially accurate — real courses pulled from context, but scattered; got 189/162, not the 170/164 emphasis expected |
| 2 | Why do students quit/leave the CS major? | Burnout, harsh grading/curve, competitiveness, lost passion | Cited the "bona fide curve" in 70/170, a curve that's "never a function of effort," and one student calling CS "an average major… with lukewarm salaries." | Relevant (src 3 "Why I Quit CS", all hits) | Accurate |
| 3 | What qualities describe excellent CS professors? | Clear/engaging lectures, helpful, fair grading | "Excellent lecturer," "nicest/most helpful," "engaging"; named DeNero, Yun Song, Jaijeet Roychowdhury. | Relevant (src 7 "Best Professors") | Partially accurate — captures lecturing/helpfulness, but leans toward naming professors over abstract qualities |
| 4 | Name a professor described as approachable. | A specific named professor | **Pamela Fox** — "one of the nicest/most approachable people." Cited. | Relevant (src 9/7) | Accurate |
| 5 | Consequence of taking a difficult intro prof? | Harder exams, stress, lower grades, more outside help | "A bad mental breakdown and an embarrassingly low score," softened by a generous failing policy. | Partially relevant | Partially accurate — on-theme but thin; the corpus covers this only loosely |
| — | *Out-of-domain control:* "Who will win the World Cup 2026?" | Should decline | "I don't have enough information on that." (no sources) | n/a (gated out) | Correct refusal — grounding held |

**Retrieval quality:** Relevant (4 of 5 strong, 1 partial; the right source thread topped every in-domain query)  
**Response accuracy:** Accurate to Partially accurate — every answer was grounded in retrieved text with source citations, no hallucinations, and the out-of-domain question was correctly declined.

---

## Failure Case Analysis

**Question that failed:** "What happens if you take a hard professor for an intro CS class?" (the same chunk also wrongly topped "What qualities make a CS professor great?").

**What the system returned:** The #1 retrieved chunk (cosine distance ~0.377) was a reply from the "Best Professors" thread: *"I second this. I recommend that everyone, not just cs majors take at least one of his classes."* This says nothing about hard professors or intro classes — it is a generic endorsement. The same chunk surfaced as a top hit across three different queries.

**Root cause (tied to a specific pipeline stage):** The ingestion/chunking stage. My chunking is comment-based, so each comment becomes a chunk independently of its parent. This reply was severed from the comment it was agreeing with, so "his classes" lost its referent (which professor?). What remains is a generic recommendation phrase whose embedding sits close to many professor/class queries. Retrieval then did its job correctly — it returned a genuinely nearby vector — but the chunk had no standalone meaning, and the small embedding model matched it on surface lexical overlap ("cs", "classes", "recommend") rather than topical relevance. The defect is upstream of retrieval, not in it.

**What you would change to fix it:** Preserve the referent during ingestion. The cleanest fix is to attach the parent comment (or at least the professor name it mentions) to a reply chunk's `context`, the same way I already attach the thread's original post — so a reply like "I second this" carries what it is seconding. A cheaper alternative is to drop or merge referent-less short replies that begin with "I second", "agreed", "this", etc., though that risks discarding some real signal.

---

## Spec Reflection

**One way the spec helped you during implementation:** Writing the Documents list, Chunking Strategy, and Retrieval Approach *before* any code meant I could direct the implementation precisely instead of improvising. For example, because the spec already said "each Reddit comment = one chunk," the ingestion code had a clear target, and I could verify the output against the spec (comment boundaries preserved, sizes uneven) rather than guessing whether the chunking was "right." The spec turned vague intentions into concrete acceptance criteria I could check at each stage.

**One way your implementation diverged from the spec, and why:** I diverged on the chunk size — the spec said split only above 2,000 characters with no overlap, but I lowered the cap to 800 characters and added ~120-character overlap. The reason was a constraint the spec hadn't accounted for: the embedding model (`all-MiniLM-L6-v2`) only encodes its first 256 tokens (~1,000 characters), so my original 2,000-char chunks were having their tails silently truncated and made unsearchable (13 chunks, ~8% of the corpus). Aligning the cap to the model's window fixed that, and the overlap preserves continuity when a long review is split. (I also diverged on two implementation details for the same "fit reality" reason: ingestion loads saved Reddit `.json` files instead of live `requests`/BeautifulSoup scraping, because Reddit 403-blocks unauthenticated requests, and the vector store is ChromaDB instead of FAISS for native metadata filtering and persistence. I updated `planning.md` to reflect all three.)

---

## AI Usage

**Instance 1 — Ingestion and chunking**

- *What I gave the AI:* My `planning.md` Documents list (10 Reddit threads) and Chunking Strategy section (comment-based, with a size cap), plus the constraint that live scraping was failing.
- *What it produced:* `ingest.py` — a pipeline that loads saved Reddit `.json`, cleans it (HTML unescape, drop deleted/bot/short comments), and chunks it comment-by-comment with paragraph/sentence splitting for long items.
- *What I changed or overrode:* I overrode the chunk cap from 2,000 to 800 characters after recognizing the embedding model truncates at 256 tokens, and added ~120-char overlap (the spec said none). I also directed a design decision the AI hadn't proposed: a separate non-embedded `context` field carrying the thread's question, so terse comments stay interpretable at generation time without polluting the embeddings.

**Instance 2 — Retrieval and grounded generation**

- *What I gave the AI:* My Retrieval Approach (all-MiniLM-L6-v2, top-5) and the grounding requirement (answer from retrieved context only, with source attribution).
- *What it produced:* `retriever.py` (embed chunks → ChromaDB → `retrieve()`) and `generator.py` (a grounding prompt that calls Groq's `llama-3.3-70b-versatile`), plus a Gradio interface.
- *What I changed or overrode:* I directed the ChromaDB collection to use cosine distance so scores matched the milestone's 0–1 scale, and added a structural guardrail the prompt alone didn't give: a 0.7 cosine-distance gate that declines out-of-domain questions *before* calling the LLM. I also made source attribution programmatic (built from retrieved metadata) rather than trusting the model to cite correctly.
