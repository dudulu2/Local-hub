(() => {
  'use strict';

  // Keep the real browser observer for our thumbnail scheduler, then shield the
  // legacy card-video observer in app.js. Playback in the viewer is untouched.
  const NativeIntersectionObserver = window.IntersectionObserver;
  if (NativeIntersectionObserver) {
    window.IntersectionObserver = function LocalHubIntersectionObserver(callback, options) {
      const inner = new NativeIntersectionObserver(callback, options);
      return {
        observe(target) {
          if (target instanceof Element && target.classList.contains('lazy-preview')) return;
          inner.observe(target);
        },
        unobserve(target) { inner.unobserve(target); },
        disconnect() { inner.disconnect(); },
        takeRecords() { return inner.takeRecords(); },
        get root() { return inner.root; },
        get rootMargin() { return inner.rootMargin; },
        get thresholds() { return inner.thresholds; },
      };
    };
  }

  const PAGE_SIZE = 60;
  const PAGE_STEP = 40;
  const MAX_THUMB_REQUESTS = 2;
  const thumbnailQueue = [];
  let activeThumbnailRequests = 0;
  let gridStash = [];
  let gridSentinel = null;
  let gridObserver = null;
  let mutationScheduled = false;

  function injectStyles() {
    if (document.getElementById('localhub-performance-style')) return;
    const style = document.createElement('style');
    style.id = 'localhub-performance-style';
    style.textContent = `
      .cached-video-thumb{opacity:0;transition:opacity .16s ease;background:#171719}
      .cached-video-thumb.perf-loaded{opacity:1}
      .cached-video-thumb.perf-error{opacity:0}
      .thumb-wrap.perf-awaiting::after{content:'预览';position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);font-size:10px;font-weight:800;letter-spacing:.08em;color:#5f5f67;border:1px solid #303034;border-radius:999px;padding:4px 7px;background:rgba(14,14,15,.82);pointer-events:none}
      .thumb-wrap.perf-loading::after{content:'生成预览…';color:#8b8b93;border-color:#3a3a40}
      .thumb-wrap.perf-ready::after{display:none}
      .perf-load-more{grid-column:1/-1;min-height:46px;display:flex;align-items:center;justify-content:center;color:#6f6f77;font-size:11px;border-top:1px solid #202024;margin-top:4px;padding-top:14px}
      .perf-load-more button{border:1px solid #333338;background:#171719;color:#bcbcc3;border-radius:9px;padding:8px 14px;cursor:pointer;font-weight:700}
      .perf-load-more button:hover{border-color:#505057;background:#202024;color:#fff}
      .perf-load-more.done{opacity:.65}.perf-load-more.done button{cursor:default;border-color:transparent;background:transparent;color:#66666d}
      .perf-status{position:fixed;right:18px;bottom:18px;z-index:80;padding:7px 10px;border-radius:8px;border:1px solid #303035;background:rgba(20,20,22,.92);color:#8f8f97;font-size:10px;pointer-events:none;opacity:0;transform:translateY(8px);transition:.18s}
      .perf-status.show{opacity:1;transform:translateY(0)}
      @media(max-width:620px){.perf-status{right:10px;bottom:68px}.perf-load-more{min-height:40px}}
    `;
    document.head.appendChild(style);
  }

  function statusNode() {
    let node = document.getElementById('perfStatus');
    if (!node) {
      node = document.createElement('div');
      node.id = 'perfStatus';
      node.className = 'perf-status';
      document.body.appendChild(node);
    }
    return node;
  }

  function updateStatus() {
    const node = statusNode();
    const pending = thumbnailQueue.length + activeThumbnailRequests;
    if (pending <= 0) {
      node.classList.remove('show');
      return;
    }
    node.textContent = `正在准备 ${pending} 个预览 · 最多并行 ${MAX_THUMB_REQUESTS}`;
    node.classList.add('show');
  }

  function thumbnailUrl(path) {
    return `/api/thumbnail?path=${encodeURIComponent(path)}`;
  }

  function pumpThumbnailQueue() {
    while (activeThumbnailRequests < MAX_THUMB_REQUESTS && thumbnailQueue.length) {
      const img = thumbnailQueue.shift();
      if (!img || !img.isConnected || img.dataset.perfStarted === '1') continue;
      img.dataset.perfStarted = '1';
      activeThumbnailRequests++;
      const wrap = img.closest('.thumb-wrap');
      wrap?.classList.remove('perf-awaiting');
      wrap?.classList.add('perf-loading');

      const finish = (ok) => {
        activeThumbnailRequests = Math.max(0, activeThumbnailRequests - 1);
        wrap?.classList.remove('perf-loading');
        wrap?.classList.add('perf-ready');
        img.classList.toggle('perf-loaded', ok);
        img.classList.toggle('perf-error', !ok);
        updateStatus();
        pumpThumbnailQueue();
      };
      img.addEventListener('load', () => finish(true), { once: true });
      img.addEventListener('error', () => finish(false), { once: true });
      img.src = img.dataset.perfSrc || '';
    }
    updateStatus();
  }

  const thumbObserver = NativeIntersectionObserver
    ? new NativeIntersectionObserver((entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const img = entry.target;
          thumbObserver.unobserve(img);
          if (img.dataset.perfQueued === '1' || img.dataset.perfStarted === '1') continue;
          img.dataset.perfQueued = '1';
          thumbnailQueue.push(img);
        }
        pumpThumbnailQueue();
      }, { rootMargin: '90px 0px', threshold: 0.01 })
    : null;

  function makeVideoThumbnail(card, video) {
    const path = card.dataset.id;
    if (!path) return;
    const img = document.createElement('img');
    img.className = 'cached-video-thumb';
    img.alt = '';
    img.decoding = 'async';
    img.loading = 'lazy';
    img.dataset.perfSrc = thumbnailUrl(path);
    video.pause?.();
    video.removeAttribute('src');
    video.removeAttribute('data-src');
    try { video.load?.(); } catch {}
    video.replaceWith(img);
    const wrap = img.closest('.thumb-wrap');
    wrap?.classList.add('perf-awaiting');
    if (thumbObserver) thumbObserver.observe(img);
    else {
      thumbnailQueue.push(img);
      pumpThumbnailQueue();
    }
  }

  function processCard(card) {
    if (!(card instanceof HTMLElement) || !card.classList.contains('media-card')) return;
    if (card.dataset.perfProcessed === '1') return;
    card.dataset.perfProcessed = '1';
    const video = card.querySelector('video.lazy-preview');
    if (video) makeVideoThumbnail(card, video);
  }

  function processCards(container) {
    if (!container) return;
    container.querySelectorAll('.media-card').forEach(processCard);
  }

  function clearPaging() {
    if (gridObserver && gridSentinel) {
      try { gridObserver.unobserve(gridSentinel); } catch {}
    }
    gridSentinel?.remove();
    gridSentinel = null;
    gridStash = [];
  }

  function appendNextPage() {
    const grid = document.getElementById('mediaGrid');
    if (!grid || !gridSentinel || !gridStash.length) return;
    const batch = gridStash.splice(0, PAGE_STEP);
    const fragment = document.createDocumentFragment();
    batch.forEach((card) => fragment.appendChild(card));
    grid.insertBefore(fragment, gridSentinel);
    const button = gridSentinel.querySelector('button');
    if (!gridStash.length) {
      gridObserver?.unobserve(gridSentinel);
      gridSentinel.classList.add('done');
      if (button) button.textContent = '全部已加载';
    } else if (button) {
      button.textContent = `继续加载 · 剩余 ${gridStash.length}`;
    }
  }

  function setupPaging(grid) {
    if (!grid || grid.querySelector('.perf-load-more')) return;
    const cards = [...grid.children].filter((node) => node.classList?.contains('media-card'));
    cards.forEach(processCard);
    if (cards.length <= PAGE_SIZE) {
      gridStash = [];
      return;
    }

    gridStash = cards.slice(PAGE_SIZE);
    for (const card of gridStash) card.remove();

    gridSentinel = document.createElement('div');
    gridSentinel.className = 'perf-load-more';
    gridSentinel.innerHTML = `<button type="button">继续加载 · 剩余 ${gridStash.length}</button>`;
    gridSentinel.querySelector('button').addEventListener('click', appendNextPage);
    grid.appendChild(gridSentinel);

    if (NativeIntersectionObserver) {
      gridObserver = gridObserver || new NativeIntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) appendNextPage();
      }, { rootMargin: '500px 0px' });
      gridObserver.observe(gridSentinel);
    }
  }

  function scheduleMutationWork() {
    if (mutationScheduled) return;
    mutationScheduled = true;
    queueMicrotask(() => {
      mutationScheduled = false;
      const grid = document.getElementById('mediaGrid');
      const rail = document.getElementById('continueRail');
      processCards(rail);
      if (!grid) return;

      // app.js replaces grid.innerHTML whenever filtering/sorting changes. The
      // sentinel disappears in that case, which is our signal to rebuild paging.
      if (!grid.querySelector('.perf-load-more')) {
        clearPaging();
        setupPaging(grid);
      } else {
        processCards(grid);
      }
    });
  }

  function init() {
    injectStyles();
    const grid = document.getElementById('mediaGrid');
    const rail = document.getElementById('continueRail');
    if (!grid) return;

    const observer = new MutationObserver(scheduleMutationWork);
    observer.observe(grid, { childList: true });
    if (rail) observer.observe(rail, { childList: true });
    scheduleMutationWork();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
