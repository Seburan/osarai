// Îlot interactif de Quiz QCM (4 choix, schémas masqués, explication immédiate et relance d'erreurs)

import { isItemQuarantined } from "./feedback.js";
import { buildAssetFigure } from "./flashcards.js";

const GRADE_ORDER = { "6eme": 0, "5eme": 1, "4eme": 2, "3eme": 3 };
const GRADE_LABELS = { "6eme": "6ème", "5eme": "5ème", "4eme": "4ème", "3eme": "3ème" };

export function initQuiz({
  themeData,
  getGrade,
  readThemeProgress,
  writeThemeProgress,
  renderMath,
  openFlagModal,
  requestPersist,
}) {
  const stage = document.getElementById("quiz-stage");
  const progressLabel = document.getElementById("quiz-progress-label");
  const allLevelsWrap = document.getElementById("quiz-all-levels-wrap");
  const allLevelsToggle = document.getElementById("quiz-all-levels-toggle");
  const gradeBanner = document.getElementById("quiz-grade-banner");

  if (!stage || !themeData || !Array.isArray(themeData.quiz)) return;

  let includeAllLevels = false;
  let retryMissedOnly = false;
  let missedIdsSnapshot = [];
  let qIndex = 0;
  let selectedChoice = null;
  let score = 0;
  let sessionMissedIds = [];

  function getPool() {
    const grade = getGrade();
    const maxOrder = GRADE_ORDER[grade] ?? 1;
    const available = themeData.quiz.filter(
      (q) => !isItemQuarantined(q.item_id, q.content_hash)
    );

    const higherCount = available.filter(
      (q) => (GRADE_ORDER[q.reperes_level] ?? 1) > maxOrder
    ).length;

    if (allLevelsWrap) {
      allLevelsWrap.hidden = higherCount === 0;
    }
    if (gradeBanner) {
      if (higherCount > 0 && !includeAllLevels) {
        gradeBanner.hidden = false;
        gradeBanner.textContent =
          `QCM filtré cumulativement jusqu'en ${GRADE_LABELS[grade] || grade} ` +
          `(${higherCount} question(s) de niveau supérieur masquée(s)).`;
      } else {
        gradeBanner.hidden = true;
      }
    }

    const gradePool = includeAllLevels
      ? available
      : available.filter((q) => (GRADE_ORDER[q.reperes_level] ?? 1) <= maxOrder);

    if (retryMissedOnly && missedIdsSnapshot.length > 0) {
      const missedSet = new Set(missedIdsSnapshot);
      return gradePool.filter((q) => missedSet.has(q.item_id));
    }
    return gradePool;
  }

  function resetSession(onlyMissed = false) {
    retryMissedOnly = onlyMissed;
    qIndex = 0;
    selectedChoice = null;
    score = 0;
    sessionMissedIds = [];
    render();
  }

  function saveCompletedQuiz(totalCount) {
    const progress = readThemeProgress();
    const prevBest = progress.quiz?.best_score ?? 0;
    progress.quiz = {
      best_score: retryMissedOnly ? prevBest : Math.max(prevBest, score),
      total: retryMissedOnly ? progress.quiz?.total || totalCount : totalCount,
      missed_ids: [...sessionMissedIds],
      updated_at: new Date().toISOString(),
    };
    writeThemeProgress(progress);
    if (typeof requestPersist === "function") {
      requestPersist();
    }
  }

  function renderSummaryScreen(totalCount) {
    saveCompletedQuiz(totalCount);
    stage.replaceChildren();
    if (progressLabel) {
      progressLabel.textContent = `Séance terminée : ${score} / ${totalCount}`;
    }

    const box = document.createElement("div");
    box.className = "quiz-box";

    const heading = document.createElement("h3");
    heading.textContent = `Résultat : ${score} bonne(s) réponse(s) sur ${totalCount}`;
    box.appendChild(heading);

    const sub = document.createElement("p");
    sub.textContent =
      sessionMissedIds.length === 0
        ? "Bravo ! Toutes les questions de cette série ont été réussies."
        : `Il reste ${sessionMissedIds.length} question(s) à consolider.`;
    box.appendChild(sub);

    const actions = document.createElement("div");
    actions.className = "study-actions-group";

    if (sessionMissedIds.length > 0) {
      const retryBtn = document.createElement("button");
      retryBtn.type = "button";
      retryBtn.className = "btn btn-amber";
      retryBtn.textContent = `Relancer mes erreurs (${sessionMissedIds.length})`;
      retryBtn.addEventListener("click", () => {
        missedIdsSnapshot = [...sessionMissedIds];
        resetSession(true);
      });
      actions.appendChild(retryBtn);
    }

    const restartBtn = document.createElement("button");
    restartBtn.type = "button";
    restartBtn.className = "btn btn-primary";
    restartBtn.textContent = "Recommencer tout le QCM";
    restartBtn.addEventListener("click", () => {
      missedIdsSnapshot = [];
      resetSession(false);
    });
    actions.appendChild(restartBtn);

    box.appendChild(actions);
    stage.appendChild(box);
  }

  function render() {
    const pool = getPool();
    stage.replaceChildren();

    if (pool.length === 0) {
      if (progressLabel) progressLabel.textContent = "";
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "Aucune question QCM disponible pour ce niveau.";
      stage.appendChild(empty);
      return;
    }

    if (qIndex >= pool.length) {
      renderSummaryScreen(pool.length);
      return;
    }

    const q = pool[qIndex];
    const answered = selectedChoice !== null;
    if (progressLabel) {
      const best = readThemeProgress().quiz;
      const bestSuffix = best ? ` · Meilleur score : ${best.best_score}/${best.total}` : "";
      progressLabel.textContent = `Question ${qIndex + 1} / ${pool.length}${bestSuffix}`;
    }

    const box = document.createElement("div");
    box.className = "quiz-box";

    const metaBar = document.createElement("div");
    metaBar.className = "study-meta-bar";
    const diffSpan = document.createElement("span");
    diffSpan.textContent =
      `Difficulté : ${q.difficulty} · ${GRADE_LABELS[q.reperes_level] || q.reperes_level}`;
    const scoreSpan = document.createElement("span");
    scoreSpan.textContent = `Score en cours : ${score}`;
    metaBar.append(diffSpan, scoreSpan);
    box.appendChild(metaBar);

    const asset = q.asset_id ? themeData.assets?.[q.asset_id] : null;
    if (asset && q.asset_role === "front_occluded") {
      const { figure } = buildAssetFigure(asset, "front_occluded", q.occlusions, answered);
      box.appendChild(figure);
    }

    const promptDiv = document.createElement("div");
    promptDiv.className = "quiz-prompt";
    promptDiv.innerHTML = q.question_html;
    box.appendChild(promptDiv);

    const choicesGrid = document.createElement("div");
    choicesGrid.className = "choices-grid";

    q.choices_html.forEach((choiceHtml, idx) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "choice-btn";
      btn.disabled = answered;
      if (answered) {
        if (idx === q.answer_index) {
          btn.classList.add("is-correct");
        } else if (idx === selectedChoice) {
          btn.classList.add("is-wrong");
        }
      }
      btn.innerHTML = choiceHtml;
      btn.addEventListener("click", () => {
        if (selectedChoice !== null) return;
        selectedChoice = idx;
        if (idx === q.answer_index) {
          score += 1;
        } else if (!sessionMissedIds.includes(q.item_id)) {
          sessionMissedIds.push(q.item_id);
        }
        render();
      });
      choicesGrid.appendChild(btn);
    });
    box.appendChild(choicesGrid);

    if (answered) {
      const expDiv = document.createElement("div");
      expDiv.className = "quiz-explanation";
      expDiv.innerHTML = q.explanation_html;
      box.appendChild(expDiv);

      if (asset && q.asset_role === "explanation_reference") {
        const { figure } = buildAssetFigure(asset, "explanation_reference", [], true);
        box.appendChild(figure);
      }
    }

    const actionsRow = document.createElement("div");
    actionsRow.className = "study-actions-row";

    const leftActions = document.createElement("div");
    leftActions.className = "study-actions-group";
    if (answered) {
      const nextBtn = document.createElement("button");
      nextBtn.type = "button";
      nextBtn.className = "btn btn-primary";
      nextBtn.textContent =
        qIndex + 1 < pool.length ? "Question suivante →" : "Voir mon score final";
      nextBtn.addEventListener("click", () => {
        selectedChoice = null;
        qIndex += 1;
        render();
      });
      leftActions.appendChild(nextBtn);
    }

    const flagBtn = document.createElement("button");
    flagBtn.type = "button";
    flagBtn.className = "btn btn-outline";
    flagBtn.textContent = "Signaler une erreur";
    flagBtn.addEventListener("click", () => {
      openFlagModal({
        cycle: themeData.cycle,
        subject: themeData.subject,
        theme_slug: themeData.theme_slug,
        item_id: q.item_id,
        item_type: "quiz",
        content_hash: q.content_hash,
        build_sha: themeData.build_sha,
      });
    });

    actionsRow.append(leftActions, flagBtn);
    box.appendChild(actionsRow);

    stage.appendChild(box);
    renderMath(box);
  }

  if (allLevelsToggle) {
    allLevelsToggle.addEventListener("change", () => {
      includeAllLevels = Boolean(allLevelsToggle.checked);
      resetSession(false);
    });
  }

  window.addEventListener("osarai:grade-changed", () => {
    resetSession(false);
  });

  window.addEventListener("osarai:flags-changed", () => {
    selectedChoice = null;
    render();
  });

  render();
}
