"""Test bootstrap: make the repo importable and provide a dummy Groq key.

The tests are fully offline — no Groq API calls happen anywhere. The dummy key
only satisfies client *construction* (ChatGroq/Groq validate the env var exists,
but no network happens until a real call is made).
"""
import os
import sys

os.environ.setdefault("GROQ_API_KEY", "dummy_key_for_offline_tests")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
