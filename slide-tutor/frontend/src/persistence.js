const DATABASE_NAME = "vlearn-slide-tutor";
const DATABASE_VERSION = 1;
const PDF_STORE = "deck-pdfs";

export const WORKSPACE_STORAGE_KEY = "vlearn-workspace-v1";

export const loadWorkspace = () => {
  try {
    const value = window.localStorage.getItem(WORKSPACE_STORAGE_KEY);
    if (!value) return null;
    const workspace = JSON.parse(value);
    if (!Array.isArray(workspace?.decks) || workspace.decks.length === 0) return null;
    return workspace;
  } catch {
    return null;
  }
};

export const saveWorkspace = (workspace) => {
  try {
    window.localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify(workspace));
  } catch (error) {
    console.warn("Unable to persist the VLearn workspace.", error);
  }
};

const openDatabase = () => new Promise((resolve, reject) => {
  if (!window.indexedDB) {
    reject(new Error("IndexedDB is unavailable."));
    return;
  }

  const request = window.indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
  request.onerror = () => reject(request.error);
  request.onsuccess = () => resolve(request.result);
  request.onupgradeneeded = () => {
    const database = request.result;
    if (!database.objectStoreNames.contains(PDF_STORE)) database.createObjectStore(PDF_STORE);
  };
});

const usePdfStore = async (mode, operation) => {
  const database = await openDatabase();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = database.transaction(PDF_STORE, mode);
      const request = operation(transaction.objectStore(PDF_STORE));
      request.onerror = () => reject(request.error);
      request.onsuccess = () => resolve(request.result);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally {
    database.close();
  }
};

export const saveDeckPdf = (deckId, file) => usePdfStore("readwrite", (store) => store.put(file, deckId));

export const getDeckPdf = (deckId) => usePdfStore("readonly", (store) => store.get(deckId));

export const deleteDeckPdf = (deckId) => usePdfStore("readwrite", (store) => store.delete(deckId));
