"""Deploy CourseLens to a Hugging Face Space (Docker SDK).

    python scripts/deploy_hf.py <hf-username>/<space-name>

Needs a Hugging Face login with write access (`hf auth login`). Uploads the
committed state of the repo (git archive HEAD, so local runtime churn is never
shipped), keeping only what the Docker image needs. The Space's README gets the
YAML header Spaces requires; GitHub's README stays clean.

After the first deploy, add GROQ_API_KEY under the Space's Settings → Secrets.
"""
import io
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

KEEP = ("Dockerfile", ".dockerignore", "requirements.txt", "README.md", "LICENSE",
        "backend/", "api/", "web/", "chroma_store/", "media_store/")

SPACE_HEADER = """---
title: CourseLens
emoji: 🎓
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
short_description: Ask your lectures and slides; answers cite the exact second.
---

"""


def main():
    if len(sys.argv) != 2 or "/" not in sys.argv[1]:
        sys.exit(__doc__)
    repo_id = sys.argv[1]
    root = Path(__file__).resolve().parent.parent
    archive = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=root,
                             check=True, capture_output=True).stdout
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            members = [m for m in tar.getmembers() if m.name.startswith(KEEP) or m.name in KEEP]
            tar.extractall(tmp, members=members, filter="data")
        readme = Path(tmp, "README.md")
        readme.write_text(SPACE_HEADER + readme.read_text())

        api = HfApi()
        api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                             check=True, capture_output=True, text=True).stdout.strip()
        api.upload_folder(folder_path=tmp, repo_id=repo_id, repo_type="space",
                          commit_message=f"Deploy {sha}",
                          delete_patterns=["backend/**", "api/**", "web/**"])
    print(f"Deployed {sha} → https://huggingface.co/spaces/{repo_id}")


if __name__ == "__main__":
    main()
