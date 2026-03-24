from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.indexing.index_manager import IndexManager


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--document-id", default=None)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Run indexing directly in this process (without HTTP API).",
    )
    args = parser.parse_args()

    if args.direct:
        manager = IndexManager()
        if args.document_id:
            result = manager.index_document(course_id=args.course_id, document_id=args.document_id)
        else:
            result = manager.index_course(course_id=args.course_id)
        print(json.dumps({"status": "indexed", "result": result}, ensure_ascii=False, indent=2))
        return

    payload = {"document_id": args.document_id}
    r = requests.post(f"{args.api}/courses/{args.course_id}/index", json=payload, timeout=3600)
    print(r.status_code)
    try:
        print(r.json())
    except Exception:
        print(r.text)


if __name__ == "__main__":
    main()
