import { defineStore } from "pinia";
import { ref } from "vue";

import { api } from "@/api/endpoints";
import type {
  ReviewApplyResult,
  IndexJobOut,
  ReviewIssue,
  ReviewReferenceSyncSummary,
  ReviewRunOut,
  ReviewScanSummary,
} from "@/types/api";
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
  const applies = ref<ReviewApplyResult[]>([]);
  const applyingIssueIds = ref<string[]>([]);
  const reviewRuns = ref<ReviewRunOut[]>([]);
  const indexJobs = ref<IndexJobOut[]>([]);

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

  async function loadReviewRuns(courseId: string) {
    loading.value = true;
    error.value = null;
    try {
      const response = await api.listReviewRuns(courseId);
      reviewRuns.value = response.items ?? [];
      return response.items ?? [];
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function loadFilteredIssues(
    courseId: string,
    params?: { document_id?: string; status?: string; severity?: string; issue_type?: string; review_run_id?: string },
  ) {
    loading.value = true;
    error.value = null;
    try {
      const response = await api.listReviewIssues(courseId, params);
      issues.value = response.items ?? [];
      return issues.value;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function applyIssue(courseId: string, issueId: string) {
    error.value = null;
    if (!applyingIssueIds.value.includes(issueId)) {
      applyingIssueIds.value.push(issueId);
    }
    try {
      const response = await api.applyIssue(courseId, issueId, { apply_to_pdf: true });
      const result = response.result;
      const issue = issues.value.find((item) => item.issue_id === issueId);
      if (issue) {
        issue.status = result.status === "applied" ? "applied" : "review";
        issue.apply_result = result;
      }
      applies.value.unshift(result);
      return result;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      applyingIssueIds.value = applyingIssueIds.value.filter((id) => id !== issueId);
    }
  }

  async function loadApplies(courseId: string) {
    loading.value = true;
    error.value = null;
    try {
      const response = await api.getCourseApplies(courseId);
      applies.value = response.items ?? [];
      return response;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function loadIndexJobs(courseId: string) {
    loading.value = true;
    error.value = null;
    try {
      const response = await api.listCourseIndexJobs(courseId);
      indexJobs.value = response.items ?? [];
      return indexJobs.value;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function acceptIssue(issue: ReviewIssue, teacherId: string) {
    error.value = null;
    if (!applyingIssueIds.value.includes(issue.issue_id)) {
      applyingIssueIds.value.push(issue.issue_id);
    }
    try {
      const response = await api.acceptIssue(issue.issue_id, { teacher_id: teacherId });
      if (response.apply_result) {
        issue.apply_result = response.apply_result;
      }
      issue.status = "applied";
      return response;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      applyingIssueIds.value = applyingIssueIds.value.filter((id) => id !== issue.issue_id);
    }
  }

  async function editIssue(issue: ReviewIssue, teacherId: string, editedText: string) {
    error.value = null;
    if (!applyingIssueIds.value.includes(issue.issue_id)) {
      applyingIssueIds.value.push(issue.issue_id);
    }
    try {
      const response = await api.editIssue(issue.issue_id, { teacher_id: teacherId, edited_text: editedText });
      if (response.apply_result) {
        issue.apply_result = response.apply_result;
      }
      issue.suggestion = editedText;
      issue.status = "applied";
      return response;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      applyingIssueIds.value = applyingIssueIds.value.filter((id) => id !== issue.issue_id);
    }
  }

  async function rejectIssue(issue: ReviewIssue, teacherId: string) {
    error.value = null;
    try {
      await api.rejectIssue(issue.issue_id, { teacher_id: teacherId });
      issue.status = "rejected";
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
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
    applies,
    applyingIssueIds,
    reviewRuns,
    indexJobs,
    syncReference,
    loadBaseline,
    scanCourse,
    loadIssues,
    loadReviewRuns,
    loadFilteredIssues,
    applyIssue,
    loadApplies,
    loadIndexJobs,
    acceptIssue,
    editIssue,
    rejectIssue,
  };
});
