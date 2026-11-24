// Îlot de révision des cartes mémoire (`basic`, `cloze` dépliées et schémas occultés)

import { isItemQuarantined } from "./feedback.js";

const GRADE_ORDER = { "6eme": 0, "5eme": 1, "4eme": 2, "3eme": 3 };
const GRADE_LABELS = { "6eme": "6ème", "5eme": "5ème", "4eme": "4ème", "3eme": "3ème" };

export function buildAssetFigure(asset, role, occlusions, isRevealed) {
  const figure = document.createElement("figure");
  figure.className = "study-figure";

  const stage = document.createElement("div");
  stage.className = "asset-stage";

  const container = document.createElement("div");
  container.className = "asset-container" + (isRevealed ? " is-revealed" : "");
  container.style.setProperty("--asset-w", String(asset.width));
  container.style.setProperty("--asset-h", String(asset.height));

  const img = document.createElement("img");
  img.src = `assets/${asset.filename}`;
  img.width = Number(asset.width);
  img.height = Number(asset.height);
  img.alt =
    role === "front_occluded" && !isRevealed
      ? "Illustration pédagogique à légender"
      : String(asset.title || "Illustration pédagogique");
  container.appendChild(img);

  if (role === "front_occluded" && Array.isArray(occlusions)) {
    for (const box of occlusions) {
      const boxEl = document.createElement("div");
      const boxRole = box.role === "target" ? "target" : "mask";
      boxEl.className = `occlusion-box occlusion-box--${boxRole}`;
      boxEl.style.left = `${box.x}%`;
      boxEl.style.top = `${box.y}%`;
      boxEl.style.width = `${box.w}%`;
      boxEl.style.height = `${box.h}%`;
      if (box.badge) {
        const span = document.createElement("span");
        span.textContent = String(box.badge);
        boxEl.appendChild(span);
      }
      container.appendChild(boxEl);
    }
  }

  const zoomBtn = document.createElement("button");
  zoomBtn.type = "button";
  zoomBtn.className = "btn-zoom-asset";
  zoomBtn.textContent = "Agrandir le schéma";
  zoomBtn.setAttribute("aria-label", "Agrandir le schéma en plein écran");

  stage.append(container, zoomBtn);
  figure.appendChild(stage);

  const details = document.createElement("details");
  details.className = "tasl-details";
  if (isRevealed || role !== "front_occluded") {
    details.open = true;
  }

  const summary = document.createElement("summary");
  summary.textContent = "Crédit de l'illustration (TASL)";

  const creditP = document.createElement("p");
  const titleStrong = document.createElement("strong");
  titleStrong.textContent = String(asset.title || asset.commons_title || "Illustration");

  const authorText = document.createTextNode(` — Auteur : ${asset.author || "Wikimedia"} · `);

  const srcLink = document.createElement("a");
  srcLink.href = String(asset.source_url || "#");
  srcLink.target = "_blank";
  srcLink.rel = "noopener noreferrer";
  srcLink.textContent = "Source Wikimedia";

  const sepText = document.createTextNode(" · Licence ");

  const licLink = document.createElement("a");
  licLink.href = String(asset.license_url || "#");
  licLink.target = "_blank";
  licLink.rel = "noopener noreferrer";
  licLink.textContent = String(asset.license_spdx || "");

  const modText = document.createTextNode(` (${asset.modifications_note || ""})`);

  creditP.append(titleStrong, authorText, srcLink, sepText, licLink, modText);
  details.append(summary, creditP);
  figure.appendChild(details);

  return { figure, container, details, img };
}

export function initFlashcards({
  themeData,
  getGrade,
  readThemeProgress,
  writeThemeProgress,
  renderMath,
  openFlagModal,
  requestPersist,
}) {
  const stage = document.getElementById("flashcards-stage");
  if (!stage || !themeData || !Array.isArray(themeData.flashcards)) return;

  const filterButtons = Array.from(document.querySelectorAll("[data-card-filter]"));
  const reviewCountEl = document.getElementById("review-only-count");
  const allLevelsWrap = document.getElementById("cards-all-levels-wrap");
  const allLevelsToggle = document.getElementById("cards-all-levels-toggle");
  const gradeBanner = document.getElementById("cards-grade-banner");

  let activeFilter = "all";
  let includeAllLevels = false;
  let currentIndex = 0;
  let isRevealed = false;

  function getDeck() {
    const grade = getGrade();
    const maxOrder = GRADE_ORDER[grade] ?? 1;
    const progress = readThemeProgress();
    const cardStates = progress.cards || {};

    const nonQuarantined = themeData.flashcards.filter(
      (c) => !isItemQuarantined(c.item_id, c.content_hash)
    );

    const higherCount = nonQuarantined.filter(
      (c) => (GRADE_ORDER[c.reperes_level] ?? 1) > maxOrder
    ).length;

    if (allLevelsWrap) {
      allLevelsWrap.hidden = higherCount === 0;
    }
    if (gradeBanner) {
      if (higherCount > 0 && !includeAllLevels) {
        gradeBanner.hidden = false;
        gradeBanner.textContent =
          `Pile filtrée cumulativement jusqu'à la classe de ${GRADE_LABELS[grade] || grade} ` +
          `(${higherCount} carte(s) de niveau supérieur masquée(s)).`;
      } else {
        gradeBanner.hidden = true;
      }
    }

    const gradeFiltered = includeAllLevels
      ? nonQuarantined
      : nonQuarantined.filter((c) => (GRADE_ORDER[c.reperes_level] ?? 1) <= maxOrder);

    const reviewTotal = gradeFiltered.filter(
      (c) => cardStates[c.item_id] && cardStates[c.item_id].state === "a_revoir"
    ).length;
    if (reviewCountEl) {
      reviewCountEl.textContent = `(${reviewTotal})`;
    }

    if (activeFilter === "essentiel") {
      return gradeFiltered.filter((c) => c.priority === "essentiel");
    }
    if (activeFilter === "a_revoir") {
      return gradeFiltered.filter(
        (c) => cardStates[c.item_id] && cardStates[c.item_id].state === "a_revoir"
      );
    }
    return gradeFiltered;
  }

  function markCardState(itemId, state) {
    const progress = readThemeProgress();
    if (!progress.cards || typeof progress.cards !== "object") {
      progress.cards = {};
    }
    progress.cards[itemId] = {
      state,
      updated_at: new Date().toISOString(),
    };
    writeThemeProgress(progress);
    if (typeof requestPersist === "function") {
      requestPersist();
    }
  }

  function render() {
    const deck = getDeck();
    stage.replaceChildren();

    if (deck.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent =
        activeFilter === "a_revoir"
          ? "Aucune carte marquée « À revoir » dans cette sélection."
          : "Aucune carte mémoire active pour ce filtre ou ce niveau.";
      stage.appendChild(empty);
      return;
    }

    if (currentIndex >= deck.length) {
      currentIndex = 0;
    }
    const card = deck[currentIndex];
    const progress = readThemeProgress();
    const savedState = progress.cards?.[card.item_id]?.state || null;

    const box = document.createElement("div");
    box.className = "flashcard-box";

    const metaBar = document.createElement("div");
    metaBar.className = "study-meta-bar";

    const posSpan = document.createElement("span");
    posSpan.textContent =
      `Carte ${currentIndex + 1} / ${deck.length} · ` +
      `${GRADE_LABELS[card.reperes_level] || card.reperes_level} · ` +
      (card.priority === "essentiel" ? "Essentiel" : "Approfondissement");

    const statusSpan = document.createElement("span");
    statusSpan.textContent =
      savedState === "a_revoir"
        ? "Statut : À revoir"
        : savedState === "connu"
          ? "Statut : Connu"
          : "Non évaluée";

    metaBar.append(posSpan, statusSpan);
    box.appendChild(metaBar);

    const asset = card.asset_id ? themeData.assets?.[card.asset_id] : null;
    if (asset && card.asset_role === "front_occluded") {
      const { figure } = buildAssetFigure(asset, "front_occluded", card.occlusions, isRevealed);
      box.appendChild(figure);
    }

    const promptDiv = document.createElement("div");
    promptDiv.className = "card-prompt";
    // Contenu pré-rendu au build par markdown-it-py (html=False) et validé hors-ligne
    promptDiv.innerHTML = isRevealed && card.type === "cloze" ? card.back_html : card.front_html;
    box.appendChild(promptDiv);

    if (isRevealed) {
      const answerPanel = document.createElement("div");
      answerPanel.className = "card-answer-panel";

      if (card.type === "basic") {
        const ansBody = document.createElement("div");
        ansBody.className = "card-answer-body";
        ansBody.innerHTML = card.back_html;
        answerPanel.appendChild(ansBody);
      }

      if (asset && card.asset_role === "back_reference") {
        const { figure } = buildAssetFigure(asset, "back_reference", [], true);
        answerPanel.appendChild(figure);
      }

      if (card.explanation_html) {
        const expDiv = document.createElement("div");
        expDiv.className = "card-explanation";
        expDiv.innerHTML = card.explanation_html;
        answerPanel.appendChild(expDiv);
      }

      box.appendChild(answerPanel);
    }

    const actionsRow = document.createElement("div");
    actionsRow.className = "study-actions-row";

    const mainGroup = document.createElement("div");
    mainGroup.className = "study-actions-group";

    if (!isRevealed) {
      const revealBtn = document.createElement("button");
      revealBtn.type = "button";
      revealBtn.className = "btn btn-primary";
      revealBtn.textContent = "Voir la réponse";
      revealBtn.addEventListener("click", () => {
        isRevealed = true;
        render();
      });
      mainGroup.appendChild(revealBtn);
    } else {
      const reviewBtn = document.createElement("button");
      reviewBtn.type = "button";
      reviewBtn.className = "btn btn-amber";
      reviewBtn.textContent = "À revoir";
      reviewBtn.addEventListener("click", () => {
        markCardState(card.item_id, "a_revoir");
        isRevealed = false;
        currentIndex = (currentIndex + 1) % Math.max(1, getDeck().length);
        render();
      });

      const knownBtn = document.createElement("button");
      knownBtn.type = "button";
      knownBtn.className = "btn btn-success";
      knownBtn.textContent = "Je connais";
      knownBtn.addEventListener("click", () => {
        markCardState(card.item_id, "connu");
        isRevealed = false;
        const nextDeck = getDeck();
        currentIndex = nextDeck.length ? (currentIndex + 1) % nextDeck.length : 0;
        render();
      });

      mainGroup.append(reviewBtn, knownBtn);
    }

    const navGroup = document.createElement("div");
    navGroup.className = "study-actions-group";

    const prevBtn = document.createElement("button");
    prevBtn.type = "button";
    prevBtn.className = "btn btn-subtle";
    prevBtn.textContent = "← Précédente";
    prevBtn.disabled = deck.length <= 1;
    prevBtn.addEventListener("click", () => {
      isRevealed = false;
      currentIndex = (currentIndex - 1 + deck.length) % deck.length;
      render();
    });

    const nextBtn = document.createElement("button");
    nextBtn.type = "button";
    nextBtn.className = "btn btn-subtle";
    nextBtn.textContent = "Suivante →";
    nextBtn.disabled = deck.length <= 1;
    nextBtn.addEventListener("click", () => {
      isRevealed = false;
      currentIndex = (currentIndex + 1) % deck.length;
      render();
    });

    const flagBtn = document.createElement("button");
    flagBtn.type = "button";
    flagBtn.className = "btn btn-outline";
    flagBtn.textContent = "Signaler une erreur";
    flagBtn.addEventListener("click", () => {
      openFlagModal({
        cycle: themeData.cycle,
        subject: themeData.subject,
        theme_slug: themeData.theme_slug,
        item_id: card.item_id,
        item_type: "flashcard",
        content_hash: card.content_hash,
        build_sha: themeData.build_sha,
      });
    });

    navGroup.append(prevBtn, nextBtn, flagBtn);
    actionsRow.append(mainGroup, navGroup);
    box.appendChild(actionsRow);

    stage.appendChild(box);
    renderMath(box);
  }

  for (const btn of filterButtons) {
    btn.addEventListener("click", () => {
      activeFilter = btn.dataset.cardFilter || "all";
      for (const b of filterButtons) {
        b.classList.toggle("is-active", b === btn);
      }
      currentIndex = 0;
      isRevealed = false;
      render();
    });
  }

  if (allLevelsToggle) {
    allLevelsToggle.addEventListener("change", () => {
      includeAllLevels = Boolean(allLevelsToggle.checked);
      currentIndex = 0;
      isRevealed = false;
      render();
    });
  }

  window.addEventListener("osarai:grade-changed", () => {
    currentIndex = 0;
    isRevealed = false;
    render();
  });

  window.addEventListener("osarai:flags-changed", () => {
    isRevealed = false;
    render();
  });

  render();
}
