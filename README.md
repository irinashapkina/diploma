# Multimodal RAG MVP (RU/EN, PDF Slides)

Рабочий MVP мультимодальной RAG-системы для учебных PDF/слайдов по информатике:
- ingestion PDF -> страницы (image) + OCR;
- text chunking;
- multi-index retrieval: `BM25 + Dense + Visual`;
- router: `text/visual/hybrid`;
- grounded answer generation через `Qwen2.5-VL` (Ollama);
- anti-hallucination validation + confidence;
- FastAPI + CLI scripts + debug output.

## 1. Архитектура

```text
app/
  api/main.py                  # FastAPI endpoints
  ingestion/pdf_ingestor.py    # PDF -> pages -> OCR -> metadata
  ocr/preprocess.py            # grayscale/resize/denoise/threshold
  ocr/ocr_engine.py            # pytesseract + page heuristics
  chunking/chunker.py          # semantic-ish chunking by blocks/headings
  indexing/
    store.py                   # artifacts registry (documents/pages/chunks)
    index_manager.py           # orchestration
    bm25/index.py              # lexical retrieval
    dense/index.py             # sentence-transformers + FAISS
    visual/index.py            # CLIP backend + optional ColQwen2 backend
  retrieval/
    query_processing.py        # normalization/keywords/expansion
    hybrid.py                  # hybrid retrieval + merge candidates
  routing/router.py            # text/visual/hybrid mode
  reranking/reranker.py        # heuristic rerank
  answering/
    prompts.py                 # grounded prompt modes
    qwen_ollama.py             # Ollama client for Qwen2.5-VL
  validation/
    grounding.py               # unsupported facts detection
    confidence.py              # confidence estimation
  pipeline/rag_pipeline.py     # end-to-end ask flow
scripts/
  upload_pdf.py
  index_documents.py
  ask.py
  evaluate.py
tests/
  sample_questions.json
  test_router_and_query.py
```

## 2. Важные MVP-компромиссы

- Visual retrieval реализован рабочим `image-text retrieval` на CLIP по страницам (по умолчанию), с опциональным backend `ColQwen2` при установленном `colpali-engine`.
- Если `ColQwen2` не поднимается, код честно делает fallback в CLIP и пишет это в лог.
- На macOS по умолчанию используется `DENSE_BACKEND=numpy` (избегает нативных проблем FAISS в некоторых окружениях).
- Anti-hallucination реализован прагматично:
  - strict grounded prompts;
  - partial answer mode;
  - post-validation чисел/годов против retrieval context.

## 3. Требования окружения

1. Python 3.11 или 3.12 (рекомендуется 3.12). Python 3.14 сейчас не поддерживается этим набором зависимостей.
2. Установленный `tesseract` с языками `rus` и `eng`.
3. (Для Qwen2.5-VL) установлен и запущен Ollama, модель загружена:
   - `ollama pull qwen2.5vl:7b`
4. Установить зависимости:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 4. Запуск API

```bash
uvicorn app.api.main:app --reload
```

Endpoints:
- `POST /documents/upload`
- `POST /documents/index`
- `POST /ask`
- `GET /documents`
- `GET /documents/{id}/pages`

## 5. CLI usage

```bash
python scripts/upload_pdf.py /path/to/slides.pdf
python scripts/index_documents.py --document-id <DOC_ID>
python scripts/ask.py "как работает ram" --debug
```

Batch evaluation:
```bash
python scripts/evaluate.py --pdf-dir /path/to/pdfs --questions tests/sample_questions.json
```

## 6. Ответ `/ask`

Возвращает:
- `answer`
- `confidence`
- `mode` (`text|visual|hybrid`)
- `sources[]`
- `debug` (опционально)

## 7. Где менять компоненты

- OCR: [`app/ocr/ocr_engine.py`](app/ocr/ocr_engine.py), [`app/ocr/preprocess.py`](app/ocr/preprocess.py)
- Embeddings model: `EMBEDDING_MODEL_NAME` и [`app/indexing/dense/index.py`](app/indexing/dense/index.py)
- Visual retriever: `VISUAL_BACKEND` (`clip|colqwen2`) и [`app/indexing/visual/index.py`](app/indexing/visual/index.py)
- Dense backend: `DENSE_BACKEND` (`numpy|faiss`) и [`app/indexing/dense/index.py`](app/indexing/dense/index.py)
- Для диагностики можно временно выключить visual indexing: `ENABLE_VISUAL_INDEX=false`
- Qwen2.5-VL backend: [`app/answering/qwen_ollama.py`](app/answering/qwen_ollama.py)
- Router/reranker: [`app/routing/router.py`](app/routing/router.py), [`app/reranking/reranker.py`](app/reranking/reranker.py)

## 8. Отладка

Для debug retrival/context/validation:
- используйте `POST /ask` с `"debug": true`;
- смотрите поля:
  - `debug.router`
  - `debug.retrieval` (bm25/dense/visual/final)
  - `debug.context`
  - `debug.validation`
