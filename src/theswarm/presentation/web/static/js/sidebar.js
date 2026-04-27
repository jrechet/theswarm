// Sidebar collapse + active-link highlighting.
(function () {
  const KEY = "theswarm.sidebar.collapsed";
  const sidebar = document.getElementById("sidebar");
  const toggle = document.getElementById("sidebar-toggle");
  if (!sidebar || !toggle) return;

  function apply(collapsed) {
    document.documentElement.dataset.sidebar = collapsed ? "collapsed" : "expanded";
    toggle.setAttribute("aria-expanded", String(!collapsed));
  }

  // Restore preference (default expanded on desktop, collapsed on narrow viewport).
  const stored = localStorage.getItem(KEY);
  const initial =
    stored === "1" ? true :
    stored === "0" ? false :
    window.matchMedia("(max-width: 900px)").matches;
  apply(initial);

  toggle.addEventListener("click", () => {
    const next = document.documentElement.dataset.sidebar !== "collapsed";
    apply(next);
    localStorage.setItem(KEY, next ? "1" : "0");
  });

  // Keyboard shortcut: backslash toggles.
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, [contenteditable]")) return;
    if (e.key === "\\") {
      const next = document.documentElement.dataset.sidebar !== "collapsed";
      apply(next);
      localStorage.setItem(KEY, next ? "1" : "0");
    }
  });

  // Highlight active link by longest prefix match.
  const here = window.location.pathname;
  const links = sidebar.querySelectorAll(".sidebar-nav a[href]");
  let bestMatch = null;
  let bestLen = -1;
  links.forEach((a) => {
    const url = new URL(a.href, window.location.origin);
    if (here === url.pathname) {
      if (url.pathname.length > bestLen) { bestMatch = a; bestLen = url.pathname.length; }
    } else if (url.pathname !== "/" && here.startsWith(url.pathname)) {
      if (url.pathname.length > bestLen) { bestMatch = a; bestLen = url.pathname.length; }
    }
  });
  if (bestMatch) bestMatch.setAttribute("aria-current", "page");

  // ── Resize handle ──────────────────────────────────────────────────
  // Drag the right edge of the sidebar to resize. Width persisted in
  // localStorage and applied via the --sidebar-width CSS variable.
  const handle = document.getElementById("sidebar-resize-handle");
  const WIDTH_KEY = "theswarm.sidebar.width";
  const root = document.documentElement;

  function readBound(name, fallback) {
    const v = parseInt(getComputedStyle(root).getPropertyValue(name), 10);
    return Number.isFinite(v) ? v : fallback;
  }
  const MIN_W = readBound("--sidebar-width-min", 220);
  const MAX_W = readBound("--sidebar-width-max", 380);

  function applyWidth(px) {
    const clamped = Math.max(MIN_W, Math.min(MAX_W, Math.round(px)));
    root.style.setProperty("--sidebar-width", clamped + "px");
    return clamped;
  }

  const storedWidth = parseInt(localStorage.getItem(WIDTH_KEY) || "", 10);
  if (Number.isFinite(storedWidth)) applyWidth(storedWidth);

  if (handle) {
    let dragging = false;
    let startX = 0;
    let startWidth = 0;

    handle.addEventListener("mousedown", (e) => {
      if (root.dataset.sidebar === "collapsed") return;
      dragging = true;
      startX = e.clientX;
      startWidth = sidebar.getBoundingClientRect().width;
      handle.classList.add("is-dragging");
      root.dataset.sidebarResizing = "1";
      e.preventDefault();
    });

    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      applyWidth(startWidth + (e.clientX - startX));
    });

    window.addEventListener("mouseup", () => {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove("is-dragging");
      delete root.dataset.sidebarResizing;
      const finalWidth = parseInt(getComputedStyle(root).getPropertyValue("--sidebar-width"), 10);
      if (Number.isFinite(finalWidth)) {
        localStorage.setItem(WIDTH_KEY, String(finalWidth));
      }
    });

    // Double-click resets to default.
    handle.addEventListener("dblclick", () => {
      root.style.removeProperty("--sidebar-width");
      localStorage.removeItem(WIDTH_KEY);
    });
  }
})();
