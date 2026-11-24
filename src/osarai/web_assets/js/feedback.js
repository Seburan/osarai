// Îlot de quarantaine locale et d'export de signalements (`osarai:v1:flags` / `osarai-feedback-v1`)

export const FLAGS_STORAGE_KEY = "osarai:v1:flags";
const MAX_GITHUB_ISSUE_URI_LENGTH = 5500;

const VALID_REASONS = new Set([
  "erreur_factuelle",
  "hors_programme",
  "formulation_ambigue",
  "masque_decale",
  "coquille",
  "autre",
]);

export function readFlags() {
  try {
    const raw = window.localStorage.getItem(FLAGS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function writeFlags(flags) {
  try {
    window.localStorage.setItem(FLAGS_STORAGE_KEY, JSON.stringify(flags));
  } catch {
    // Stockage plein ou navigation privée stricte
  }
  window.dispatchEvent(new CustomEvent("osarai:flags-changed"));
}

export function isItemQuarantined(itemId, contentHash) {
  const flags = readFlags();
  return flags.some(
    (entry) =>
      entry &&
      entry.status === "open" &&
      entry.item_id === itemId &&
      entry.content_hash === contentHash
  );
}

export function reconcileFlagsWithTheme(themeData) {
  if (!themeData) return;
  const flags = readFlags();
  if (!flags.length) return;

  const retiredSet = new Set(Array.isArray(themeData.retired_ids) ? themeData.retired_ids : []);
  const activeHashes = new Map();
  for (const card of themeData.flashcards || []) {
    activeHashes.set(card.item_id, card.content_hash);
  }
  for (const q of themeData.quiz || []) {
    activeHashes.set(q.item_id, q.content_hash);
  }

  let mutated = false;
  for (const entry of flags) {
    if (
      !entry ||
      entry.status !== "open" ||
      entry.cycle !== themeData.cycle ||
      entry.subject !== themeData.subject ||
      entry.theme_slug !== themeData.theme_slug
    ) {
      continue;
    }
    const parentId = String(entry.item_id || "").split("#")[0];
    if (retiredSet.has(parentId) || !activeHashes.has(entry.item_id)) {
      entry.status = "retired";
      mutated = true;
    } else if (activeHashes.get(entry.item_id) !== entry.content_hash) {
      entry.status = "resolved";
      mutated = true;
    }
  }

  if (mutated) {
    writeFlags(flags);
  }
}

export function buildFeedbackFenceBlock(openItems) {
  const payload = {
    schema: "osarai-feedback-v1",
    exported_at: new Date().toISOString(),
    items: openItems,
  };
  return "```osarai-feedback-v1\n" + JSON.stringify(payload, null, 2) + "\n```";
}

async function copyTextSafe(text) {
  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    await navigator.clipboard.writeText(text);
    return true;
  }
  return false;
}

export function initFeedbackUI({ repoUrl, requestPersist }) {
  const drawer = document.getElementById("feedback-drawer");
  const openDrawerBtn = document.getElementById("btn-open-feedback-drawer");
  const countBadge = document.getElementById("feedback-count-badge");
  const listEl = document.getElementById("feedback-drawer-list");
  const statusEl = document.getElementById("feedback-drawer-status");
  const shareBtn = document.getElementById("btn-share-feedback");
  const issueBtn = document.getElementById("btn-github-issue-feedback");
  const clearBtn = document.getElementById("btn-clear-feedback");
  const confirmBar = document.getElementById("feedback-clear-confirm");
  const confirmClearBtn = document.getElementById("btn-confirm-clear-feedback");
  const cancelClearBtn = document.getElementById("btn-cancel-clear-feedback");

  const flagDialog = document.getElementById("flag-item-dialog");
  const flagTargetIdEl = document.getElementById("flag-target-id");
  const flagReasonSelect = document.getElementById("flag-reason-select");
  const flagNoteInput = document.getElementById("flag-note-input");
  const submitFlagBtn = document.getElementById("btn-submit-flag");

  let pendingTarget = null;

  function renderBadgeAndDrawer() {
    const allFlags = readFlags();
    const openFlags = allFlags.filter((f) => f && f.status === "open");

    if (countBadge) {
      countBadge.textContent = String(openFlags.length);
      countBadge.hidden = openFlags.length === 0;
    }

    if (!listEl) return;
    listEl.replaceChildren();

    if (openFlags.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "Aucun signalement actif en attente d'envoi.";
      listEl.appendChild(empty);
      if (shareBtn) shareBtn.disabled = true;
      if (issueBtn) issueBtn.disabled = true;
      if (clearBtn) clearBtn.disabled = allFlags.length === 0;
      return;
    }

    if (shareBtn) shareBtn.disabled = false;
    if (issueBtn) issueBtn.disabled = false;
    if (clearBtn) clearBtn.disabled = false;

    for (const item of openFlags) {
      const card = document.createElement("div");
      card.className = "feedback-entry";

      const head = document.createElement("div");
      head.className = "feedback-entry-head";

      const idSpan = document.createElement("code");
      idSpan.textContent = String(item.item_id || "");

      const reasonSpan = document.createElement("span");
      reasonSpan.textContent = String(item.reason || "autre");

      head.append(idSpan, reasonSpan);
      card.appendChild(head);

      if (item.note) {
        const noteP = document.createElement("p");
        noteP.className = "feedback-entry-note";
        noteP.textContent = String(item.note);
        card.appendChild(noteP);
      }

      listEl.appendChild(card);
    }
  }

  function openFlagModal(itemMeta) {
    if (!flagDialog || !itemMeta) return;
    pendingTarget = itemMeta;
    if (flagTargetIdEl) flagTargetIdEl.textContent = itemMeta.item_id;
    if (flagReasonSelect) flagReasonSelect.value = "formulation_ambigue";
    if (flagNoteInput) flagNoteInput.value = "";
    if (typeof flagDialog.showModal === "function") {
      flagDialog.showModal();
    } else {
      flagDialog.setAttribute("open", "");
    }
  }

  if (submitFlagBtn) {
    submitFlagBtn.addEventListener("click", () => {
      if (!pendingTarget) return;
      const rawReason = flagReasonSelect ? flagReasonSelect.value : "autre";
      const reason = VALID_REASONS.has(rawReason) ? rawReason : "autre";
      const note = flagNoteInput ? flagNoteInput.value.trim().slice(0, 300) : "";

      const flags = readFlags();
      const existingIdx = flags.findIndex(
        (f) =>
          f &&
          f.item_id === pendingTarget.item_id &&
          f.content_hash === pendingTarget.content_hash
      );
      const record = {
        cycle: pendingTarget.cycle,
        subject: pendingTarget.subject,
        theme_slug: pendingTarget.theme_slug,
        item_id: pendingTarget.item_id,
        item_type: pendingTarget.item_type,
        content_hash: pendingTarget.content_hash,
        build_sha: pendingTarget.build_sha || "dev",
        reason,
        note,
        status: "open",
        flagged_at: new Date().toISOString(),
      };

      if (existingIdx >= 0) {
        flags[existingIdx] = record;
      } else {
        flags.push(record);
      }
      writeFlags(flags);
      if (typeof requestPersist === "function") {
        requestPersist();
      }
      pendingTarget = null;
      if (flagDialog && typeof flagDialog.close === "function") {
        flagDialog.close();
      } else if (flagDialog) {
        flagDialog.removeAttribute("open");
      }
    });
  }

  if (openDrawerBtn && drawer) {
    openDrawerBtn.addEventListener("click", () => {
      if (statusEl) statusEl.textContent = "";
      if (confirmBar) confirmBar.hidden = true;
      renderBadgeAndDrawer();
      if (typeof drawer.showModal === "function") {
        drawer.showModal();
      } else {
        drawer.setAttribute("open", "");
      }
    });
  }

  if (shareBtn) {
    shareBtn.addEventListener("click", async () => {
      const openFlags = readFlags().filter((f) => f && f.status === "open");
      if (!openFlags.length) return;
      const block = buildFeedbackFenceBlock(openFlags);
      try {
        if (typeof navigator.share === "function") {
          await navigator.share({
            title: `Signalement Osarai (${openFlags.length})`,
            text: block,
          });
          if (statusEl) statusEl.textContent = "Signalement partagé avec succès.";
          return;
        }
      } catch {
        // Repli automatique sur le presse-papiers si le partage natif est annulé
      }
      try {
        const copied = await copyTextSafe(block);
        if (statusEl) {
          statusEl.textContent = copied
            ? "Bloc osarai-feedback-v1 copié dans le presse-papiers."
            : "Impossible d'accéder au presse-papiers sur ce navigateur.";
        }
      } catch {
        if (statusEl) statusEl.textContent = "Échec de la copie dans le presse-papiers.";
      }
    });
  }

  if (issueBtn) {
    issueBtn.addEventListener("click", async () => {
      const openFlags = readFlags().filter((f) => f && f.status === "open");
      if (!openFlags.length) return;
      const cleanRepo = (repoUrl || "https://github.com/Seburan/osarai").replace(/\/+$/, "");
      const block = buildFeedbackFenceBlock(openFlags);
      const idsSummary = openFlags.map((f) => f.item_id).join(", ");
      const title = `[Signalement] ${idsSummary}`.slice(0, 120);
      const fullBody = `Bonjour,\n\nVoici un signalement généré depuis le portail Osarai :\n\n${block}\n`;
      const candidateUrl = `${cleanRepo}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(fullBody)}`;

      if (candidateUrl.length <= MAX_GITHUB_ISSUE_URI_LENGTH) {
        window.open(candidateUrl, "_blank", "noopener,noreferrer");
        return;
      }

      // Plafond <= 5 500 octets encodés : copier le bloc complet et ouvrir une URL courte
      await copyTextSafe(block).catch(() => false);
      const shortBody =
        `Éléments concernés : ${idsSummary.slice(0, 800)}\n\n` +
        `*(Le bloc complet \`osarai-feedback-v1\` a été copié dans votre presse-papiers : collez-le ci-dessous).*`;
      const shortUrl = `${cleanRepo}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(shortBody)}`.slice(
        0,
        MAX_GITHUB_ISSUE_URI_LENGTH
      );
      if (statusEl) {
        statusEl.textContent =
          "Rapport volumineux : bloc copié dans le presse-papiers avant ouverture de GitHub.";
      }
      window.open(shortUrl, "_blank", "noopener,noreferrer");
    });
  }

  if (clearBtn && confirmBar) {
    clearBtn.addEventListener("click", () => {
      confirmBar.hidden = false;
    });
  }
  if (cancelClearBtn && confirmBar) {
    cancelClearBtn.addEventListener("click", () => {
      confirmBar.hidden = true;
    });
  }
  if (confirmClearBtn && confirmBar) {
    confirmClearBtn.addEventListener("click", () => {
      writeFlags([]);
      confirmBar.hidden = true;
      if (statusEl) statusEl.textContent = "Liste des signalements locaux vidée.";
      renderBadgeAndDrawer();
    });
  }

  window.addEventListener("osarai:flags-changed", renderBadgeAndDrawer);
  renderBadgeAndDrawer();

  return { openFlagModal };
}
