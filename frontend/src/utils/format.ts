import axios from "axios";

export function toPrettyJson(data: unknown): string {
  return JSON.stringify(data, null, 2);
}

export function errorMessage(error: unknown): string {
  const dictionary: Record<string, string> = {
    "Only PDF files are supported.": "Поддерживается только формат PDF.",
    "Empty question.": "Вопрос не может быть пустым.",
    "course_id in path and body must match.": "Несовпадение course_id в URL и теле запроса.",
    "year_label must be yyyy or yyyy/yyyy": "Учебный год должен быть в формате ГГГГ или ГГГГ/ГГГГ.",
    "year_label yyyy/yyyy must have end=start+1":
      "Диапазон учебного года должен состоять из последовательных лет.",
    "semester must be one of: 1, 2, spring, autumn":
      "Семестр должен быть одним из значений: 1, 2, spring, autumn.",
  };

  function mapFieldName(field: string): string {
    const fields: Record<string, string> = {
      teacher_id: "ID преподавателя",
      title: "Название курса",
      year_label: "Учебный год",
      semester: "Семестр",
      description: "Описание",
      question: "Вопрос",
      course_id: "Курс",
      document_id: "Документ",
    };
    return fields[field] ?? field;
  }

  function translateMessage(msg: string): string {
    return dictionary[msg] ?? msg;
  }

  function parseValidationDetail(detail: unknown): string | null {
    if (!Array.isArray(detail) || detail.length === 0) return null;
    const first = detail[0] as Record<string, unknown>;
    const loc = Array.isArray(first?.loc) ? first.loc : [];
    const rawField = typeof loc[loc.length - 1] === "string" ? String(loc[loc.length - 1]) : "";
    const field = rawField ? mapFieldName(rawField) : "Поле";
    const rawMsg = typeof first?.msg === "string" ? first.msg : "Некорректное значение.";
    const msg = translateMessage(rawMsg.replace(/^Value error,\s*/i, ""));
    return `${field}: ${msg}`;
  }

  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") {
      return translateMessage(detail);
    }
    const validationError = parseValidationDetail(detail);
    if (validationError) {
      return validationError;
    }
    return "Не удалось выполнить запрос к серверу.";
  }
  if (error instanceof Error) {
    return translateMessage(error.message);
  }
  return "Неизвестная ошибка.";
}
