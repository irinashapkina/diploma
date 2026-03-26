import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { api } from "@/api/endpoints";
import type { DocumentOut, IndexCourseResponse } from "@/types/api";
import { errorMessage } from "@/utils/format";

const SELECTED_STORAGE_KEY = "ta_selected_document";

export const useDocumentsStore = defineStore("documents", () => {
  const loading = ref(false);
  const error = ref<string | null>(null);

  const currentCourseId = ref<string | null>(null);
  const documents = ref<DocumentOut[]>([]);
  const selectedDocumentId = ref<string | null>(localStorage.getItem(SELECTED_STORAGE_KEY));
  const documentStatuses = ref<Record<string, string>>({});
  const indexResult = ref<IndexCourseResponse | null>(null);

  const selectedDocument = computed(() =>
    documents.value.find((document) => document.document_id === selectedDocumentId.value) ?? null,
  );

  function setSelectedDocument(documentId: string | null) {
    selectedDocumentId.value = documentId;
    if (documentId) {
      localStorage.setItem(SELECTED_STORAGE_KEY, documentId);
    } else {
      localStorage.removeItem(SELECTED_STORAGE_KEY);
    }
  }

  function upsertDocument(document: DocumentOut) {
    const index = documents.value.findIndex((item) => item.document_id === document.document_id);
    if (index >= 0) {
      documents.value[index] = document;
    } else {
      documents.value.unshift(document);
    }
    documentStatuses.value = { ...documentStatuses.value, [document.document_id]: document.status || "uploaded" };
  }

  async function loadForCourse(courseId: string) {
    loading.value = true;
    error.value = null;
    currentCourseId.value = courseId;
    try {
      const items = await api.listDocuments(courseId);
      documents.value = items;
      const statuses: Record<string, string> = {};
      for (const item of items) {
        statuses[item.document_id] = item.status || documentStatuses.value[item.document_id] || "uploaded";
      }
      documentStatuses.value = statuses;
      if (
        selectedDocumentId.value &&
        !documents.value.some((document) => document.document_id === selectedDocumentId.value)
      ) {
        setSelectedDocument(null);
      }
      return items;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function upload(courseId: string, file: File) {
    loading.value = true;
    error.value = null;
    currentCourseId.value = courseId;
    try {
      const uploadResult = await api.uploadDocument(courseId, file);
      upsertDocument(uploadResult.document);
      setSelectedDocument(uploadResult.document.document_id);
      return uploadResult.document;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function index(courseId: string, documentId?: string | null) {
    loading.value = true;
    error.value = null;
    try {
      indexResult.value = await api.indexCourse(courseId, {
        document_id: documentId ?? null,
      });
      if (documentId) {
        documentStatuses.value = { ...documentStatuses.value, [documentId]: "indexed" };
      } else {
        const statuses = { ...documentStatuses.value };
        for (const item of documents.value) {
          statuses[item.document_id] = "indexed";
        }
        documentStatuses.value = statuses;
      }
      return indexResult.value;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  function clearCourse() {
    currentCourseId.value = null;
    documents.value = [];
    documentStatuses.value = {};
    setSelectedDocument(null);
    indexResult.value = null;
  }

  return {
    loading,
    error,
    currentCourseId,
    documents,
    selectedDocumentId,
    selectedDocument,
    documentStatuses,
    indexResult,
    setSelectedDocument,
    loadForCourse,
    upload,
    index,
    clearCourse,
  };
});
