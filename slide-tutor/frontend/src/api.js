const API_BASE = import.meta.env.VITE_API_BASE || "";

export const DEVELOPMENT_COURSE_ID =
  import.meta.env.VITE_COURSE_ID || "00000000-0000-0000-0000-000000000010";

const apiUrl = (path) => `${API_BASE}${path}`;

const readError = async (response) => {
  try {
    const payload = await response.json();
    return payload?.error?.message || payload?.detail || `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
};

const request = async (path, options) => {
  const response = await fetch(apiUrl(path), options);
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
};

export const uploadDeck = (file, title) => {
  const formData = new FormData();
  formData.append("course_id", DEVELOPMENT_COURSE_ID);
  formData.append("title", title);
  formData.append("file", file);
  return request("/api/decks", { method: "POST", body: formData });
};

export const getDeckStatus = (deckId) => request(`/api/decks/${deckId}/status`);

export const getDeckSlides = (deckId) => request(`/api/decks/${deckId}/slides`);

export const answerQuestion = (payload) => request("/api/chat/answer", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});

export const waitForDeck = async (deckId, onStatus, options = {}) => {
  const interval = options.interval ?? 1_500;
  const attempts = options.attempts ?? 120;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const status = await getDeckStatus(deckId);
    onStatus?.(status);

    if (status.status === "failed" || ["failed", "drifted"].includes(status.index_status) || status.error_code) {
      throw new Error(status.error_detail || "The slide deck could not be processed.");
    }
    if (status.status === "ready" && status.index_status === "in_sync") return status;
    if (attempt < attempts - 1) await new Promise((resolve) => window.setTimeout(resolve, interval));
  }

  throw new Error("Slide processing timed out. Please try again.");
};
