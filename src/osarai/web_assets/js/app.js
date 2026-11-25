// Point d'entrée ES Module du portail Osarai (`app.js`)

import { initFeedbackUI, readFlags, reconcileFlagsWithTheme, writeFlags } from "./feedback.js";
import { initFlashcards } from "./flashcards.js";
import { initQuiz } from "./quiz.js";
import { initSearch } from "./search.js";

const GRADE_STORAGE_KEY = "osarai:v1:grade";
const THEME_STORAGE_KEY = "osarai:v1:theme";
const PROGRESS_PREFIX = "osarai:v1:progress:";
const VALID_GRADES = new Set(["6eme", "5eme", "4eme", "3eme"]);
const GRADE_LABELS = {
  "6eme": "6ème",
  "5eme": "5ème",
  "4eme": "4ème",
  "3eme": "3ème",
};
const PROGRESS_KEY_RE = /^(cycle-3|cycle-4):([a-z-]+):([a-z0-9]+(?:-[a-z0-9]+)*)$/;

let persistRequested = false;
function requestPersistentStorage() {
  if (persistRequested) return;
  persistRequested = true;
  if (navigator.storage && typeof navigator.storage.persist === "function") {
    navigator.storage.persist().catch(() => {});
  }
}

export function renderMath(rootEl) {
  if (!rootEl || typeof window.renderMathInElement !== "function") return;
  window.renderMathInElement(rootEl, {
    delimiters: [
      { left: "\\[", right: "\\]", display: true },
      { left: "\\(", right: "\\)", display: false },
    ],
    throwOnError: false,
  });
}

function getGrade() {
  try {
    const stored = window.localStorage.getItem(GRADE_STORAGE_KEY);
    if (stored && VALID_GRADES.has(stored)) {
      return stored;
    }
  } catch {
    // Repli silencieux sur 5ème
  }
  return "5eme";
}

function setGrade(grade) {
  const safeGrade = VALID_GRADES.has(grade) ? grade : "5eme";
  try {
    window.localStorage.setItem(GRADE_STORAGE_KEY, safeGrade);
  } catch {
    // Stockage local indisponible
  }
  window.dispatchEvent(new CustomEvent("osarai:grade-changed", { detail: { grade: safeGrade } }));
}

function showToast(message) {
  const toast = document.getElementById("global-toast");
  if (!toast) return;
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(toast._hideTimer);
  toast._hideTimer = window.setTimeout(() => {
    toast.hidden = true;
  }, 4200);
}

function initGradeFiltering() {
  const gradeSelect = document.getElementById("grade-select");
  const showAllBtn = document.getElementById("btn-show-all-grades");
  const emptyNotice = document.getElementById("empty-grade-notice");
  const gradeLabels = document.querySelectorAll("[data-current-grade-label]");
  let showAllOverride = false;

  function applyFilter() {
    const current = getGrade();
    if (gradeSelect && gradeSelect.value !== current) {
      gradeSelect.value = current;
    }
    for (const el of gradeLabels) {
      el.textContent = GRADE_LABELS[current] || current;
    }

    const cards = Array.from(document.querySelectorAll("[data-reperes-levels]"));
    if (cards.length === 0) return;

    let visibleCount = 0;
    let hiddenCount = 0;
    for (const card of cards) {
      const levels = String(card.dataset.reperesLevels || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const visible = showAllOverride || levels.includes(current);
      card.hidden = !visible;
      if (visible) visibleCount += 1;
      else hiddenCount += 1;
    }

    if (showAllBtn) {
      showAllBtn.hidden = showAllOverride || hiddenCount === 0;
    }
    if (emptyNotice) {
      emptyNotice.hidden = visibleCount > 0;
    }
  }

  if (gradeSelect) {
    gradeSelect.addEventListener("change", () => {
      showAllOverride = false;
      setGrade(gradeSelect.value);
      applyFilter();
    });
  }

  if (showAllBtn) {
    showAllBtn.addEventListener("click", () => {
      showAllOverride = true;
      applyFilter();
    });
  }

  window.addEventListener("osarai:grade-changed", applyFilter);
  applyFilter();
}

function initTabs() {
  const tablist = document.querySelector('[role="tablist"]');
  if (!tablist) return;
  const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
  if (!tabs.length) return;

  function activateTab(nextTab, moveFocus = false) {
    for (const tab of tabs) {
      const selected = tab === nextTab;
      tab.classList.toggle("is-active", selected);
      tab.setAttribute("aria-selected", selected ? "true" : "false");
      tab.tabIndex = selected ? 0 : -1;
      const panelId = tab.getAttribute("aria-controls");
      const panel = panelId ? document.getElementById(panelId) : null;
      if (panel) {
        panel.hidden = !selected;
      }
    }
    if (moveFocus) {
      nextTab.focus();
    }
  }

  tabs.forEach((tab, idx) => {
    tab.addEventListener("click", () => activateTab(tab, false));
    tab.addEventListener("keydown", (event) => {
      let targetIdx = null;
      if (event.key === "ArrowRight") targetIdx = (idx + 1) % tabs.length;
      else if (event.key === "ArrowLeft") targetIdx = (idx - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") targetIdx = 0;
      else if (event.key === "End") targetIdx = tabs.length - 1;

      if (targetIdx !== null) {
        event.preventDefault();
        activateTab(tabs[targetIdx], true);
      }
    });
  });
}

function initDialogsAndZoom() {
  document.addEventListener("click", (event) => {
    const closeBtn = event.target.closest("[data-close-dialog]");
    if (closeBtn) {
      const dlg = document.getElementById(closeBtn.dataset.closeDialog);
      if (dlg) {
        if (typeof dlg.close === "function") dlg.close();
        else dlg.removeAttribute("open");
      }
      return;
    }

    const zoomBtn = event.target.closest(".btn-zoom-asset");
    if (zoomBtn) {
      const zoomDialog = document.getElementById("image-zoom-dialog");
      const zoomBody = document.getElementById("image-zoom-body");
      const stage = zoomBtn.closest(".asset-stage");
      const container = stage ? stage.querySelector(".asset-container") : null;
      if (zoomDialog && zoomBody && container) {
        zoomBody.replaceChildren(container.cloneNode(true));
        if (typeof zoomDialog.showModal === "function") zoomDialog.showModal();
        else zoomDialog.setAttribute("open", "");
      }
    }
  });

  // Fermer les <dialog> au clic sur l'arrière-plan (backdrop)
  for (const dlg of document.querySelectorAll("dialog.modal-dialog")) {
    dlg.addEventListener("click", (event) => {
      if (event.target === dlg && typeof dlg.close === "function") {
        dlg.close();
      }
    });
  }
}

function validateBackupPayload(obj) {
  if (!obj || typeof obj !== "object") return false;
  if (obj.schema !== "osarai-backup-v1") return false;
  if (!VALID_GRADES.has(obj.grade)) return false;
  if (typeof obj.exported_at !== "string") return false;
  if (!obj.progress || typeof obj.progress !== "object" || Array.isArray(obj.progress)) {
    return false;
  }
  for (const [key, val] of Object.entries(obj.progress)) {
    if (!PROGRESS_KEY_RE.test(key)) return false;
    if (!val || typeof val !== "object") return false;
  }
  if (!Array.isArray(obj.flags)) return false;
  return true;
}

function initBackupControls() {
  const exportBtn = document.getElementById("btn-export-backup");
  const importBtn = document.getElementById("btn-import-backup");
  const fileInput = document.getElementById("input-import-backup");

  if (exportBtn) {
    exportBtn.addEventListener("click", () => {
      const progress = {};
      try {
        for (let i = 0; i < window.localStorage.length; i += 1) {
          const k = window.localStorage.key(i);
          if (k && k.startsWith(PROGRESS_PREFIX)) {
            const shortKey = k.slice(PROGRESS_PREFIX.length);
            if (PROGRESS_KEY_RE.test(shortKey)) {
              progress[shortKey] = JSON.parse(window.localStorage.getItem(k) || "{}");
            }
          }
        }
      } catch {
        // Ignorer les entrées illisibles
      }

      const payload = {
        schema: "osarai-backup-v1",
        exported_at: new Date().toISOString(),
        grade: getGrade(),
        progress,
        flags: readFlags(),
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = "osarai-backup-v1.json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      showToast("Sauvegarde osarai-backup-v1.json téléchargée.");
    });
  }

  if (importBtn && fileInput) {
    importBtn.addEventListener("click", () => {
      fileInput.value = "";
      fileInput.click();
    });

    fileInput.addEventListener("change", async () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      try {
        const text = await file.text();
        const parsed = JSON.parse(text);
        if (!validateBackupPayload(parsed)) {
          showToast("Fichier de sauvegarde invalide (attendu : osarai-backup-v1).");
          return;
        }
        for (const [shortKey, val] of Object.entries(parsed.progress)) {
          window.localStorage.setItem(
            `${PROGRESS_PREFIX}${shortKey}`,
            JSON.stringify({
              cards: val.cards && typeof val.cards === "object" ? val.cards : {},
              quiz: val.quiz && typeof val.quiz === "object" ? val.quiz : null,
            })
          );
        }
        writeFlags(parsed.flags);
        setGrade(parsed.grade);
        requestPersistentStorage();
        showToast("Progression et signalements restaurés avec succès.");
      } catch {
        showToast("Impossible de lire ce fichier JSON de sauvegarde.");
      }
    });
  }
}

function getStoredTheme() {
  try {
    const val = window.localStorage.getItem(THEME_STORAGE_KEY);
    return val === "light" || val === "dark" ? val : null;
  } catch {
    return null;
  }
}

function initThemeToggle() {
  const toggleBtn = document.getElementById("btn-theme-toggle");
  const meta = document.querySelector('meta[name="color-scheme"]');
  if (!meta) return;

  const applyMeta = (scheme) => {
    meta.content = scheme === "light" || scheme === "dark" ? scheme : "light dark";
  };

  applyMeta(getStoredTheme());

  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      const sysDark =
        Boolean(window.matchMedia) && window.matchMedia("(prefers-color-scheme: dark)").matches;
      const sysScheme = sysDark ? "dark" : "light";
      const currentMeta = meta.content === "light" || meta.content === "dark" ? meta.content : null;
      const rendered = currentMeta || getStoredTheme() || sysScheme;
      const target = rendered === "dark" ? "light" : "dark";

      if (target === sysScheme) {
        try {
          window.localStorage.removeItem(THEME_STORAGE_KEY);
        } catch {
          // Stockage local indisponible
        }
        applyMeta(null);
      } else {
        try {
          window.localStorage.setItem(THEME_STORAGE_KEY, target);
        } catch {
          // Appliquer tout de même le thème à la page courante
        }
        applyMeta(target);
      }
    });
  }

  window.addEventListener("storage", (event) => {
    if (event.key === THEME_STORAGE_KEY || event.key === null) {
      applyMeta(getStoredTheme());
    }
  });
}

function bootstrap() {
  const htmlEl = document.documentElement;
  const baseUrl = htmlEl.dataset.baseUrl || "";
  const repoUrl = htmlEl.dataset.repoUrl || "https://github.com/Seburan/osarai";

  if (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) {
    requestPersistentStorage();
  }

  initThemeToggle();
  initGradeFiltering();
  initTabs();
  initDialogsAndZoom();
  initSearch({ baseUrl });
  initBackupControls();

  const feedbackApi = initFeedbackUI({
    repoUrl,
    requestPersist: requestPersistentStorage,
  });

  const summaryPanel = document.getElementById("panel-summary");
  if (summaryPanel) {
    renderMath(summaryPanel);
  }

  const themeDataScript = document.getElementById("theme-data");
  if (themeDataScript) {
    let themeData = null;
    try {
      themeData = JSON.parse(themeDataScript.textContent || "{}");
    } catch {
      themeData = null;
    }

    if (themeData) {
      reconcileFlagsWithTheme(themeData);
      const progressStorageKey = `${PROGRESS_PREFIX}${themeData.cycle}:${themeData.subject}:${themeData.theme_slug}`;

      const readThemeProgress = () => {
        try {
          const raw = window.localStorage.getItem(progressStorageKey);
          if (!raw) return { cards: {}, quiz: null };
          const obj = JSON.parse(raw);
          return {
            cards: obj && typeof obj.cards === "object" ? obj.cards : {},
            quiz: obj && typeof obj.quiz === "object" ? obj.quiz : null,
          };
        } catch {
          return { cards: {}, quiz: null };
        }
      };

      const writeThemeProgress = (nextObj) => {
        try {
          window.localStorage.setItem(progressStorageKey, JSON.stringify(nextObj));
        } catch {
          // Stockage local indisponible
        }
      };

      initFlashcards({
        themeData,
        getGrade,
        readThemeProgress,
        writeThemeProgress,
        renderMath,
        openFlagModal: feedbackApi.openFlagModal,
        requestPersist: requestPersistentStorage,
      });

      initQuiz({
        themeData,
        getGrade,
        readThemeProgress,
        writeThemeProgress,
        renderMath,
        openFlagModal: feedbackApi.openFlagModal,
        requestPersist: requestPersistentStorage,
      });
    }
  }
}

bootstrap();
