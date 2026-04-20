// Sprint E M1 — memory viewer client-side search + pagination (50/page).
(function () {
  var list = document.querySelector('[data-testid="memory-list"]');
  if (!list) return;

  var pageSize = parseInt(list.getAttribute('data-page-size') || '50', 10);
  var search = document.querySelector('[data-testid="memory-search"]');
  var visibleEl = document.querySelector('[data-memory-visible]');
  var prevBtn = document.querySelector('[data-memory-prev]');
  var nextBtn = document.querySelector('[data-memory-next]');
  var pageEl = document.querySelector('[data-memory-page]');
  var pagesEl = document.querySelector('[data-memory-pages]');
  var items = Array.prototype.slice.call(list.querySelectorAll('[data-memory-item]'));
  var page = 0;
  var filter = '';

  function applyFilter() {
    var matches = items.filter(function (li) {
      if (!filter) return true;
      return (li.getAttribute('data-text') || '').indexOf(filter) !== -1;
    });
    var pages = Math.max(1, Math.ceil(matches.length / pageSize));
    if (page >= pages) page = pages - 1;
    if (page < 0) page = 0;
    var from = page * pageSize;
    var to = from + pageSize;

    items.forEach(function (li) { li.hidden = true; });
    matches.slice(from, to).forEach(function (li) { li.hidden = false; });

    if (visibleEl) visibleEl.textContent = matches.length;
    if (pageEl) pageEl.textContent = String(page + 1);
    if (pagesEl) pagesEl.textContent = String(pages);
    if (prevBtn) prevBtn.disabled = page === 0;
    if (nextBtn) nextBtn.disabled = page >= pages - 1;
  }

  if (search) {
    search.addEventListener('input', function () {
      filter = (search.value || '').toLowerCase().trim();
      page = 0;
      applyFilter();
    });
  }
  if (prevBtn) prevBtn.addEventListener('click', function () { page -= 1; applyFilter(); });
  if (nextBtn) nextBtn.addEventListener('click', function () { page += 1; applyFilter(); });

  applyFilter();
})();
