import { defineStore } from "pinia";
import { ref } from "vue";

import { api } from "@/api/endpoints";
import type { HealthResponse } from "@/types/api";
import { errorMessage } from "@/utils/format";

export const useHealthStore = defineStore("health", () => {
  const loading = ref(false);
  const error = ref<string | null>(null);
  const health = ref<HealthResponse | null>(null);

  async function fetchHealth() {
    loading.value = true;
    error.value = null;
    try {
      health.value = await api.health();
    } catch (err) {
      error.value = errorMessage(err);
    } finally {
      loading.value = false;
    }
  }

  return { loading, error, health, fetchHealth };
});
