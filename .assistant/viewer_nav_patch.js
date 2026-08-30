// LH_RECOMMEND_NAVIGATION_FIX_V2
(() => {
  'use strict';

  const viewer = document.querySelector('#viewer');
  const pathNode = document.querySelector('#viewerPath');
  const search = document.querySelector('#searchInput');
  const closeButton = document.querySelector('#closeViewer');
  const toastNode = document.querySelector('#toast');
  if (!viewer || !pathNode || !search || !closeButton) return;

  const history = [];
  let internalNavigation = false;
  let navigatingBack = false;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  function toast(message) {
    if (!toastNode || !message) return;
    toastNode.textContent = message;
    toastNode.classList.add('show');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => toastNode.classList.remove('show'), 2100);
  }

  async function api(url) {
    const response = await fetch(url, {cache:'no-store'});
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function snapshotView() {
    return {
      folder: document.querySelector('.folder-nav button.active')?.dataset.folder ?? null,
      route: document.querySelector('.main-nav button.active')?.dataset.route || '',
      query: (search.value || '').trim(),
    };
  }

  function restoreBackground(view) {
    if (!view) return;
    if (view.folder != null) {
      const direct = [...document.querySelectorAll('.folder-nav button')].find(node => node.dataset.folder === view.folder);
      direct?.click();
      return;
    }
    if (view.query) {
      search.value = view.query;
      search.dispatchEvent(new Event('input', {bubbles:true}));
      return;
    }
    if (view.route) document.querySelector(`.main-nav button[data-route="${CSS.escape(view.route)}"]`)?.click();
  }

  async function itemById(id) {
    if (!id) return null;
    const data = await api(`/api/smart/by-ids?ids=${encodeURIComponent(id)}`);
    return (data.items || []).find(item => item.id === id) || (data.items || [])[0] || null;
  }

  function updateBackButton() {
    let button = document.querySelector('#viewerHistoryBack');
    if (!button) {
      button = document.createElement('button');
      button.id = 'viewerHistoryBack';
      button.type = 'button';
      button.className = 'lh-viewer-history-back';
      button.setAttribute('aria-label', '返回上一个视频');
      button.title = '返回上一个视频';
      button.textContent = '←';
      viewer.appendChild(button);
      button.addEventListener('click', async event => {
        event.preventDefault();
        event.stopPropagation();
        const previous = history.pop();
        updateBackButton();
        if (!previous) return;
        try {
          const item = await itemById(previous);
          if (!item) throw new Error('上一个视频已不存在');
          navigatingBack = true;
          await openExactItem(item, {recordHistory:false});
        } catch (error) {
          toast(error.message || '无法返回上一个视频');
        } finally {
          navigatingBack = false;
          updateBackButton();
        }
      });
    }
    button.classList.toggle('hidden', history.length === 0);
  }

  if (!document.querySelector('#lhViewerNavigationStyle')) {
    const style = document.createElement('style');
    style.id = 'lhViewerNavigationStyle';
    style.textContent = `
      .lh-viewer-history-back{position:absolute;left:12px;top:12px;z-index:40;width:40px;height:40px;border:1px solid #35353a;border-radius:50%;background:rgba(0,0,0,.72);color:#fff;font-size:24px;line-height:1;display:grid;place-items:center;cursor:pointer;box-shadow:0 5px 18px rgba(0,0,0,.28)}
      .lh-viewer-history-back:hover{background:#202024;border-color:#55555c}
      .lh-viewer-history-back.hidden{display:none!important}
    `;
    document.head.appendChild(style);
  }
  updateBackButton();

  async function waitForExactCard(id, timeout = 4600) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const card = [...document.querySelectorAll('.card[data-id]')].find(node => node.dataset.id === id);
      if (card) return card;
      await sleep(80);
    }
    return null;
  }

  async function openExactItem(item, {recordHistory=true} = {}) {
    const targetId = String(item?.id || '');
    if (!targetId) throw new Error('推荐视频路径无效');
    const currentId = (pathNode.textContent || '').trim();
    if (recordHistory && currentId && currentId !== targetId && !navigatingBack) {
      if (history[history.length - 1] !== currentId) history.push(currentId);
      if (history.length > 40) history.splice(0, history.length - 40);
      updateBackButton();
    }

    const background = snapshotView();
    internalNavigation = true;
    closeButton.click();
    await sleep(55);

    const queries = [item.name, item.stem, String(item.name || '').replace(/\.[^.]+$/, '')]
      .map(value => String(value || '').trim())
      .filter((value, index, rows) => value && rows.indexOf(value) === index);

    let card = null;
    for (const query of queries) {
      search.value = query;
      search.dispatchEvent(new Event('input', {bubbles:true}));
      card = await waitForExactCard(targetId, 2600);
      if (card) break;
    }

    if (!card) {
      internalNavigation = false;
      restoreBackground(background);
      throw new Error('推荐视频存在，但当前列表没有定位到它');
    }

    card.click();
    const deadline = Date.now() + 2600;
    while (Date.now() < deadline) {
      if (viewer.open && (pathNode.textContent || '').trim() === targetId) break;
      await sleep(60);
    }
    viewer.scrollTop = 0;
    setTimeout(() => restoreBackground(background), 120);
    internalNavigation = false;
    updateBackButton();
  }

  document.addEventListener('click', async event => {
    const card = event.target.closest?.('.v23-rec-card[data-rec-id]');
    if (!card) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    try {
      const item = await itemById(card.dataset.recId || '');
      if (!item) throw new Error('推荐视频已不存在');
      await openExactItem(item, {recordHistory:true});
    } catch (error) {
      internalNavigation = false;
      toast(error.message || '暂时无法打开推荐视频');
    }
  }, true);

  viewer.addEventListener('close', () => {
    if (internalNavigation) return;
    history.length = 0;
    updateBackButton();
  });
})();
