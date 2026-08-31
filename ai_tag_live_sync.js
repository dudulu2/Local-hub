(() => {
  'use strict';

  let revision = 0;
  let timer = null;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  async function json(url) {
    const response = await fetch(url, {cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function wireTagButton(button, tag) {
    button.addEventListener('click', event => {
      if (event.target.closest('.tag-remove-inline')) return;
      event.preventDefault();
      event.stopPropagation();
      const input = document.querySelector('#searchInput');
      if (!input) return;
      input.value = tag;
      input.dispatchEvent(new Event('input', {bubbles:true}));
    });
  }

  function rebuildStrip(strip, path, tags, viewer = false) {
    if (!strip) return;
    const rating = strip.querySelector('.rating-inline');
    const add = viewer ? (strip.querySelector('#viewerTagAdd') || strip.querySelector('.viewer-tag-add')) : strip.querySelector('.tag-edit');
    strip.querySelectorAll(viewer ? '.viewer-tag-chip,.viewer-no-tags' : '.tag-chip,.no-tags').forEach(node => node.remove());
    if (!tags.length) {
      const empty = document.createElement('span');
      empty.className = viewer ? 'viewer-no-tags' : 'no-tags';
      empty.textContent = '暂无标签';
      strip.insertBefore(empty, rating || add || null);
      return;
    }
    for (const tag of tags) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = viewer ? 'viewer-tag-chip' : 'tag-chip';
      if (viewer) button.dataset.viewerTag = tag;
      else button.dataset.tag = tag;
      button.innerHTML = `#${esc(tag)}<span class="tag-remove-inline" title="删除这个标签">×</span>`;
      wireTagButton(button, tag);
      strip.insertBefore(button, rating || add || null);
    }
  }

  async function refreshPath(path) {
    try {
      const meta = await json(`/api/rating?path=${encodeURIComponent(path)}`);
      const tags = Array.isArray(meta.tags) ? meta.tags : [];
      document.querySelectorAll('[data-tag-strip]').forEach(strip => {
        if (strip.dataset.tagStrip === path) rebuildStrip(strip, path, tags, false);
      });
      const viewerPath = (document.querySelector('#viewerPath')?.textContent || '').trim();
      const viewer = document.querySelector('#viewerTagStrip');
      if (viewer && viewerPath === path) {
        rebuildStrip(viewer, path, tags, true);
        const input = document.querySelector('#manageTags');
        if (input) input.value = tags.join(', ');
      }
    } catch {}
  }

  async function poll() {
    clearTimeout(timer);
    if (document.hidden) {
      timer = setTimeout(poll, 3500);
      return;
    }
    try {
      const data = await json(`/api/ai/tag-sync?since=${revision}`);
      revision = Math.max(revision, Number(data.revision) || 0);
      const changed = Array.isArray(data.changed) ? data.changed : [];
      if (changed.length) {
        for (const path of changed) await refreshPath(path);
        window.dispatchEvent(new CustomEvent('localhub:ai-tags-updated', {detail:{paths:changed, revision}}));
      }
    } catch {}
    const viewerPlaying = !!document.querySelector('#viewer[open] #videoPlayer:not(:paused)');
    timer = setTimeout(poll, viewerPlaying ? 2600 : 1600);
  }

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      clearTimeout(timer);
      timer = setTimeout(poll, 120);
    }
  });
  timer = setTimeout(poll, 900);
})();
