// Application précoce du thème clair/sombre avant le rendu (sans script en ligne, conforme CSP script-src 'self')
try {
  const stored = window.localStorage.getItem("osarai:v1:theme");
  if (stored === "light" || stored === "dark") {
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) {
      meta.content = stored;
    }
  }
} catch {
  // Stockage local indisponible : suivi automatique de la préférence système ("light dark")
}
