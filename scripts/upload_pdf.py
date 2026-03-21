from __future__ import annotations

import argparse
from pathlib import Path
import sys

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    with args.pdf_path.open("rb") as f:
        files = {"file": (args.pdf_path.name, f, "application/pdf")}
        r = requests.post(f"{args.api}/documents/upload", files=files, timeout=120)
    print(r.status_code)
    print(r.json())


if __name__ == "__main__":
    main()
