from __future__ import annotations

from app.config.settings import settings
from app.indexing.bm25.index import BM25Index
from app.indexing.dense.index import DenseTextIndex
from app.indexing.store import ArtifactStore
from app.indexing.visual.index import VisualPageIndex
from app.reranking.reranker import HeuristicReranker
from app.schemas.models import RetrievalCandidate
from app.utils.media import parse_video_locator


class HybridRetriever:
    def __init__(
        self,
        store: ArtifactStore,
        bm25: BM25Index,
        dense: DenseTextIndex,
        visual: VisualPageIndex,
        reranker: HeuristicReranker | None = None,
    ) -> None:
        self.store = store
        self.bm25 = bm25
        self.dense = dense
        self.visual = visual
        self.reranker = reranker or HeuristicReranker()

    def retrieve(
        self,
        query: str,
        course_id: str,
        mode: str,
        top_k: int = 8,
        query_forms: list[str] | None = None,
        visual_query: str | None = None,
    ) -> tuple[list[RetrievalCandidate], dict]:
        if not course_id:
            raise ValueError("course_id is required for retrieval")
        self.bm25.set_course_scope(course_id)
        self.dense.set_course_scope(course_id)
        self.visual.set_course_scope(course_id)
        chunks = self.store.list_chunks(course_id=course_id)
        pages = self.store.list_pages(course_id=course_id)
        chunk_map = {c.chunk_id: c for c in chunks}
        page_map = {p.page_id: p for p in pages}
        combined: dict[str, RetrievalCandidate] = {}
        debug: dict = {
            "bm25_hits": [],
            "dense_hits": [],
            "visual_hits": [],
            "query_used": query,
            "query_forms_used": [],
            "visual_query_used": None,
            "visual_error": None,
        }

        forms = query_forms or [query]
        for q_form in forms:
            debug["query_forms_used"].append(q_form)
            bm25_hits = self.bm25.search(q_form, top_k=settings.bm25_top_k)
            for hit in bm25_hits:
                chunk = chunk_map.get(hit.chunk_id)
                if not chunk:
                    continue
                key = f"text:{chunk.chunk_id}"
                cand = combined.get(key)
                if cand is None:
                    material_type = str(chunk.metadata.get("material_type", "document"))
                    cand = RetrievalCandidate(
                        candidate_id=key,
                        source_type="text",
                        score=0.0,
                        document_id=chunk.document_id,
                        document_title=chunk.document_title,
                        page_id=chunk.page_id,
                        page_number=chunk.page_number,
                        text=chunk.cleaned_text,
                        image_path=chunk.image_path,
                        debug={
                            "bm25_score": 0.0,
                            "dense_score": 0.0,
                            "visual_score": 0.0,
                            "has_diagram": bool(chunk.metadata.get("has_diagram", False)),
                            "text_source": chunk.metadata.get("text_source", "ocr"),
                            "pdf_text_quality": float(chunk.metadata.get("pdf_text_quality", 0.0)),
                            "ocr_text_quality": float(chunk.metadata.get("ocr_text_quality", 0.0)),
                            "material_type": material_type,
                            "time_start_sec": chunk.metadata.get("time_start_sec"),
                            "time_end_sec": chunk.metadata.get("time_end_sec"),
                            "time_label": chunk.metadata.get("time_label"),
                        },
                    )
                    combined[key] = cand
                cand.debug["bm25_score"] = max(float(cand.debug.get("bm25_score", 0.0)), float(hit.score))
                debug["bm25_hits"].append({"chunk_id": hit.chunk_id, "score": hit.score})

            dense_hits = self.dense.search(q_form, top_k=settings.dense_top_k)
            for hit in dense_hits:
                chunk = chunk_map.get(hit.chunk_id)
                if not chunk:
                    continue
                key = f"text:{chunk.chunk_id}"
                cand = combined.get(key)
                if cand is None:
                    material_type = str(chunk.metadata.get("material_type", "document"))
                    cand = RetrievalCandidate(
                        candidate_id=key,
                        source_type="text",
                        score=0.0,
                        document_id=chunk.document_id,
                        document_title=chunk.document_title,
                        page_id=chunk.page_id,
                        page_number=chunk.page_number,
                        text=chunk.cleaned_text,
                        image_path=chunk.image_path,
                        debug={
                            "bm25_score": 0.0,
                            "dense_score": 0.0,
                            "visual_score": 0.0,
                            "has_diagram": bool(chunk.metadata.get("has_diagram", False)),
                            "text_source": chunk.metadata.get("text_source", "ocr"),
                            "pdf_text_quality": float(chunk.metadata.get("pdf_text_quality", 0.0)),
                            "ocr_text_quality": float(chunk.metadata.get("ocr_text_quality", 0.0)),
                            "material_type": material_type,
                            "time_start_sec": chunk.metadata.get("time_start_sec"),
                            "time_end_sec": chunk.metadata.get("time_end_sec"),
                            "time_label": chunk.metadata.get("time_label"),
                        },
                    )
                    combined[key] = cand
                cand.debug["dense_score"] = max(float(cand.debug.get("dense_score", 0.0)), float(hit.score))
                debug["dense_hits"].append({"chunk_id": hit.chunk_id, "score": hit.score})

        if mode in {"visual", "hybrid"}:
            visual_search_query = (visual_query or query).strip()
            debug["visual_query_used"] = visual_search_query
            try:
                visual_hits = self.visual.search(visual_search_query, top_k=settings.visual_top_k)
                for hit in visual_hits:
                    page = page_map.get(hit.page_id)
                    if not page:
                        continue
                    key = f"visual:{page.page_id}"
                    cand = combined.get(key)
                    if cand is None:
                        locator = parse_video_locator(str(page.image_path))
                        material_type = "video" if str(page.image_path).startswith("video://") else "document"
                        cand = RetrievalCandidate(
                            candidate_id=key,
                            source_type="visual",
                            score=0.0,
                            document_id=page.document_id,
                            document_title=page.document_title,
                            page_id=page.page_id,
                            page_number=page.page_number,
                            text=(page.merged_text or page.pdf_text_raw or page.ocr_text_clean)[:900],
                            image_path=page.image_path,
                            debug={
                                "bm25_score": 0.0,
                                "dense_score": 0.0,
                                "visual_score": 0.0,
                                "has_diagram": page.has_diagram,
                                "text_source": page.text_source,
                                "pdf_text_quality": page.pdf_text_quality,
                                "ocr_text_quality": page.ocr_text_quality,
                                "material_type": material_type,
                                "time_start_sec": locator.get("start_sec") if locator else None,
                                "time_end_sec": locator.get("end_sec") if locator else None,
                                "time_label": locator.get("label") if locator else None,
                            },
                        )
                        combined[key] = cand
                    cand.debug["visual_score"] = max(float(cand.debug.get("visual_score", 0.0)), float(hit.score))
                    debug["visual_hits"].append({"page_id": hit.page_id, "score": hit.score})
            except Exception as exc:  # pragma: no cover - defensive guard
                debug["visual_error"] = str(exc)[:260]

        reranked = self.reranker.rerank(query=query, candidates=list(combined.values()), mode=mode, top_k=top_k)
        debug["final_candidates"] = [
            {
                "candidate_id": c.candidate_id,
                "score": c.score,
                "page": c.page_number,
                "type": c.source_type,
                "debug": c.debug,
            }
            for c in reranked
        ]
        return reranked, debug
