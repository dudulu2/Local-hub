(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const video = $('#videoPlayer');
  const viewer = $('#viewer');
  const pathNode = $('#viewerPath');
  const tagStrip = $('#viewerTagStrip');
  if (!video || !viewer || !pathNode || !tagStrip) return;

  let heartbeatTimer = null;
  let uiPollTimer = null;
  let uiToken = 0;

  async function json(url, opt = {}) {
    const response = await fetch(url, {cache:'no-store', ...opt});
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function post(url, payload) {
    return json(url, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload),
    });
  }

  function currentPath() {
    return (pathNode.textContent || '').trim();
  }

  function toast(message) {
    const node = $('#toast');
    if (!node || !message) return;
    node.textContent = message;
    node.classList.add('show');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.classList.remove('show'), 2100);
  }

  function sendActivity(extra = {}) {
    const playing = viewer.open && !video.paused && !video.ended;
    return post('/api/io/activity', {playing, ...extra}).catch(() => {});
  }

  function stopHeartbeat() {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }

  function startHeartbeat() {
    stopHeartbeat();
    sendActivity({seeking: video.seeking});
    heartbeatTimer = setInterval(() => sendActivity({seeking: video.seeking}), 8000);
  }

  video.addEventListener('play', startHeartbeat);
  video.addEventListener('pause', () => { stopHeartbeat(); sendActivity({playing:false,seeking:false}); });
  video.addEventListener('ended', () => { stopHeartbeat(); sendActivity({playing:false,seeking:false}); });
  video.addEventListener('seeking', () => sendActivity({seeking:true}));
  video.addEventListener('seeked', () => sendActivity({seeking:false}));
  viewer.addEventListener('close', () => { stopHeartbeat(); sendActivity({playing:false,seeking:false}); });
  addEventListener('pagehide', () => {
    stopHeartbeat();
    try {
      navigator.sendBeacon('/api/io/activity', new Blob([JSON.stringify({playing:false,seeking:false})], {type:'application/json'}));
    } catch {}
  });

  function ensurePanel() {
    let panel = $('#autoTagPanel');
    if (panel) return panel;
    panel = document.createElement('section');
    panel.id = 'autoTagPanel';
    panel.className = 'autotag-panel';
    panel.innerHTML = `
      <div class="autotag-head">
        <div><b>AI Tag</b><span>SigLIP · 本地视觉分析</span></div>
        <span id="autoTagState" class="autotag-state"></span>
      </div>
      <div id="autoTagSuggestions" class="autotag-suggestions"></div>
      <div id="autoTagActions" class="autotag-actions"></div>`;
    tagStrip.insertAdjacentElement('afterend', panel);
    return panel;
  }

  function bytes(value) {
    const mb = Number(value || 0) / 1_000_000;
    return `${mb.toFixed(mb >= 100 ? 0 : 1)} MB`;
  }

  function setPanel(state, suggestions = '', actions = '') {
    ensurePanel();
    const stateNode = $('#autoTagState');
    const list = $('#autoTagSuggestions');
    const actionNode = $('#autoTagActions');
    if (stateNode) stateNode.textContent = state || '';
    if (list) list.innerHTML = suggestions;
    if (actionNode) actionNode.innerHTML = actions;
  }

  function button(label, action, primary = false) {
    return `<button type="button" class="autotag-btn${primary ? ' primary' : ''}" data-auto-action="${action}">${label}</button>`;
  }

  function addViewerTag(tag) {
    const add = $('#viewerTagAdd') || tagStrip.querySelector('.viewer-tag-add');
    const exists = [...tagStrip.querySelectorAll('[data-viewer-tag]')].some(node => (node.dataset.viewerTag || '').toLowerCase() === tag.toLowerCase());
    if (exists) return;
    tagStrip.querySelector('.viewer-no-tags')?.remove();
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'viewer-tag-chip';
    chip.dataset.viewerTag = tag;
    chip.textContent = `#${tag}`;
    tagStrip.insertBefore(chip, add || null);
    const input = $('#manageTags');
    if (input) {
      const tags = input.value.split(/[,，]/).map(x=>x.trim()).filter(Boolean);
      if (!tags.some(x => x.toLowerCase() === tag.toLowerCase())) tags.push(tag);
      input.value = tags.join(', ');
    }
  }

  async function loadSuggestions(path, token) {
    const data = await json(`/api/auto-tag/suggestions?path=${encodeURIComponent(path)}`);
    if (token !== uiToken || currentPath() !== path) return;
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) {
      setPanel('已分析', '<span class="autotag-empty">暂时没有足够可靠的建议</span>', button('重新分析', 'analyze'));
      return;
    }
    const markup = items.map((item, index) => {
      const score = Number(item.score ?? item.confidence ?? 0);
      return `<div class="autotag-suggestion" data-auto-index="${index}">
        <button type="button" class="autotag-accept" data-auto-tag="${encodeURIComponent(item.tag)}">＋ #${String(item.tag).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}</button>
        <span title="未校准的排序分数，不代表概率">${Number.isFinite(score) ? score.toFixed(3) : '—'}</span>
        <button type="button" class="autotag-reject" data-auto-reject="${encodeURIComponent(item.tag)}" aria-label="不符合">×</button>
      </div>`;
    }).join('');
    setPanel('建议 Tag', markup, button('空闲时分析全库', 'library-start'));
  }

  async function refreshPanel({poll = false} = {}) {
    clearTimeout(uiPollTimer);
    const path = currentPath();
    if (!viewer.open || !path) return;
    const token = ++uiToken;
    try {
      const status = await json(`/api/auto-tag/status?path=${encodeURIComponent(path)}`);
      if (token !== uiToken || currentPath() !== path) return;
      const model = status.model || {};
      if (!model.installed) {
        if (model.installing) {
          const pct = model.totalBytes ? Math.min(100, model.downloadedBytes / model.totalBytes * 100) : 0;
          const ioText = status.io?.playing || status.io?.seeking ? ' · 播放中暂停写盘' : '';
          setPanel(
            `模型下载 ${pct.toFixed(0)}%${ioText}`,
            `<div class="autotag-progress"><i style="width:${pct}%"></i></div><small>${bytes(model.downloadedBytes)} / ${bytes(model.totalBytes)}</small>`,
            ''
          );
          uiPollTimer = setTimeout(() => refreshPanel({poll:true}), 900);
        } else {
          const error = model.error ? `<span class="autotag-error">${model.error}</span>` : '<span class="autotag-empty">首次使用需下载约 206 MB，模型保存在本机 LocalAppData，不进入媒体备份目录。</span>';
          setPanel('未启用', error, button('安装 SigLIP 模型', 'install', true));
        }
        return;
      }

      if (!status.pathIndexed) {
        const waiting = status.current === path || status.queued > 0;
        if (waiting) {
          const paused = status.io?.playing || status.io?.seeking;
          setPanel(paused ? '已排队 · 播放优先' : '正在分析', '<span class="autotag-empty">固定时间点抽帧，不扫描整段视频。</span>', '');
          uiPollTimer = setTimeout(() => refreshPanel({poll:true}), 1000);
        } else {
          setPanel('尚未分析', '<span class="autotag-empty">只在空闲时读取 8 个候选帧，并保留 6 个代表向量。</span>', button('分析当前视频', 'analyze', true));
        }
        return;
      }

      await loadSuggestions(path, token);
      if (status.libraryRunning) {
        $('#autoTagActions')?.insertAdjacentHTML('beforeend', button('暂停全库分析', 'library-pause'));
      }
    } catch (error) {
      if (token !== uiToken) return;
      setPanel('不可用', `<span class="autotag-error">${error.message || error}</span>`, '');
      if (poll) uiPollTimer = setTimeout(() => refreshPanel({poll:true}), 1800);
    }
  }

  document.addEventListener('click', async event => {
    const actionButton = event.target.closest?.('[data-auto-action]');
    if (actionButton) {
      event.preventDefault();
      event.stopPropagation();
      const action = actionButton.dataset.autoAction;
      const path = currentPath();
      try {
        actionButton.disabled = true;
        if (action === 'install') await post('/api/auto-tag/model', {action:'install'});
        else if (action === 'analyze') await post('/api/auto-tag/queue', {path});
        else if (action === 'library-start') await post('/api/auto-tag/library', {action:'start'});
        else if (action === 'library-pause') await post('/api/auto-tag/library', {action:'pause'});
        refreshPanel({poll:true});
      } catch (error) {
        toast(error.message || String(error));
        actionButton.disabled = false;
      }
      return;
    }

    const accept = event.target.closest?.('[data-auto-tag]');
    if (accept) {
      event.preventDefault();
      event.stopPropagation();
      const path = currentPath();
      const tag = decodeURIComponent(accept.dataset.autoTag || '');
      if (!path || !tag) return;
      try {
        accept.disabled = true;
        await post('/api/manage', {action:'set_tags',paths:[path],tags:[tag],mode:'add'});
        await post('/api/auto-tag/feedback', {path,tag,value:1});
        addViewerTag(tag);
        accept.closest('.autotag-suggestion')?.remove();
        toast(`已添加 #${tag}`);
      } catch (error) {
        accept.disabled = false;
        toast(error.message || String(error));
      }
      return;
    }

    const reject = event.target.closest?.('[data-auto-reject]');
    if (reject) {
      event.preventDefault();
      event.stopPropagation();
      const path = currentPath();
      const tag = decodeURIComponent(reject.dataset.autoReject || '');
      if (!path || !tag) return;
      try {
        reject.disabled = true;
        await post('/api/auto-tag/feedback', {path,tag,value:-1});
        reject.closest('.autotag-suggestion')?.remove();
      } catch (error) {
        reject.disabled = false;
        toast(error.message || String(error));
      }
    }
  }, true);

  new MutationObserver(() => {
    if (!viewer.open || !currentPath()) return;
    setTimeout(() => refreshPanel(), 80);
  }).observe(pathNode, {subtree:true,childList:true,characterData:true});
  viewer.addEventListener('close', () => {
    clearTimeout(uiPollTimer);
    uiToken++;
  });
})();
