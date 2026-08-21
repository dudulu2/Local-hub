(() => {
  'use strict';

  const viewer = document.querySelector('#viewer');
  const grid = document.querySelector('#grid');
  if (!viewer) return;

  let warmingTimer = 0;
  const normalize = value => String(value || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');

  function isEditable(target) {
    if (!(target instanceof Element)) return false;
    return !!target.closest('input,textarea,select,[contenteditable="true"]');
  }

  document.addEventListener('keydown', e => {
    if (!viewer.open || e.altKey || e.ctrlKey || e.metaKey || isEditable(e.target)) return;
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    const player = window.videojs?.getPlayer?.('videoPlayer');
    if (!player) return;
    const current = Number(player.currentTime()) || 0;
    const duration = Number(player.duration()) || 0;
    const delta = e.key === 'ArrowLeft' ? -10 : 10;
    const target = Math.max(0, duration > 0 ? Math.min(duration, current + delta) : current + delta);
    e.preventDefault();
    e.stopPropagation();
    try { player.currentTime(target); } catch {}
  }, true);

  async function postJSON(url, payload, keepalive = false) {
    try {
      await fetch(url, {
        method:'POST', cache:'no-store', keepalive,
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),
      });
    } catch {}
  }

  function reportPlayback(active) {
    void postJSON('/api/stable2/playback', {active:!!active}, true);
  }

  function queueVisibleCovers() {
    clearTimeout(warmingTimer);
    if (viewer.open || !grid) return;
    warmingTimer = window.setTimeout(() => {
      if (viewer.open) return;
      const paths = [...grid.querySelectorAll('.card[data-id]')]
        .map(node => normalize(node.dataset.id))
        .filter(Boolean)
        .slice(0, 24);
      if (paths.length) void postJSON('/api/stable2/warm', {paths, includeHover:false});
    }, 600);
  }

  const viewerObserver = new MutationObserver(() => {
    reportPlayback(viewer.open);
    if (!viewer.open) queueVisibleCovers();
  });
  viewerObserver.observe(viewer, {attributes:true, attributeFilter:['open']});
  viewer.addEventListener('close', () => { reportPlayback(false); queueVisibleCovers(); });
  viewer.addEventListener('cancel', () => { reportPlayback(false); queueVisibleCovers(); });
  window.addEventListener('beforeunload', () => reportPlayback(false));

  if (grid) new MutationObserver(queueVisibleCovers).observe(grid, {childList:true, subtree:false});

  reportPlayback(viewer.open);
  queueVisibleCovers();
})();
