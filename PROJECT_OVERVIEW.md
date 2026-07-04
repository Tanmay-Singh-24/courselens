# Course Companion — Project Overview

> A plain-language explanation of what we're building, why, and how each piece works.
> This is a planning document. No code has been written yet.

---

## In one sentence

An AI study assistant that lets you dump a whole course into it — lecture videos, slide PDFs, and readings — and then ask questions that get answered *across all of it*, where every answer links back to the exact source: click a citation and the video jumps to the right second, or the referenced diagram appears right there in the chat.

---

## The problem it solves

Imagine it's exam week. Everything you need to know for the course is scattered across three kinds of stuff:

- **Lecture videos** — hours of them. Somewhere in Lecture 8, the professor explained the one concept you're stuck on. But where? You'd have to scrub through the whole video to find it.
- **Slide PDFs** — full of diagrams and charts. The answer to your question might literally *be* a picture, not text.
- **Readings/papers** — dense and long.

No existing free tool lets you ask one question and search across *all three at once* — and then take you straight to the exact moment or the exact figure the answer came from.

That's the gap. This tool closes it.

**Who it's for:** students studying for exams, anyone taking an online course (MIT OpenCourseWare, Coursera, YouTube lecture series) who wants to *ask their course questions* instead of manually searching it.

---

## What it feels like to use (the experience)

1. You add your course material: upload some slide PDFs, drop in a lecture audio file, and paste a few YouTube lecture links.
2. The tool spends a minute "reading" all of it (transcribing the audio, reading the slides, looking at the diagrams).
3. You type a question like: *"Where does she explain how photosynthesis stores energy?"*
4. You get a clear answer written in plain English — **and** below it:
   - A citation like **[Lecture 8 @ 14:32]** that you can click to open the video at exactly 14 minutes 32 seconds.
   - If the answer came from a diagram, **the diagram itself shows up** in the chat.
5. If the answer genuinely isn't in your materials, the tool says so — instead of making something up.

---

## How it works — each piece in plain language

The core idea is called **RAG** (Retrieval-Augmented Generation). Here's what that means without the jargon:

> A regular chatbot answers from memory and often makes things up ("hallucinates").
> RAG instead **looks up the relevant material first**, then answers *only* from what it found — and tells you where it got it. Like the difference between a student guessing on a test versus one allowed to look at their notes and cite the page.

Now, the steps:

### 1. Getting everything into text
Computers search text well, but a video or a diagram isn't text. So the first job is to **turn every kind of input into text**:

- **Audio/video → text:** We send the audio to **Whisper** (a speech-to-text model). It writes down everything spoken, *with timestamps* — so we know that the sentence "photosynthesis stores energy as sugar" was said at 14:32.
- **Slide diagrams → text:** We pull each image out of the PDF and show it to a **vision model** (an AI that can "see" pictures). It writes a caption describing the diagram — e.g., "A flowchart showing the light-dependent reactions of photosynthesis." That caption is now searchable text that stands in for the picture.
- **Slide/paper text → text:** Already text, so we just read it straight out of the PDF.

This is the "multimodal" part: three different **modalities** (audio, image, text) all get converted into one common format — text — so they can live in one searchable place. The clever bit is the *mismatch*: the knowledge is trapped in audio or a picture, but your question is text. We bridge that gap.

### 2. Chopping it into chunks
A whole lecture transcript is too big to work with at once. We cut everything into small **chunks** (a few sentences each). Each chunk keeps a "label" attached to it (which lecture, what timestamp, or which page/figure it came from) so we can cite it later.

### 3. Turning chunks into "meaning coordinates" (embeddings)
This is the part that sounds magical but is simple in spirit:

> An **embedding** turns a piece of text into a list of numbers that represents its *meaning*. Texts about similar ideas get similar numbers. Think of it as giving every chunk a location on a giant "map of meaning" — sentences about photosynthesis all cluster together in one region, sentences about the French Revolution cluster somewhere far away.

We store all these on the map inside a **vector store** (a database built for meaning-based search). We use one called **ChromaDB**.

### 4. Answering a question
When you ask something:

1. Your question also gets turned into a location on the meaning-map.
2. The tool finds the chunks **nearest** to it on the map — those are the most relevant pieces of your course. (This is the "retrieval" in RAG.)
3. It hands those chunks to the language model and says: *"Answer the question using only this, and cite where each fact came from."*
4. You get a grounded, cited answer.

### 5. The "double-check" step (what makes it smart, not just a lookup)
Plain RAG has a weakness: sometimes the chunks it finds *aren't actually relevant*, but it answers from them anyway — confidently and wrongly. We add a **grader**: a small AI step that looks at the retrieved chunks and asks *"do these actually answer the question?"*

- If **yes** → write the answer.
- If **no** → either rephrase the question and search again, or honestly say *"this isn't in your materials."*

This pattern is called **corrective RAG**. It's the difference between a system that always blurts *something* and one that knows when to say "I don't know."

### 6. Making citations *actionable*
Most tools cite a source as plain text. We go further:

- A transcript citation becomes a **clickable deep link** — clicking **[Lecture 8 @ 14:32]** opens the YouTube video at that exact second (using the `?t=872` trick in the URL).
- A diagram citation **renders the actual image** in the chat, so you see the figure the answer is based on.

This is the single most memorable feature in a demo.

---

## The architecture (how the pieces connect)

We use **LangGraph** to wire everything into a pipeline — think of it as a flowchart the program follows. Some steps only run when needed (like the retry loop), which is exactly what LangGraph's "conditional" connections are for.

**Ingesting (happens when you add material):**
```
You add a file/link
      │
   What type is it?
      ├── PDF   → pull out text + pull out images → caption the images → chunk it all
      ├── Audio → Whisper transcribes with timestamps → chunk it
      └── YouTube URL → download the audio → Whisper → chunk it
      │
   Turn every chunk into an embedding → store in ChromaDB
```

**Answering (happens when you ask):**
```
Your question
      │
  Rewrite it into a clean search query (resolves "it"/"that" from earlier chat)
      │
  Retrieve the most relevant chunks from ChromaDB
      │
  Grader: are these chunks actually relevant?
      ├── Yes → Generate a cited answer (with deep links + figures)
      └── No  → Retry the search, or say "not in your materials"
```

> **One honest note on wording:** the "what type is it?" step on the ingest side is just simple file-type detection (plain code, not AI). The genuinely "agentic" (AI-decision-making) part is the **grader loop** on the answer side. We describe it accurately — no dressing up an if-statement as an "agent."

---

## The tech stack (what each tool is and why it's here)

| Tool | What it does | Why this one |
|---|---|---|
| **LangGraph** | Orchestrates the whole pipeline as a flowchart | Handles the retry/grader loop cleanly; already used in PaperMind |
| **ChromaDB** | Stores the "meaning-map" and does the search | Simple, runs locally, free |
| **Embedding model** (HuggingFace) | Turns text into meaning-coordinates | Runs locally, free, no API needed |
| **Whisper** (via Groq) | Turns speech into timestamped text | Free on Groq, fast, high quality |
| **Vision model** (via Groq) | Describes diagrams/images in words | Free on Groq; unlocks the "answer from a figure" ability |
| **yt-dlp** | Downloads audio from YouTube links | Free, standard tool |
| **PyMuPDF** | Pulls text and images out of PDFs | Reliable, free |
| **Streamlit** | The web interface (upload + chat) | Fast to build, already used in PaperMind |
| **Groq** | Runs the language model that writes answers | Free API, very fast |

> The exact Groq model names (for Whisper and the vision model) drift over time, so we'll **verify the current IDs as the first step** when we start building — not hardcode today's guess.

---

## What makes this *not* a generic clone

A dozen "chat with your files" projects exist. Ours is different in four specific, defensible ways — and almost no clone repo has *any* of them:

1. **A real problem and a real user** — it's a study tool for exam week, not a vague "chat with documents" demo. You can say *"I built it for my own courses."*
2. **Actionable citations** — click-to-jump video timestamps and inline figures. This is the "wow" moment.
3. **Corrective RAG** — it knows when *not* to answer, instead of confidently making things up.
4. **Proof it works** — an evaluation that produces real accuracy numbers (see below). This is what separates "engineered" from "tutorial project."

---

## How we'll prove it works (the evals)

Most portfolio projects say "it works, trust me." We'll measure it instead.

We build a small **test set**: ~25 questions where we already know the right source (e.g., *"the answer to Q7 is in Lecture 3 at 8:15"* or *"in Figure 2 of the slides"*). Then we run the tool on all 25 and measure:

- **Retrieval hit-rate:** how often the correct source shows up in the top few results.
- **Groundedness:** how often the written answer actually sticks to the retrieved material (vs. drifting).

That gives a real number for the resume, like *"85% retrieval accuracy across text, audio, and image sources on a hand-labeled test set"* — a sentence you can defend in an interview.

---

## The build order (one piece at a time)

We don't build it all at once. Each version is usable on its own:

- **V1** — Audio file → Whisper → chat, with clickable timestamp citations. *(Most impressive for least effort; lowest risk.)*
- **V2** — PDF figure extraction → vision captions → figures shown in answers.
- **V3** — The corrective-RAG grader loop (the honest "agentic" layer).
- **V4** — The eval harness + accuracy numbers in the README.
- **V5** — Polish + deploy. YouTube-link ingestion stays as a local/demo bonus.

> **Why YouTube ingestion is a "bonus," not the core:** YouTube blocks automated downloads from cloud servers, so `yt-dlp` often fails on a hosted app even though it works perfectly on your laptop. Audio **file upload** is the reliable path that works everywhere; YouTube links are a nice extra for local demos.

---

## Known limitations (being honest about failure modes)

Knowing where your system breaks is a sign of seniority, not weakness. Ours:

- **Vector graphics don't extract.** Many textbook figures are drawn as vectors, not photos; the image extractor only grabs raster (photo-like) images. We'll filter out tiny junk images (logos) by size and note this limit.
- **Long audio needs splitting.** Whisper's free endpoint caps file size (~25 MB), so a 90-minute lecture must be cut into pieces before transcribing. We handle this in code.
- **Captions are only as good as the vision model.** A complex diagram might get a shallow caption. We treat captions as a *searchable stand-in*, and always show the real image so you can judge for yourself.
- **YouTube downloads are unreliable on cloud hosting** (see above).

---

## The interview story (the payoff)

> *"I built a study tool that ingests a whole course — lecture videos, slides, and readings — into one searchable knowledge base. Every answer cites its source, and citations are actionable: click one and the video jumps to that exact second, or the referenced diagram appears inline. It uses corrective RAG so it refuses to answer from irrelevant material, and I measured it against a hand-labeled test set to get a real retrieval-accuracy number."*

Every phrase in that sentence is something you can be grilled on and defend — which is the actual test of a resume project.
