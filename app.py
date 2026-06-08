"""
app.py — Milestone 5: Gradio web interface for The Unofficial Guide.

A viewer enters a question; the system retrieves relevant student-review chunks,
generates a grounded answer, and shows which source threads it drew from.

"Console mode" is an optional toggle: when on, it reveals the exact retrieved
chunks (with cosine distance and source) that produced the answer — useful for
demonstrating grounding and for debugging. It is hidden by default.

Run:  python app.py    then open http://localhost:7860
"""

import gradio as gr

from generator import ask


def format_chunks(hits):
    """Render the retrieved chunks behind an answer for the console view."""
    if not hits:
        return "(no chunks retrieved)"
    blocks = []
    for i, h in enumerate(hits, 1):
        m = h["metadata"]
        body = h["text"].split("\n", 1)[1] if "\n" in h["text"] else h["text"]
        blocks.append(
            f'[{i}] distance {h["distance"]:.3f} | source {m["source_id"]} '
            f'"{m["source_title"]}" | {m["type"]} | u/{m["author"]}\n{body}'
        )
    return "\n\n".join(blocks)


def handle_query(question):
    question = (question or "").strip()
    if not question:
        return "Please enter a question.", "", ""
    result = ask(question)
    sources = "\n".join(f"• {s}" for s in result["sources"]) or "(none)"
    chunks = format_chunks(result["hits"])
    return result["answer"], sources, chunks


with gr.Blocks(title="The Unofficial Guide — Berkeley CS") as demo:
    gr.Markdown(
        "# The Unofficial Guide — Berkeley CS\n"
        "Ask about Berkeley CS courses and professors. Answers come **only** from "
        "student reviews collected from r/berkeley — the system declines when the "
        "reviews don't cover your question."
    )
    inp = gr.Textbox(
        label="Your question",
        placeholder="e.g. Which upper-division CS courses are must-takes?",
    )
    btn = gr.Button("Ask", variant="primary")
    answer = gr.Textbox(label="Answer", lines=8)
    sources = gr.Textbox(label="Retrieved from", lines=4)

    # Console mode: hidden by default; toggle reveals the chunks behind the answer.
    console_toggle = gr.Checkbox(
        label="Console mode — show the retrieved chunks used for the answer",
        value=False,
    )
    chunks_box = gr.Textbox(
        label="Retrieved chunks (cosine distance · source · author)",
        lines=16,
        visible=False,
    )

    btn.click(handle_query, inputs=inp, outputs=[answer, sources, chunks_box])
    inp.submit(handle_query, inputs=inp, outputs=[answer, sources, chunks_box])
    # Show/hide the chunks box when the toggle flips (content persists either way).
    console_toggle.change(lambda on: gr.update(visible=on),
                          inputs=console_toggle, outputs=chunks_box)

    gr.Examples(
        [
            "Which upper-division CS courses are must-takes?",
            "Why do students quit or leave the CS major?",
            "Which professors are approachable and good to talk to?",
        ],
        inputs=inp,
    )

if __name__ == "__main__":
    demo.launch()
