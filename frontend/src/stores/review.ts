import { defineStore } from "pinia";
import { ref } from "vue";

import { api } from "@/api/endpoints";
import type { ReviewIssue, ReviewReferenceSyncSummary, ReviewScanSummary } from "@/types/api";
import { errorMessage } from "@/utils/format";

export const useReviewStore = defineStore("review", () => {
  const loading = ref(false);
  const error = ref<string | null>(null);

  const referenceSummary = ref<ReviewReferenceSyncSummary | null>(null);
  const baseline = ref<Record<string, unknown> | null>(null);
  const baselineRunId = ref<string | null>(null);
  const baselineUpdatedAt = ref<string | null>(null);

  const scanSummary = ref<ReviewScanSummary | null>(null);
  const latestScan = ref<Record<string, unknown> | null>(null);
  const issues = ref<ReviewIssue[]>([]);

  async function syncReference(includeConcepts = true) {
    loading.value = true;
    error.value = null;
    try {
      const response = await api.syncReference({ include_concepts: includeConcepts });
      referenceSummary.value = response.summary;
      await loadBaseline();
      return response.summary;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function loadBaseline(runId?: string) {
    loading.value = true;
    error.value = null;
    try {
      const response = await api.getReferenceBaseline(runId);
      baseline.value = response.baseline ?? {};
      baselineRunId.value = response.run_id ?? null;
      baselineUpdatedAt.value = response.updated_at ?? null;
      return response;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function scanCourse(courseId: string, useCurrentBaseline = true) {
    loading.value = true;
    error.value = null;
    try {
      const response = await api.scanCourseReview(courseId, { use_current_baseline: useCurrentBaseline });
      scanSummary.value = response.summary;
      issues.value = [];
      latestScan.value = null;
      return response.summary;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function loadIssues(courseId: string) {
    loading.value = true;
    error.value = null;
    try {
      const response = await api.getCourseIssues(courseId);
      issues.value = response.issues ?? [];
      latestScan.value = response.scan ?? null;
      return response;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  return {
    loading,
    error,
    referenceSummary,
    baseline,
    baselineRunId,
    baselineUpdatedAt,
    scanSummary,
    latestScan,
    issues,
    syncReference,
    loadBaseline,
    scanCourse,
    loadIssues,
  };
});
