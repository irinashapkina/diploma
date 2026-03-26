import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { api } from "@/api/endpoints";
import type { DocumentOut, VideoSegmentOut } from "@/types/api";
import { errorMessage } from "@/utils/format";

export const useVideosStore = defineStore("videos", () => {
  const loading = ref(false);
  const error = ref<string | null>(null);
  const currentCourseId = ref<string | null>(null);
  const videos = ref<DocumentOut[]>([]);
  const selectedVideoId = ref<string | null>(null);
  const segments = ref<VideoSegmentOut[]>([]);
  const selectedVideoStatus = ref<string>("uploaded");

  const selectedVideo = computed(() => videos.value.find((item) => item.document_id === selectedVideoId.value) ?? null);

  async function loadForCourse(courseId: string) {
    loading.value = true;
    error.value = null;
    currentCourseId.value = courseId;
    try {
      const items = await api.listDocuments(courseId);
      videos.value = items.filter((item) => item.material_type === "video");
      if (selectedVideoId.value && !videos.value.some((item) => item.document_id === selectedVideoId.value)) {
        selectedVideoId.value = null;
        segments.value = [];
      }
    } catch (err) {
      error.value = errorMessage(err);
    } finally {
      loading.value = false;
    }
  }

  async function loadSegments(courseId: string, documentId: string) {
    loading.value = true;
    error.value = null;
    selectedVideoId.value = documentId;
    try {
      const payload = await api.listVideoSegments(courseId, documentId);
      segments.value = payload.segments;
      selectedVideoStatus.value = payload.status;
    } catch (err) {
      error.value = errorMessage(err);
      segments.value = [];
    } finally {
      loading.value = false;
    }
  }

  return {
    loading,
    error,
    currentCourseId,
    videos,
    selectedVideoId,
    selectedVideo,
    selectedVideoStatus,
    segments,
    loadForCourse,
    loadSegments,
  };
});

