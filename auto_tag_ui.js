(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const video = $('#videoPlayer');
  const viewer = $('#viewer');
  const pathNode = $('#viewerPath');
  const tagStrip = $('#viewerTagStrip');
  if (!video || !viewer || !pathNode || !tagStrip) return;

  const DISMISS_COOKIE = 'localhub_ai_hidden';
  const DISMISS_MAX_AGE = 60 * 60 * 24 * 365 * 5;

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

  function aiDismissed() {
    return document.cookie
      .split(';')
      .map(value => value.trim())
      .some(value => value === `${DISMISS_COOKIE}=1`);
  }

  function hideAiUi({persist = false} = {}) {
    clearTimeout(uiPollTimer);
    uiToken++;
    if (persist) {
      // Cookies are host-scoped rather than port-scoped, so this preference also
      // survives the rare case where LocalHub has to use a port other than 8787.
      document.cookie = `${DISMISS_COOKIE}=1; Max-Age=${DISMISS_MAX_AGE}; Path=/; SameSite=Strict`;
    }
    $('#autoTagPanel')?.remove();
    viewer.classList.remove('autotag-visible');
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
    if (aiDismissed()) {
      hideAiUi();
      return null;
    }
    let panel = $('#autoTagPanel');
    if (panel) return panel;
    panel = document.createElement('section');
    panel.id = 'autoTagPanel';
    panel.className = 'autotag-panel';
    panel.innerHTML = `
      <div class="autotag-head">
        <div class="autotag-title">
          <b>AI Tag</b>
          <span>SigLIP · 本地视觉分析</span>
        </div>
        <div class="autotag-head-actions">
          <span id="autoTagState" class="autotag-state"></span>
          <button type="button" class="autotag-dismiss" data-auto-dismiss aria-label="不再显示 AI Tag" title="不再显示 AI Tag">×</button>
        </div>
      </div>
      <div id="autoTagSuggestions" class="autotag-suggestions"></div>
      <div id="autoTagActions" class="autotag-actions"></div>`;
    tagStrip.insertAdjacentElement('afterend', panel);
    viewer.classList.add('autotag-visible');
    return panel;
  }

  function bytes(value) {
    const mb = Number(value || 0) / 1_000_000;
    return `${mb.toFixed(mb >= 100 ? 0 : 1)} MB`;
  }

  function setPanel(state, suggestions = '', actions = '') {
    const panel = ensurePanel();
    if (!panel) return;
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
    if (aiDismissed()) {
      hideAiUi();
      return;
    }
    const path = currentPath();
    if (!viewer.open || !path) return;
    const token = ++uiToken;
    try {
      const status = await json(`/api/auto-tag/status?path=${encodeURIComponent(path)}`);
      if (token !== uiToken || currentPath() !== path || aiDismissed()) return;
      const model = status.model || {};
      if (!model.installed) {
        if (model.installing) {
          const pct = model.totalBytes ? Math.min(100, model.downloadedBytes / model.totalBytes * 100) : 0;
          const ioText = status.io?.playing || status.io?.seeking ? ' · 播放优先' : '';
          setPanel(
            `本地安装 ${pct.toFixed(0)}%${ioText}`,
            `<div class="autotag-install-row"><div class="autotag-progress"><i style="width:${pct}%"></i></div><small>${bytes(model.downloadedBytes)} / ${bytes(model.totalBytes)}</small></div>`,
            ''
          );
          uiPollTimer = setTimeout(() => refreshPanel({poll:true}), 900);
        } else if (model.localPackageAvailable) {
          setPanel(
            '可选功能',
            '<span class="autotag-empty">离线 AI 模型包已就绪。安装后会移入本机 LocalAppData，校验成功后自动删除 EXE 同目录的模型包。</span>',
            button('安装本地 AI 模型', 'install', true)
          );
        } else {
          const reason = model.localPackageError || model.error;
          const text = reason
            ? `<span class="autotag-error">${String(reason).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}</span>`
            : '<span class="autotag-empty">未发现离线 AI 模型包。请使用完整 LocalHub 安装包，或将 <b>LocalHub-AI-Model</b> 文件夹放到 LocalHub.exe 同目录。</span>';
          setPanel('模型未安装', text, '');
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
          const warning = model.cleanupWarning ? `<span class="autotag-error">${model.cleanupWarning}</span>` : '<span class="autotag-empty">只在空闲时读取 8 个候选帧，并保留 6 个代表向量。</span>';
          setPanel('模型已就绪', warning, button('分析当前视频', 'analyze', true));
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
    const dismiss = event.target.closest?.('[data-auto-dismiss]');
    if (dismiss) {
      event.preventDefault();
      event.stopPropagation();
      hideAiUi({persist:true});
      return;
    }

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
        refreshPanel();
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
    if (aiDismissed()) {
      hideAiUi();
      return;
    }
    if (!viewer.open || !currentPath()) return;
    setTimeout(() => refreshPanel(), 80);
  }).observe(pathNode, {subtree:true,childList:true,characterData:true});

  viewer.addEventListener('close', () => {
    clearTimeout(uiPollTimer);
    uiToken++;
  });
})();
