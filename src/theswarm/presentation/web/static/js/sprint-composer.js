// Sprint composer: free-form description → draft issues → confirm → create on GitHub.
(function () {
  var form = document.getElementById('sprint-form');
  if (!form) return;

  var status = document.getElementById('sprint-status');
  var preview = document.getElementById('sprint-preview');
  var previewList = document.getElementById('sprint-preview-list');
  var draftBtn = document.getElementById('sprint-draft-btn');
  var cancelBtn = document.getElementById('sprint-cancel-btn');
  var confirmBtn = document.getElementById('sprint-confirm-btn');
  var result = document.getElementById('sprint-result');
  var description = document.getElementById('sprint-description');

  var draftUrl = form.dataset.draftUrl;
  var createUrl = form.dataset.createUrl;
  var currentDraft = null;

  function setStatus(msg, kind) {
    status.textContent = msg || '';
    status.dataset.kind = kind || '';
  }

  function clearPreview() {
    preview.hidden = true;
    previewList.innerHTML = '';
    currentDraft = null;
  }

  function showPreview(draft) {
    currentDraft = draft;
    previewList.innerHTML = '';
    if (!draft.issues || !draft.issues.length) {
      var li = document.createElement('li');
      li.className = 'sprint-issue-empty';
      li.textContent = 'Claude returned no parseable issues. Try a more specific description.';
      previewList.appendChild(li);
      preview.hidden = false;
      return;
    }
    draft.issues.forEach(function (it, idx) {
      var li = document.createElement('li');
      li.className = 'sprint-issue';
      var title = document.createElement('div');
      title.className = 'sprint-issue-title';
      title.textContent = (idx + 1) + '. ' + it.title;
      var labels = document.createElement('div');
      labels.className = 'sprint-issue-labels';
      (it.labels || []).forEach(function (lbl) {
        var span = document.createElement('span');
        span.className = 'badge badge-subtle';
        span.textContent = lbl;
        labels.appendChild(span);
      });
      var body = document.createElement('details');
      body.className = 'sprint-issue-body';
      var summary = document.createElement('summary');
      summary.textContent = 'Body';
      body.appendChild(summary);
      var pre = document.createElement('pre');
      pre.textContent = it.body || '(empty)';
      body.appendChild(pre);
      li.appendChild(title);
      li.appendChild(labels);
      li.appendChild(body);
      previewList.appendChild(li);
    });
    preview.hidden = false;
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var text = (description.value || '').trim();
    if (!text) return;
    draftBtn.disabled = true;
    setStatus('Drafting…', 'loading');
    clearPreview();
    result.hidden = true;
    result.innerHTML = '';

    var body = new URLSearchParams();
    body.set('description', text);
    fetch(draftUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
      .then(function (draft) {
        showPreview(draft);
        setStatus('Drafted ' + (draft.issues || []).length + ' issue(s)', 'ok');
      })
      .catch(function (err) {
        setStatus('Failed to draft. Try again.', 'error');
        console.error(err);
      })
      .finally(function () { draftBtn.disabled = false; });
  });

  cancelBtn.addEventListener('click', function () {
    clearPreview();
    setStatus('', '');
  });

  confirmBtn.addEventListener('click', function () {
    if (!currentDraft || !currentDraft.issues.length) return;
    confirmBtn.disabled = true;
    cancelBtn.disabled = true;
    setStatus('Creating on GitHub…', 'loading');
    fetch(createUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        issues: currentDraft.issues,
        description: currentDraft.request || description.value,
      }),
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
      .then(function (resp) {
        var lines = [];
        if (resp.sprint_id) {
          lines.push(
            '<div class="sprint-result-header">' +
              '<strong>Sprint <code>' + resp.sprint_id + '</code></strong> ' +
              '<span class="text-muted">— track its progress in the Sprints panel below.</span>' +
            '</div>'
          );
        }
        (resp.created || []).forEach(function (c) {
          lines.push(
            '<div class="sprint-result-item">' +
              '<span class="badge badge-completed">created</span> ' +
              '<a href="' + (c.url || '#') + '" target="_blank" rel="noopener">#' +
              (c.number || '?') + ' ' + (c.title || '') + '</a>' +
            '</div>'
          );
        });
        (resp.errors || []).forEach(function (e) {
          lines.push('<div class="sprint-result-item sprint-result-err">' + e + '</div>');
        });
        result.innerHTML = lines.length ? lines.join('') : '<p class="text-muted">No issues created.</p>';
        result.hidden = false;
        setStatus('Created ' + (resp.created || []).length + ' issue(s)', 'ok');
        clearPreview();
        description.value = '';
        // Refresh the sprints panel so the new sprint shows up.
        if (typeof htmx !== 'undefined') {
          var panel = document.getElementById('sprints-panel');
          if (panel) htmx.trigger(panel, 'refresh');
        }
      })
      .catch(function (err) {
        setStatus('Create failed.', 'error');
        console.error(err);
      })
      .finally(function () {
        confirmBtn.disabled = false;
        cancelBtn.disabled = false;
      });
  });
})();
