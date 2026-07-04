# CourseLens — Test Dataset

A small, **known-answer** dataset to check V1 functionality end-to-end (audio
upload + YouTube URL + timestamped, cited retrieval).

## Contents

```
test_dataset/
├── audio/
│   ├── lecture_graph_algorithms.mp3   # 89s synthetic CS lecture, KNOWN content + timeline
│   ├── lecture_data_structures.mp3    # 48s second lecture (arrays…trees), timestamped
│   └── me_at_the_zoo.mp3              # 19s real clip (YouTube's first video)
├── slides/
│   ├── sorting_algorithms_slides.pdf  # 2-page deck, text + an embedded bar chart
│   └── data_structures_slides.pdf     # 2 figures: memory bar chart + access-time table
├── youtube_links.txt                  # URLs for the YouTube ingestion path
├── test_questions.md                  # gold questions + expected answers + expected timestamps
└── README.md
```

Why synthetic audio? Because we know *exactly* what's in it and *when* — so you
can verify not just that CourseLens answers, but that it answers **correctly**
and that the citation deep-link points to the **right moment**. That's a real
functional test, not just a smoke test.

## How to run the test

1. Start the app (with your Groq key in `.env`):
   ```bash
   cd .. && source venv/bin/activate && streamlit run frontend/app.py
   ```
2. **Audio path:** in the sidebar, upload `audio/lecture_graph_algorithms.mp3`
   (and optionally `audio/me_at_the_zoo.mp3`). Wait for "Added … (N chunks)".
3. **YouTube path:** paste a URL from `youtube_links.txt` into the YouTube box.
4. Ask the questions in `test_questions.md` and compare answers + citation
   timestamps against the expected values.

## What "passing" looks like
- Answers match the gold answers in `test_questions.md`.
- Expanding **Sources** shows an audio player; pressing play starts at ~the
  expected timestamp (±15s is fine — chunk boundaries aren't exact).
- The off-corpus question ("capital of France") is refused, not answered.
- A graph question cites the lecture, not the zoo clip.

> These files live inside the repo but are **not** needed at runtime. If you
> don't want them shipped, they can be git-ignored later.
