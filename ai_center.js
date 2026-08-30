(() => {
  'use strict';

  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const grid = $('#grid');
  const pageTitle = $('#pageTitle');
  const pageMeta = $('#pageMeta');
  const viewHint = $('#viewHint');
  const pager = $('#pager');
  const empty = $('#empty');
  const searchInput = $('#searchInput');
  const viewer = $('#viewer');
  const viewerPath = $('#viewerPath');
  const viewerTagStrip = $('#viewerTagStrip');
  const viewerActions = document.querySelector('.viewer-actions');
  const rescan = $('#rescanBtn');
  const toastNode = $('#toast');
  if (!grid || !pageTitle) return;

  let aiPageActive = false;
  let aiPollTimer = null;
  let settingsCache = null;
  let overviewCache = null;
  let viewerPollTimer = null;
  let installPollTimer = null;

  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[ch]));

  function toast(message) {
    if (!toastNode || !message) return;
    toastNode.textContent = message;
    toastNode.classList.add('show');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => toastNode.classList.remove('show'), 2200);
  }

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

  function bytes(value) {
    let size = Number(value) || 0;
    const units = ['B','KB','MB','GB'];
    let index = 0;
    while (size >= 1024 && index < units.length - 1) { size /= 1024; index++; }
    return `${index === 0 || size >= 10 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
  }

  function stopAiPoll() {
    clearTimeout(aiPollTimer);
    aiPollTimer = null;
  }

  function setAiNavActive() {
    $$('.main-nav button').forEach(button => button.classList.remove('active'));
    $('#aiCenterNav')?.classList.add('active');
  }

  function leaveAiPage() {
    if (!aiPageActive) return;
    aiPageActive = false;
    stopAiPoll();
    grid.classList.remove('ai-center-grid');
  }

  function installNav() {
    if ($('#aiCenterNav')) return;
    const tagNav = $('#tagCategoryNav') || $('.main-nav button[data-route="tags"]') || $('.main-nav button[data-route="packs"]');
    const nav = document.createElement('button');
    nav.type = 'button';
    nav.id = 'aiCenterNav';
    nav.dataset.route = 'ai-center';
    nav.innerHTML = '<span>✦</span>AI 分析';
    if (tagNav) tagNav.insertAdjacentElement('afterend', nav);
    else $('.main-nav')?.appendChild(nav);
    nav.addEventListener('click', event => {
      event.preventDefault();
      event.stopImmediatePropagation();
      openAiCenter();
    }, true);
  }

  function installAccountMenu() {
    if ($('#localHubAccount')) return;
    if (rescan) rescan.classList.add('lh-menu-owned');
    const host = document.createElement('div');
    host.id = 'localHubAccount';
    host.className = 'lh-account';
    host.innerHTML = `
      <button type="button" id="localHubAccountBtn" class="lh-account-btn" aria-label="LocalHub 菜单" title="LocalHub 菜单">L</button>
      <div id="localHubAccountMenu" class="lh-account-menu hidden">
        <button type="button" data-account-action="rescan">↻ 刷新目录</button>
        <button type="button" data-account-action="ai">✦ AI 分析</button>
        <div class="lh-menu-sep"></div>
        <button type="button" data-account-action="settings">⚙ 设置</button>
      </div>`;
    document.querySelector('.topbar')?.appendChild(host);
    const button = $('#localHubAccountBtn');
    const menu = $('#localHubAccountMenu');
    button?.addEventListener('click', event => {
      event.stopPropagation();
      menu?.classList.toggle('hidden');
    });
    document.addEventListener('click', event => {
      if (!host.contains(event.target)) menu?.classList.add('hidden');
    });
    menu?.addEventListener('click', event => {
      const action = event.target.closest('[data-account-action]')?.dataset.accountAction;
      if (!action) return;
      menu.classList.add('hidden');
      if (action === 'rescan') rescan?.click();
      else if (action === 'ai') openAiCenter();
      else if (action === 'settings') openSettings();
    });
  }

  async function getOverview() {
    overviewCache = await json('/api/ai/overview');
    if (overviewCache.settings) settingsCache = overviewCache.settings;
    return overviewCache;
  }

  function progressPercent(overview) {
    const total = Math.max(0, Number(overview.totalVideos) || 0);
    const indexed = Math.max(0, Number(overview.semanticIndexed) || 0);
    return total > 0 ? Math.max(0, Math.min(100, indexed / total * 100)) : 0;
  }

  function modelLabel(model) {
    if (model?.installing) return '正在安装本地模型';
    if (model?.installed) return model?.enabled ? 'SigLIP 已启用' : 'SigLIP 已安装';
    if (model?.localPackageAvailable) return '本地模型包待安装';
    return 'AI 模型未安装';
  }

  function renderAiPage(overview) {
    if (!aiPageActive) return;
    const status = overview.status || {};
    const model = overview.model || status.model || {};
    const settings = overview.settings || {};
    const total = Math.max(0, Number(overview.totalVideos) || 0);
    const indexed = Math.max(0, Number(overview.semanticIndexed) || 0);
    const percent = progressPercent(overview);
    const queued = Math.max(0, Number(status.queued) || 0);
    const failed = Math.max(0, Number(status.failed) || 0);
    const current = String(status.current || '');
    const running = !!status.libraryRunning;
    const playing = !!status.io?.playing;
    const seeking = !!status.io?.seeking;
    const modeText = settings.backgroundMode === 'idle'
      ? '仅空闲时分析'
      : (seeking ? '拖动进度条，AI 暂停' : playing ? '播放中 · 低负载分析' : '均衡后台分析');
    const groups = (settings.groups || []).map(group =>
      `<span class="ai-group-pill${group.enabled ? ' on' : ''}">${escapeHtml(group.name)} · ${(group.tags || []).length}</span>`
    ).join('');

    grid.innerHTML = `
      <section class="ai-center-page">
        <div class="ai-hero">
          <div>
            <h2>本地 AI 媒体分析</h2>
            <p>SigLIP 在本机读取少量代表帧建立视觉索引。默认允许播放时低负载继续工作；拖动进度条和定位时立即让路。</p>
          </div>
          <div class="ai-hero-actions">
            ${!model.installed ? '<button class="ai-btn primary" data-ai-page-action="install">安装本地 AI 模型</button>' : ''}
            ${model.installed && !running ? '<button class="ai-btn primary" data-ai-page-action="start">分析整个媒体库</button>' : ''}
            ${running ? '<button class="ai-btn" data-ai-page-action="pause">暂停后台分析</button>' : ''}
            <button class="ai-btn" data-ai-page-action="settings">AI / Tag 设置</button>
          </div>
        </div>

        <div class="ai-stats">
          <div class="ai-stat"><strong>${indexed}</strong><span>已建立 AI 索引</span></div>
          <div class="ai-stat"><strong>${total}</strong><span>媒体库视频</span></div>
          <div class="ai-stat"><strong>${queued}</strong><span>等待分析</span></div>
          <div class="ai-stat"><strong>${failed}</strong><span>本轮失败</span></div>
        </div>

        <div class="ai-progress-card">
          <div class="ai-section-head"><h3>全库进度</h3><span>${modeText}</span></div>
          <div class="ai-progress-track"><i style="width:${percent.toFixed(1)}%"></i></div>
          <div class="ai-progress-meta"><span>${indexed} / ${total} 个视频</span><span>${percent.toFixed(1)}%</span></div>
        </div>

        <div class="ai-current-card">
          <div class="ai-section-head"><h3>当前任务</h3><span>${running ? '后台持续运行' : '未运行'}</span></div>
          <div class="ai-current-path">${current ? escapeHtml(current) : '当前没有正在分析的视频'}</div>
          <p class="ai-muted">单个视频只抽取最多 8 个候选帧、保留 6 个代表向量；已完成的视频会缓存，重启后不会从头重复解析。</p>
        </div>

        <div class="ai-model-card">
          <div class="ai-section-head"><h3>模型与 Tag 组</h3><span>${escapeHtml(modelLabel(model))}</span></div>
          ${model.installing ? `<div class="ai-progress-track"><i style="width:${model.totalBytes ? Math.min(100,(Number(model.downloadedBytes)||0)/(Number(model.totalBytes)||1)*100) : 0}%"></i></div><p class="ai-muted">${bytes(model.downloadedBytes)} / ${bytes(model.totalBytes)}</p>` : ''}
          <div class="ai-tag-group-summary">${groups}</div>
        </div>
      </section>`;
    if (empty) empty.classList.add('hidden');
    if (pager) pager.classList.add('hidden');
  }

  async function refreshAiPage() {
    stopAiPoll();
    if (!aiPageActive) return;
    try {
      renderAiPage(await getOverview());
    } catch (error) {
      grid.innerHTML = `<section class="ai-center-page"><div class="ai-current-card"><h3>AI 状态读取失败</h3><p class="ai-muted">${escapeHtml(error.message || error)}</p></div></section>`;
    }
    if (aiPageActive) aiPollTimer = setTimeout(refreshAiPage, 1400);
  }

  function openAiCenter() {
    aiPageActive = true;
    setAiNavActive();
    grid.classList.add('ai-center-grid');
    pageTitle.textContent = 'AI 分析';
    if (pageMeta) pageMeta.textContent = '';
    if (viewHint) viewHint.textContent = '';
    if (pager) pager.classList.add('hidden');
    if (empty) empty.classList.add('hidden');
    grid.innerHTML = '<section class="ai-center-page"><div class="ai-current-card"><p class="ai-muted">正在读取 AI 状态…</p></div></section>';
    refreshAiPage();
  }

  async function pageAction(action, button) {
    try {
      if (button) button.disabled = true;
      if (action === 'settings') return openSettings();
      if (action === 'install') {
        await post('/api/auto-tag/model', {action:'install'});
        toast('正在从 LocalHub 本地模型包安装');
      } else if (action === 'start') {
        const overview = overviewCache || await getOverview();
        if (!overview.model?.installed) {
          openSettings();
          return;
        }
        await post('/api/auto-tag/library', {action:'start'});
        toast('已开始后台分析全库');
      } else if (action === 'pause') {
        await post('/api/auto-tag/library', {action:'pause'});
        toast('后台分析已暂停');
      }
      await refreshAiPage();
    } catch (error) {
      toast(error.message || String(error));
    } finally {
      if (button) button.disabled = false;
    }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest?.('[data-ai-page-action]');
    if (!button) return;
    event.preventDefault();
    pageAction(button.dataset.aiPageAction, button);
  });

  function installViewerButton() {
    if (!viewerActions || $('#viewerAiButton')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'viewerAiButton';
    button.className = 'viewer-ai-btn';
    button.textContent = '✦ AI 分析';
    button.title = '分析当前视频 / 查看 AI Tag';
    viewerActions.insertBefore(button, viewerActions.firstChild);

    const popover = document.createElement('div');
    popover.id = 'viewerAiPopover';
    popover.className = 'viewer-ai-popover hidden';
    popover.innerHTML = '<header><b>AI 分析</b><button type="button" data-viewer-ai-close>×</button></header><div id="viewerAiBody" class="viewer-ai-state"></div>';
    viewerActions.appendChild(popover);

    button.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      if (popover.classList.contains('hidden')) openViewerAi();
      else popover.classList.add('hidden');
    });
    popover.addEventListener('click', event => {
      if (event.target.closest('[data-viewer-ai-close]')) popover.classList.add('hidden');
    });
  }

  function currentPath() {
    return (viewerPath?.textContent || '').trim();
  }

  function addViewerTag(tag) {
    if (!viewerTagStrip || !tag) return;
    const exists = [...viewerTagStrip.querySelectorAll('[data-viewer-tag]')].some(node =>
      String(node.dataset.viewerTag || '').toLocaleLowerCase() === String(tag).toLocaleLowerCase()
    );
    if (exists) return;
    viewerTagStrip.querySelector('.viewer-no-tags')?.remove();
    const add = $('#viewerTagAdd') || viewerTagStrip.querySelector('.viewer-tag-add');
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'viewer-tag-chip';
    chip.dataset.viewerTag = tag;
    chip.textContent = `#${tag}`;
    viewerTagStrip.insertBefore(chip, add || null);
    const input = $('#manageTags');
    if (input) {
      const tags = input.value.split(/[,，]/).map(value => value.trim()).filter(Boolean);
      if (!tags.some(value => value.toLocaleLowerCase() === tag.toLocaleLowerCase())) tags.push(tag);
      input.value = tags.join(', ');
    }
  }

  function renderViewerSuggestions(items, status) {
    const body = $('#viewerAiBody');
    if (!body) return;
    if (!items.length) {
      body.innerHTML = '<div class="viewer-ai-state">已经完成分析，但当前没有足够合适的 Tag 建议。</div><div class="viewer-ai-actions"><button class="ai-btn" data-viewer-ai-action="reanalyze">重新分析</button><button class="ai-btn" data-viewer-ai-action="center">打开 AI 页面</button></div>';
      return;
    }
    const chips = items.map(item => {
      const score = Number(item.score ?? item.confidence ?? 0);
      return `<span class="viewer-ai-chip"><button data-viewer-ai-accept="${encodeURIComponent(item.tag)}">＋ #${escapeHtml(item.tag)}</button><small>${Number.isFinite(score) ? score.toFixed(3) : ''}</small><button class="reject" data-viewer-ai-reject="${encodeURIComponent(item.tag)}">×</button></span>`;
    }).join('');
    body.innerHTML = `<div class="viewer-ai-state">${status?.io?.playing ? '播放中使用低负载结果 · ' : ''}点击 ＋ 接受 Tag，× 表示不符合。</div><div class="viewer-ai-suggestions">${chips}</div><div class="viewer-ai-actions"><button class="ai-btn" data-viewer-ai-action="center">打开 AI 页面</button></div>`;
  }

  async function refreshViewerAi({poll = false} = {}) {
    clearTimeout(viewerPollTimer);
    const path = currentPath();
    const button = $('#viewerAiButton');
    const body = $('#viewerAiBody');
    if (!viewer?.open || !path || !button || !body) return;
    try {
      const overview = await getOverview();
      const status = await json(`/api/auto-tag/status?path=${encodeURIComponent(path)}`);
      const model = overview.model || status.model || {};
      button.classList.toggle('busy', status.current === path || (!status.pathIndexed && status.queued > 0));
      button.classList.toggle('hidden', overview.settings?.showViewerButton === false);
      if (!model.installed) {
        body.innerHTML = `<div class="viewer-ai-state">AI 模型尚未安装。完整包会从 EXE 同目录的本地模型包安装，不需要访问国外网站。</div><div class="viewer-ai-actions"><button class="ai-btn primary" data-viewer-ai-action="settings">打开设置</button></div>`;
        return;
      }
      if (!status.pathIndexed) {
        const waiting = status.current === path || status.queued > 0;
        if (!waiting) {
          body.innerHTML = '<div class="viewer-ai-state">当前视频还没有 AI 索引。</div><div class="viewer-ai-actions"><button class="ai-btn primary" data-viewer-ai-action="analyze">分析当前视频</button><button class="ai-btn" data-viewer-ai-action="center">打开 AI 页面</button></div>';
          return;
        }
        const state = status.io?.seeking ? '正在拖动进度条，AI 已让路' : status.io?.playing ? '视频正在播放，AI 以低负载继续分析' : '正在分析当前视频';
        body.innerHTML = `<div class="viewer-ai-state">${state}…</div>`;
        viewerPollTimer = setTimeout(() => refreshViewerAi({poll:true}), 900);
        return;
      }
      const suggestions = await json(`/api/auto-tag/suggestions?path=${encodeURIComponent(path)}`);
      renderViewerSuggestions(suggestions.items || [], status);
    } catch (error) {
      body.innerHTML = `<div class="viewer-ai-state">${escapeHtml(error.message || error)}</div>`;
      if (poll) viewerPollTimer = setTimeout(() => refreshViewerAi({poll:true}), 1800);
    }
  }

  function openViewerAi() {
    const popover = $('#viewerAiPopover');
    const body = $('#viewerAiBody');
    if (!popover || !body) return;
    popover.classList.remove('hidden');
    body.innerHTML = '正在读取 AI 状态…';
    refreshViewerAi();
  }

  document.addEventListener('click', async event => {
    const actionButton = event.target.closest?.('[data-viewer-ai-action]');
    if (actionButton) {
      event.preventDefault();
      event.stopPropagation();
      const action = actionButton.dataset.viewerAiAction;
      try {
        if (action === 'settings') openSettings();
        else if (action === 'center') { $('#viewerAiPopover')?.classList.add('hidden'); if (viewer?.open) $('#closeViewer')?.click(); openAiCenter(); }
        else if (action === 'analyze' || action === 'reanalyze') {
          const path = currentPath();
          if (!path) return;
          await post('/api/auto-tag/queue', {path});
          refreshViewerAi({poll:true});
        }
      } catch (error) { toast(error.message || String(error)); }
      return;
    }

    const accept = event.target.closest?.('[data-viewer-ai-accept]');
    if (accept) {
      event.preventDefault();
      event.stopPropagation();
      const path = currentPath();
      const tag = decodeURIComponent(accept.dataset.viewerAiAccept || '');
      if (!path || !tag) return;
      try {
        await post('/api/manage', {action:'set_tags', paths:[path], tags:[tag], mode:'add'});
        await post('/api/auto-tag/feedback', {path, tag, value:1});
        addViewerTag(tag);
        accept.closest('.viewer-ai-chip')?.remove();
        toast(`已添加 #${tag}`);
      } catch (error) { toast(error.message || String(error)); }
      return;
    }

    const reject = event.target.closest?.('[data-viewer-ai-reject]');
    if (reject) {
      event.preventDefault();
      event.stopPropagation();
      const path = currentPath();
      const tag = decodeURIComponent(reject.dataset.viewerAiReject || '');
      if (!path || !tag) return;
      try {
        await post('/api/auto-tag/feedback', {path, tag, value:-1});
        reject.closest('.viewer-ai-chip')?.remove();
      } catch (error) { toast(error.message || String(error)); }
    }
  }, true);

  function ensureSettingsDialog() {
    let dialog = $('#aiSettingsDialog');
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'aiSettingsDialog';
    dialog.className = 'ai-settings-dialog';
    dialog.innerHTML = `
      <div class="ai-settings-shell">
        <header class="ai-settings-head"><h2>LocalHub 设置</h2><button type="button" data-ai-settings-close>×</button></header>
        <div id="aiSettingsBody" class="ai-settings-body"></div>
        <footer class="ai-settings-foot">
          <button class="ai-btn" type="button" data-ai-settings-reset>恢复默认</button>
          <div><button class="ai-btn" type="button" data-ai-settings-close>取消</button><button class="ai-btn primary" type="button" data-ai-settings-save>保存设置</button></div>
        </footer>
      </div>`;
    document.body.appendChild(dialog);
    dialog.addEventListener('click', event => {
      if (event.target.closest('[data-ai-settings-close]')) dialog.close();
    });
    return dialog;
  }

  function groupEditor(group, groupIndex) {
    const tags = (group.tags || []).map((tag, tagIndex) => `
      <div class="ai-tag-row" data-ai-tag-row data-group-index="${groupIndex}" data-tag-index="${tagIndex}">
        <input type="text" data-ai-tag-name value="${escapeHtml(tag.tag)}" placeholder="Tag 名称">
        <textarea data-ai-tag-prompts placeholder="英文语义词 / 句子，每行一条">${escapeHtml((tag.prompts || []).join('\n'))}</textarea>
        <button type="button" class="remove" data-ai-remove-tag title="删除 Tag">×</button>
      </div>`).join('');
    return `
      <details class="ai-group-editor" data-ai-group data-group-index="${groupIndex}" ${groupIndex < 2 ? 'open' : ''}>
        <summary><input type="checkbox" data-ai-group-enabled ${group.enabled ? 'checked' : ''}><strong>${escapeHtml(group.name)}</strong><span>${(group.tags || []).length} 个 Tag</span></summary>
        <div class="ai-group-content">
          <div class="ai-group-meta"><label>分类名称</label><input type="text" data-ai-group-name value="${escapeHtml(group.name)}"></div>
          <div data-ai-tag-list>${tags}</div>
          <button type="button" class="ai-add-tag" data-ai-add-tag>＋ 添加 Tag</button>
        </div>
      </details>`;
  }

  function renderSettings(settings, overview) {
    const body = $('#aiSettingsBody');
    if (!body) return;
    const model = overview?.model || {};
    const modelText = model.installed
      ? `已安装 · ${escapeHtml(model.modelDir || model.path || '本机 LocalAppData')}`
      : model.localPackageAvailable ? '已找到 EXE 同目录离线模型包' : '未找到离线模型包';
    body.innerHTML = `
      <section class="ai-settings-section">
        <h3>AI 模型</h3>
        <div class="ai-setting-row"><div><label>SigLIP 本地模型</label><small>安装成功后移入本机 LocalAppData；完整校验通过后删除 EXE 同目录模型包。</small></div><div><div class="ai-muted">${modelText}</div><div style="margin-top:8px;display:flex;gap:7px">${!model.installed ? '<button type="button" class="ai-btn primary" data-settings-model="install">安装本地模型</button>' : '<button type="button" class="ai-btn" data-settings-model="unload">释放 AI 模型内存</button>'}</div></div></div>
      </section>
      <section class="ai-settings-section">
        <h3>后台分析</h3>
        <div class="ai-setting-row"><div><label>自动分析媒体库</label><small>安装模型后自动把尚未建立索引的视频加入后台队列；已缓存的视频不会重复计算。</small></div><div><label><input type="checkbox" id="aiAutoLibrary" ${settings.autoAnalyzeLibrary ? 'checked' : ''}> 自动持续分析</label></div></div>
        <div class="ai-setting-row"><div><label>播放时策略</label><small>“均衡”允许视频播放时单线程、低优先级抽帧；拖动进度条时仍会立即暂停 AI。</small></div><div><select id="aiBackgroundMode"><option value="balanced" ${settings.backgroundMode === 'balanced' ? 'selected' : ''}>均衡：边播边低负载分析</option><option value="idle" ${settings.backgroundMode === 'idle' ? 'selected' : ''}>保守：仅空闲时分析</option></select></div></div>
        <div class="ai-setting-row"><div><label>播放器 AI 按钮</label><small>播放器只显示一个小按钮，不再常驻整块 AI 面板。</small></div><div><label><input type="checkbox" id="aiViewerButton" ${settings.showViewerButton !== false ? 'checked' : ''}> 显示“AI 分析”按钮</label></div></div>
      </section>
      <section class="ai-settings-section">
        <h3>Tag 分类与英文语义词</h3>
        <p class="ai-muted">启用的组会共同组成 SigLIP 的候选 Tag。中文是最终写入 LocalHub 的标签；右侧英文用于视觉语义匹配，可自由增删修改。</p>
        <div id="aiGroupEditors" style="display:grid;gap:9px">${(settings.groups || []).map(groupEditor).join('')}</div>
      </section>`;
  }

  function addTagRow(groupEditorNode) {
    const list = groupEditorNode.querySelector('[data-ai-tag-list]');
    if (!list) return;
    const row = document.createElement('div');
    row.className = 'ai-tag-row';
    row.dataset.aiTagRow = '';
    row.innerHTML = '<input type="text" data-ai-tag-name placeholder="Tag 名称"><textarea data-ai-tag-prompts placeholder="英文语义词 / 句子，每行一条">A video frame related to this tag.</textarea><button type="button" class="remove" data-ai-remove-tag title="删除 Tag">×</button>';
    list.appendChild(row);
    row.querySelector('[data-ai-tag-name]')?.focus();
  }

  function collectSettings() {
    const groups = $$('#aiGroupEditors [data-ai-group]').map((groupNode, index) => ({
      id: settingsCache?.groups?.[index]?.id || `group-${index+1}`,
      name: (groupNode.querySelector('[data-ai-group-name]')?.value || `分类${index+1}`).trim(),
      enabled: !!groupNode.querySelector('[data-ai-group-enabled]')?.checked,
      tags: [...groupNode.querySelectorAll('[data-ai-tag-row]')].map(row => ({
        tag: (row.querySelector('[data-ai-tag-name]')?.value || '').trim(),
        prompts: (row.querySelector('[data-ai-tag-prompts]')?.value || '').split(/\r?\n/).map(value => value.trim()).filter(Boolean),
      })).filter(row => row.tag),
    }));
    return {
      version: 1,
      autoAnalyzeLibrary: !!$('#aiAutoLibrary')?.checked,
      backgroundMode: $('#aiBackgroundMode')?.value || 'balanced',
      showViewerButton: !!$('#aiViewerButton')?.checked,
      onboardingCompleted: settingsCache?.onboardingCompleted !== false,
      aiOptIn: settingsCache?.aiOptIn === true,
      groups,
    };
  }

  async function openSettings() {
    const dialog = ensureSettingsDialog();
    const body = $('#aiSettingsBody');
    if (body) body.innerHTML = '<p class="ai-muted">正在读取设置…</p>';
    if (!dialog.open) dialog.showModal();
    try {
      const overview = await getOverview();
      settingsCache = overview.settings;
      renderSettings(settingsCache, overview);
    } catch (error) {
      if (body) body.innerHTML = `<p class="ai-muted">${escapeHtml(error.message || error)}</p>`;
    }
  }

  document.addEventListener('click', async event => {
    const add = event.target.closest?.('[data-ai-add-tag]');
    if (add) { event.preventDefault(); addTagRow(add.closest('[data-ai-group]')); return; }
    const remove = event.target.closest?.('[data-ai-remove-tag]');
    if (remove) { event.preventDefault(); remove.closest('[data-ai-tag-row]')?.remove(); return; }

    const modelButton = event.target.closest?.('[data-settings-model]');
    if (modelButton) {
      event.preventDefault();
      try {
        modelButton.disabled = true;
        if (modelButton.dataset.settingsModel === 'install') {
          await post('/api/auto-tag/model', {action:'install'});
          toast('正在安装本地 AI 模型');
          startInstallPolling();
        } else {
          await post('/api/auto-tag/model', {action:'unload'});
          toast('AI 模型内存已释放');
          openSettings();
        }
      } catch (error) { toast(error.message || String(error)); }
      finally { modelButton.disabled = false; }
      return;
    }

    if (event.target.closest?.('[data-ai-settings-save]')) {
      event.preventDefault();
      try {
        const saved = await post('/api/ai/settings', {action:'save', settings:collectSettings()});
        settingsCache = saved.settings;
        $('#aiSettingsDialog')?.close();
        toast('AI / Tag 设置已保存');
        refreshViewerButtonVisibility();
        if (aiPageActive) refreshAiPage();
      } catch (error) { toast(error.message || String(error)); }
      return;
    }

    if (event.target.closest?.('[data-ai-settings-reset]')) {
      event.preventDefault();
      try {
        const reset = await post('/api/ai/settings', {action:'reset'});
        settingsCache = reset.settings;
        renderSettings(settingsCache, await getOverview());
        toast('已恢复默认 Tag 组');
      } catch (error) { toast(error.message || String(error)); }
    }
  }, true);

  function startInstallPolling() {
    clearTimeout(installPollTimer);
    const tick = async () => {
      try {
        const overview = await getOverview();
        settingsCache = overview.settings;
        if ($('#aiSettingsDialog')?.open) renderSettings(settingsCache, overview);
        if (aiPageActive) renderAiPage(overview);
        if (overview.model?.installed) {
          toast('本地 AI 模型安装完成');
          if (overview.settings?.autoAnalyzeLibrary) {
            await post('/api/auto-tag/library', {action:'start'}).catch(() => {});
          }
          refreshViewerButtonVisibility();
          return;
        }
        if (overview.model?.installing) installPollTimer = setTimeout(tick, 900);
      } catch { installPollTimer = setTimeout(tick, 1800); }
    };
    tick();
  }

  async function refreshViewerButtonVisibility() {
    const button = $('#viewerAiButton');
    if (!button) return;
    try {
      const overview = overviewCache || await getOverview();
      button.classList.toggle('hidden', overview.settings?.showViewerButton === false);
    } catch {}
  }

  document.addEventListener('click', event => {
    const main = event.target.closest?.('.main-nav button');
    if (main && main.id !== 'aiCenterNav') leaveAiPage();
  }, true);
  searchInput?.addEventListener('input', () => leaveAiPage(), true);
  viewer?.addEventListener('close', () => {
    clearTimeout(viewerPollTimer);
    $('#viewerAiPopover')?.classList.add('hidden');
  });
  if (viewerPath) new MutationObserver(() => {
    clearTimeout(viewerPollTimer);
    $('#viewerAiPopover')?.classList.add('hidden');
    refreshViewerButtonVisibility();
  }).observe(viewerPath, {subtree:true, childList:true, characterData:true});

  installNav();
  installAccountMenu();
  installViewerButton();
  refreshViewerButtonVisibility();
})();
