export function formatDate(value: string) {
  return new Date(value).toLocaleString("ru-RU");
}

export function ingestStatusLabel(value: string) {
  const map: Record<string, string> = {
    uploaded: "Загружен",
    transcribing: "Транскрибация",
    indexing: "Индексация",
    ingested: "Обработан",
    indexed: "Проиндексирован",
    error: "Ошибка",
    failed: "Ошибка",
  };
  return map[value] ?? value;
}

export function ingestStatusVariant(value: string): "ok" | "warn" | "err" {
  if (value === "indexed" || value === "ingested") return "ok";
  if (value === "error" || value === "failed") return "err";
  return "warn";
}
