# Project 1 Planning: The Unofficial Guide

> Write this document before you write any pipeline code.
> Your spec and architecture diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Update the Retrieval Approach and Chunking Strategy sections if you change your approach during implementation.
> Update this file before starting any stretch features.

---

## Domain

Student-generated course and professor review knowledge for UC Berkeley Computer Science classes. Official course catalogs and department pages describe what is taught, but not how individual instructors grade, whether they provide useful feedback, or which professors make a class worth the workload. This system will surface the lived experience students share on Reddit and informal advice threads.

---

## Documents

| # | Source | Description | URL or location |
|---|--------|-------------|-----------------|
| 1 | CS profs on reddit | Student thread comparing Berkeley CS professors | https://www.reddit.com/r/berkeley/comments/fa120e/cs_profs_on_reddit/ |
| 2 | Best/worst STEM professors? | Student list of strong and weak STEM instructors | https://www.reddit.com/r/berkeley/comments/1k5ncfq/bestworst_stem_professors/ |
| 3 | Why I Quit CS | Thread describing why students left CS | https://www.reddit.com/r/berkeley/comments/rrn14k/why_i_quit_cs/ |
| 4 | The difference between this professor and that one CS 189 professor ?? | Detailed comparisons of two CS instructors | https://www.reddit.com/r/berkeley/comments/1ct2pq6/the_difference_between_this_professor_and_that/ |
| 5 | CS Major Advice | Advice about course sequencing, professors, and major planning | https://www.reddit.com/r/berkeley/comments/1s6iarl/cs_major_advice/ |
| 6 | my opinion on cs classes | Student opinions on individual CS course experiences | https://www.reddit.com/r/berkeley/comments/1btbpq5/my_opinion_on_cs_classes/ |
| 7 | Best Professors | Students naming the most helpful professors | https://www.reddit.com/r/berkeley/comments/tzjiou/best_professors/ |
| 8 | Must-take CS upper divs? | Student recommendations for upper-division CS courses | https://www.reddit.com/r/berkeley/comments/122ea3o/musttake_cs_upper_divs/ |
| 9 | Cool Professors to Talk To | Students recommending approachable research professors | https://www.reddit.com/r/berkeley/comments/1ieu3ha/cool_professors_to_talk_to/ |
| 10 | Who are the best Engineering Professors to take? What classes did they teach? | Broader student ranking of engineering instructors | https://www.reddit.com/r/berkeley/comments/c0yo6t/who_are_the_best_engineering_professors_to_take/ |

---

## Chunking Strategy

**Chunk size:** 400-500 tokens (roughly 2,000-2,500 characters)

**Overlap:** 80-100 tokens

**Reasoning:**
Berkeley Reddit threads include a mix of short comments, longer top-level posts, and nested discussion. A moderate chunk size keeps each chunk focused on a single professor recommendation or course observation while still preserving the surrounding opinion context. Overlap prevents splitting a key recommendation across two chunks, which is especially important when comment text crosses a sentence boundary.

---

## Retrieval Approach

**Embedding model:** sentence-transformers/all-MiniLM-L6-v2

**Top-k:** 5

**Production tradeoff reflection:**
For this student-review corpus, a lightweight semantic embedding model is a good starting point because it balances speed, cost, and relevance for short opinion text. In production, I would weigh larger or domain-tuned embeddings for better nuance on professor/course names, while also considering whether a hosted API is acceptable for privacy and latency. 

---

## Evaluation Plan

| # | Question | Expected answer |
|---|----------|-----------------|
| 1 | Which upper-division CS classes do Berkeley students repeatedly recommend as must-takes? | Students repeatedly call out CS 164, CS 170, and CS 189 as top upper-division CS courses. |
| 2 | In the "Why I Quit CS" thread, what are the main reasons students say they left the major? | The thread emphasizes burnout, grading pressure, and poor course support or instructor communication. |
| 3 | What do students say makes a Berkeley CS professor especially good in the "Best Professors" thread? | Students highlight clear lectures, helpful office hours, and fair grading. |
| 4 | Which professors are recommended as approachable mentors in "Cool Professors to Talk To"? | The thread recommends professors who are known to be supportive, accessible, and engaged outside class. |
| 5 | What warning do students give about taking a hard CS professor in an intro class? | The warning is that difficult professors can increase stress, make exams feel less predictable, and require stronger use of office hours and feedback. |

---

## Anticipated Challenges

1. Reddit threads contain a lot of noise, off-topic replies, and quote text; preprocessing must remove navigation and keep only substantive student opinions.

2. Key details may be split across adjacent comments or chunk boundaries, so poor chunking could cause retrieval to miss the complete recommendation.

---

## Architecture

Document Ingestion ? Chunking ? Embedding + Vector Store ? Retrieval ? Generation

- Document Ingestion: fetch Reddit thread HTML / raw thread text, strip UI and metadata
- Chunking: split cleaned text into overlapping chunks using the chosen token size
- Embedding + Vector Store: embed each chunk with sentence-transformers and store in FAISS or similar
- Retrieval: semantic similarity search with top-5 chunks
- Generation: prompt an LLM with retrieved chunks and ask for a grounded, cited answer

---

## AI Tool Plan

**Milestone 3 — Ingestion and chunking:**
I will use an AI coding assistant to implement `load_documents()` and `chunk_text()` from this planning spec. I will give the model the Documents list and Chunking Strategy sections and verify the output by inspecting cleaned text and chunk lengths.

**Milestone 4 — Embedding and retrieval:**
I will prompt the AI assistant with the Retrieval Approach and the vector store design. The output should be a working embedding pipeline plus a `query()` function. I will verify it by running search queries and checking that the retrieved chunks match expected thread topics.

**Milestone 5 — Generation and interface:**
I will use the AI assistant to design the grounding prompt and a simple command-line or notebook query wrapper. I will verify by asking sample questions and confirming that the answer cites the source URLs or chunk IDs.
