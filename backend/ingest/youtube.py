"""CourseLens — YouTube ingestion (local-only bonus).

yt-dlp downloads the audio track; from there it's the same Whisper pipeline as an
uploaded audio file. yt-dlp is frequently blocked from datacenter IPs, so this
path is disabled in hosted deploys (see ENABLE_YOUTUBE).
"""
import os
import glob
import tempfile

from backend.ingest.audio import transcribe_audio


def build_youtube_chunks(url):
    """YouTube URL → chunk dicts ready for the store."""
    import yt_dlp  # imported lazily so the app runs without it installed

    with tempfile.TemporaryDirectory() as workdir:
        opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(workdir, "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            audio_file = ydl.prepare_filename(info)

        # prepare_filename can report a different extension than what landed on
        # disk; fall back to whatever was actually downloaded.
        if not os.path.exists(audio_file):
            downloaded = glob.glob(os.path.join(workdir, "*"))
            if not downloaded:
                raise RuntimeError("yt-dlp produced no audio file.")
            audio_file = downloaded[0]

        title = info.get("title", "YouTube video")
        watch_url = f"https://www.youtube.com/watch?v={info.get('id')}"
        chunks = transcribe_audio(audio_file)

    return [
        {
            "text": c["text"],
            "metadata": {
                "source_name": title,
                "source_type": "youtube",
                "ts_start": c["ts_start"],
                "ts_end": c["ts_end"],
                "youtube_url": watch_url,
            },
        }
        for c in chunks
    ]
