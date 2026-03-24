from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    payload = {"course_id": args.course_id, "question": args.question, "top_k": args.top_k, "debug": args.debug}
    r = requests.post(f"{args.api}/courses/{args.course_id}/ask", json=payload, timeout=240)
    print(r.status_code)
    try:
        body = r.json()
    except ValueError:
        text = (r.text or "").strip()
        print(text if text else "<empty response body>")
        sys.exit(1 if r.status_code >= 400 else 0)

    print(json.dumps(body, ensure_ascii=False, indent=2))
    if r.status_code >= 400:
        sys.exit(1)


if __name__ == "__main__":
    main()
