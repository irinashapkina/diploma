<template>
  <pre class="json">{{ content }}</pre>
</template>

<script setup lang="ts">
import { computed } from "vue";

import { toPrettyJson } from "@/utils/format";

const props = defineProps<{
  data: unknown;
}>();

const content = computed(() => toPrettyJson(props.data));
</script>
