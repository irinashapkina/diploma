import { defineStore } from "pinia";
import { ref } from "vue";

export const useReviewStore = defineStore("review", () => {
  const loading = ref(false);
  const error = ref<string | null>("Раздел проверки отключен: в текущем backend нет review API.");

  return { loading, error };
});
