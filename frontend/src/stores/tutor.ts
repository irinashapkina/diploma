import { defineStore } from "pinia";
import { ref } from "vue";

import { api } from "@/api/endpoints";
import type { TutorAnswerResponse } from "@/types/api";
import { errorMessage } from "@/utils/format";

export const useTutorStore = defineStore("tutor", () => {
  const loading = ref(false);
  const error = ref<string | null>(null);
  const answer = ref<TutorAnswerResponse | null>(null);

  async function ask(params: { courseId: string; question: string; debug?: boolean }) {
    loading.value = true;
    error.value = null;
    try {
      answer.value = await api.askCourse(params.courseId, {
        course_id: params.courseId,
        question: params.question,
        debug: params.debug ?? false,
      });
      return answer.value;
    } catch (err) {
      error.value = errorMessage(err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  return { loading, error, answer, ask };
});
