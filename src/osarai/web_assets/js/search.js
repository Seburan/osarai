// Îlot de recherche transversale insensible aux ligatures (`œ`/`æ`) et aux diacritiques

export function normalizeSearchQuery(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/œ/g, "oe")
    .replace(/æ/g, "ae")
    .replace(/[\u2018\u2019]/g, "'")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function matchesSearchToken(hay, tok) {
  if (hay.includes(tok)) return true;
  if (tok.length >= 4 && (tok.endsWith("s") || tok.endsWith("x"))) {
    if (hay.includes(tok.slice(0, -1))) return true;
  }
  if (tok.length >= 6 && tok.endsWith("ie")) {
    if (hay.includes(`${tok.slice(0, -2)}ique`)) return true;
  }
  if (tok.length >= 8 && tok.endsWith("ique")) {
    if (hay.includes(`${tok.slice(0, -4)}ie`)) return true;
  }
  return false;
}

const GRADE_DISPLAY = {
  "6eme": "6ème",
  "5eme": "5ème",
  "4eme": "4ème",
  "3eme": "3ème",
};

export function initSearch({ baseUrl }) {
  const input = document.getElementById("global-search-input");
  const resultsBox = document.getElementById("global-search-results");
  const statusBox = document.getElementById("global-search-status");
  if (!input || !resultsBox) return;

  let indexPromise = null;
  let cachedIndex = null;
  let statusTimer = null;

  async function ensureIndex() {
    if (cachedIndex) return cachedIndex;
    if (!indexPromise) {
      indexPromise = fetch(`${baseUrl}/search-index.json`, {
        headers: { Accept: "application/json" },
      })
        .then((resp) => (resp.ok ? resp.json() : []))
        .then((data) => {
          cachedIndex = Array.isArray(data) ? data : [];
          return cachedIndex;
        })
        .catch(() => {
          cachedIndex = [];
          return cachedIndex;
        });
    }
    return indexPromise;
  }

  function announceStatus(message) {
    if (!statusBox) return;
    window.clearTimeout(statusTimer);
    if (!message) {
      statusBox.textContent = "";
      return;
    }
    statusTimer = window.setTimeout(() => {
      statusBox.textContent = message;
    }, 200);
  }

  function closeResults() {
    resultsBox.hidden = true;
    announceStatus("");
  }

  function renderHits(queryNorm, entries) {
    resultsBox.replaceChildren();
    if (!queryNorm) {
      closeResults();
      return;
    }

    const rawTokens = queryNorm.split(" ").filter(Boolean);
    const multiFiltered = rawTokens.filter((t) => t.length >= 2);
    const tokens = multiFiltered.length > 0 ? multiFiltered : rawTokens;
    const matches = entries
      .filter((entry) => {
        const hay = String(entry.concepts_text_normalized || "");
        return tokens.every((tok) => matchesSearchToken(hay, tok));
      })
      .slice(0, 12);

    if (matches.length === 0) {
      const emptyItem = document.createElement("li");
      emptyItem.className = "search-empty";
      emptyItem.textContent = "Aucun thème trouvé pour cette recherche.";
      resultsBox.appendChild(emptyItem);
      announceStatus("Aucun thème trouvé pour cette recherche.");
    } else {
      for (const hit of matches) {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.className = "search-hit";
        // Préfixage unique `${baseUrl}${hit.url}` (`hit.url` est stocké sous la forme `/cycle-4/.../`)
        link.href = `${baseUrl}${hit.url}`;

        const titleSpan = document.createElement("span");
        titleSpan.className = "search-hit-title";
        titleSpan.textContent = String(hit.title || "");

        const grades = Array.isArray(hit.reperes_levels)
          ? hit.reperes_levels.map((g) => GRADE_DISPLAY[g] || g).join(", ")
          : "";
        const metaSpan = document.createElement("span");
        metaSpan.className = "search-hit-meta";
        metaSpan.textContent = `${hit.subject_label || hit.subject} · ${grades}`;

        link.append(titleSpan, metaSpan);
        item.appendChild(link);
        resultsBox.appendChild(item);
      }
      announceStatus(
        matches.length === 1 ? "1 thème trouvé." : `${matches.length} thèmes trouvés.`
      );
    }

    resultsBox.hidden = false;
  }

  input.addEventListener("focus", () => {
    ensureIndex();
  });

  input.addEventListener("input", async () => {
    const q = normalizeSearchQuery(input.value);
    if (!q) {
      closeResults();
      return;
    }
    const entries = await ensureIndex();
    renderHits(q, entries);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeResults();
    } else if (event.key === "ArrowDown" && !resultsBox.hidden) {
      const firstHit = resultsBox.querySelector("a.search-hit");
      if (firstHit) {
        event.preventDefault();
        firstHit.focus();
      }
    }
  });

  resultsBox.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeResults();
      input.focus();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const links = Array.from(resultsBox.querySelectorAll("a.search-hit"));
    const idx = links.indexOf(document.activeElement);
    if (idx < 0) return;
    event.preventDefault();
    if (event.key === "ArrowUp" && idx === 0) {
      input.focus();
    } else {
      const nextIdx = event.key === "ArrowDown" ? (idx + 1) % links.length : idx - 1;
      links[nextIdx].focus();
    }
  });

  document.addEventListener("click", (event) => {
    if (!resultsBox.hidden && !input.contains(event.target) && !resultsBox.contains(event.target)) {
      closeResults();
    }
  });
}
