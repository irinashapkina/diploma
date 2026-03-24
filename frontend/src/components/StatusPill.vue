<template>
  <span :class="['pill', variantClass]">{{ label }}</span>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  label: string;
  variant?: "ok" | "warn" | "err";
}>();

const variantClass = computed(() => props.variant ?? "ok");
</script>
