from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.indexing.index_manager import IndexManager
from app.indexing.store import ArtifactStore
from app.ingestion.pdf_ingestor import PDFIngestor
from app.pipeline.rag_pipeline import RAGPipeline


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--questions", type=Path, default=Path("tests/sample_questions.json"))
    parser.add_argument("--top-k", type=int, default=6)
    args = parser.parse_args()

    ingestor = PDFIngestor()
    indexer = IndexManager()
    pipeline = RAGPipeline()
    store = ArtifactStore()
    teacher = store.create_teacher("Auto Evaluator")
    course = store.create_course(teacher_id=teacher.teacher_id, title="Evaluation Course", year_label="2026")

    if args.pdf_dir.is_file():
        pdf_files = [args.pdf_dir]
    else:
        pdf_files = sorted(args.pdf_dir.glob("*.pdf"))

    docs = []
    for pdf in pdf_files:
        doc = ingestor.ingest_pdf(pdf, course_id=course.course_id)
        indexer.index_document(course_id=course.course_id, document_id=doc.document_id)
        docs.append(doc.document_title)
        print(f"[INGEST+INDEX] {pdf.name} -> {doc.document_id}")

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    print(f"\nLoaded docs: {docs}\n")
    for q in questions:
        resp = pipeline.ask(q, course_id=course.course_id, top_k=args.top_k, debug=True)
        print("=" * 100)
        print("Q:", q)
        print("MODE:", resp.mode, "CONF:", resp.confidence)
        print("A:", resp.answer)
        print("SOURCES:", [f"{s.document_title}:p{s.page}:{s.type}:{s.score}" for s in resp.sources[:3]])
        if resp.debug:
            print("ROUTER:", resp.debug.get("router"))
            print("UNSUPPORTED:", resp.debug.get("validation", {}).get("unsupported_facts"))


if __name__ == "__main__":
    main()
