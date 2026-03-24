import { defineStore } from "pinia";
import { ref } from "vue";

export const useVideosStore = defineStore("videos", () => {
  const loading = ref(false);
  const error = ref<string | null>("Видео-сценарий отключен: в текущем backend нет API для видео.");

  return { loading, error };
});
