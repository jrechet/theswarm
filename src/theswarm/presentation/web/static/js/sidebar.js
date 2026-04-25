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
})();
