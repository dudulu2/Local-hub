(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  let overlay = null;
  let overview = null;
  let polling = false;

  async function json(url, opt = {}) {
    const response = await fetch(url, {cache:'no-store', ...opt});
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  const post = (url, payload) => json(url, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload),
  });

  function bytes(value) {
    let size = Math.max(0, Number(value) || 0);
    const units = ['B','KB','MB','GB'];
    let i = 0;
    while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
    return `${i === 0 || size >= 10 ? size.toFixed(0) : size.toFixed(1)} ${units[i]}`;
  }

  function icon(kind) {
    const paths = {
      tag: '<path d="M4 4h7l9 9-7 7-9-9V4Zm4 3.2a1.8 1.8 0 1 0 0 3.6 1.8 1.8 0 0 0 0-3.6Z"/>',
      local: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H13v2h3v2H8v-2h3v-2H6.5A2.5 2.5 0 0 1 4 13.5v-8Zm2 0v8c0 .28.22.5.5.5h11a.5.5 0 0 0 .5-.5v-8a.5.5 0 0 0-.5-.5h-11a.5.5 0 0 0-.5.5Z"/>',
      background: '<path d="M12 2a10 10 0 1 0 10 10h-2a8 8 0 1 1-2.34-5.66L15 9h7V2l-2.93 2.93A9.96 9.96 0 0 0 12 2Zm-1 5v6l5 3 .9-1.65-3.9-2.3V7h-2Z"/>',
      privacy: '<path d="M12 2 4 5v6c0 5.05 3.41 9.74 8 11 4.59-1.26 8-5.95 8-11V5l-8-3Zm0 2.13L18 6.4V11c0 3.92-2.5 7.73-6 8.87C8.5 18.73 6 14.92 6 11V6.4l6-2.27Zm-1 4.37v3.09L8.79 13.8l1.42 1.41L12 13.41l1.79 1.8 1.42-1.41L13 11.59V8.5h-2Z"/>'
    };
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[kind] || paths.tag}</svg>`;
  }

  function ensureOverlay() {
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.id = 'aiFirstRun';
    overlay.className = 'ai-first-run hidden';
    overlay.innerHTML = `
      <section class="ai-first-card" role="dialog" aria-modal="true" aria-labelledby="aiFirstTitle">
        <div class="ai-first-brand"><span>LOCAL</span><b>HUB</b><em>AI Tag</em></div>
        <h1 id="aiFirstTitle">让本地视频自动变得更好找</h1>
        <p class="ai-first-lead">AI Tag 会从每个视频抽取少量代表画面，在你的电脑上识别内容并建立可搜索的 Tag。视频和分析结果都留在本机。</p>

        <div class="ai-first-features">
          <article><i>${icon('tag')}</i><div><strong>自动 Tag 与分类</strong><span>按生活、学习、风景、娱乐等分类生成建议，也可以在设置里修改 Tag 和英文语义词。</span></div></article>
          <article><i>${icon('local')}</i><div><strong>模型完全从本地安装</strong><span>使用 EXE 同目录的 LocalHub-AI-Model，不需要下载模型；安装校验成功后会自动删除这个模型文件夹。</span></div></article>
          <article><i>${icon('background')}</i><div><strong>后台持续分析</strong><span>可以一边看视频一边低负载分析全库；拖动进度条时 AI 会主动让路，已经完成的视频不会重复计算。</span></div></article>
          <article><i>${icon('privacy')}</i><div><strong>完全离线，不连接互联网</strong><span>LocalHub 只允许访问本机 127.0.0.1 / localhost / ::1。程序不会上传媒体、Tag、文件名或使用数据，外部网络连接会被程序内部直接阻止。</span></div></article>
        </div>

        <div id="aiFirstProgress" class="ai-first-progress hidden">
          <div class="ai-first-progress-head"><strong id="aiFirstProgressTitle">正在准备本地 AI</strong><span id="aiFirstProgressPct">0%</span></div>
          <div class="ai-first-track"><i id="aiFirstProgressBar"></i></div>
          <p id="aiFirstProgressText">正在检查 LocalHub-AI-Model…</p>
        </div>
        <div id="aiFirstError" class="ai-first-error hidden"></div>

        <div class="ai-first-actions">
          <button type="button" id="aiFirstSkip" class="ai-first-secondary">跳过</button>
          <button type="button" id="aiFirstStart" class="ai-first-primary">开始 AI 功能</button>
        </div>
        <p class="ai-first-foot">之后仍可在右上角头像 → 设置中调整 AI 和 Tag 选项。</p>
      </section>`;
    document.body.appendChild(overlay);
    $('#aiFirstStart')?.addEventListener('click', startAI);
    $('#aiFirstSkip')?.addEventListener('click', skipAI);
    return overlay;
  }

  function setError(message = '') {
    const node = $('#aiFirstError');
    if (!node) return;
    node.textContent = message;
    node.classList.toggle('hidden', !message);
  }

  function showProgress(title, downloaded, total, text) {
    $('#aiFirstProgress')?.classList.remove('hidden');
    const pct = total > 0 ? Math.max(0, Math.min(100, downloaded / total * 100)) : 0;
    const titleNode = $('#aiFirstProgressTitle');
    const pctNode = $('#aiFirstProgressPct');
    const bar = $('#aiFirstProgressBar');
    const detail = $('#aiFirstProgressText');
    if (titleNode) titleNode.textContent = title;
    if (pctNode) pctNode.textContent = `${pct.toFixed(pct >= 10 ? 0 : 1)}%`;
    if (bar) bar.style.width = `${pct}%`;
    if (detail) detail.textContent = text || `${bytes(downloaded)} / ${bytes(total)}`;
  }

  async function saveDecision(optedIn) {
    const current = overview?.settings || (await json('/api/ai/overview')).settings || {};
    const settings = {
      ...current,
      onboardingCompleted: true,
      aiOptIn: !!optedIn,
      autoAnalyzeLibrary: !!optedIn,
      showViewerButton: !!optedIn,
    };
    const saved = await post('/api/ai/settings', {action:'save', settings});
    overview = {...(overview || {}), settings:saved.settings};
  }

  async function pollInstall() {
    polling = true;
    while (polling) {
      const data = await json('/api/auto-tag/model');
      const downloaded = Math.max(0, Number(data.downloadedBytes) || 0);
      const total = Math.max(1, Number(data.totalBytes) || 1);
      if (data.error) throw new Error(data.error);
      if (data.installed) {
        showProgress('本地 AI 已安装', total, total, '模型校验完成，正在启用 AI Tag…');
        return data;
      }
      showProgress(
        '正在安装本地 AI',
        downloaded,
        total,
        data.currentFile ? `正在安装 ${data.currentFile} · ${bytes(downloaded)} / ${bytes(total)}` : `正在校验本地模型 · ${bytes(downloaded)} / ${bytes(total)}`
      );
      await new Promise(resolve => setTimeout(resolve, 260));
    }
    throw new Error('安装已取消');
  }

  async function startAI() {
    const start = $('#aiFirstStart');
    const skip = $('#aiFirstSkip');
    if (start?.disabled) return;
    setError('');
    if (start) start.disabled = true;
    if (skip) skip.disabled = true;
    try {
      overview = await json('/api/ai/overview');
      let model = overview.model || {};
      if (!model.installed) {
        if (!model.localPackageAvailable) {
          throw new Error('没有找到 LocalHub-AI-Model。请把这个文件夹与 LocalHub.exe 放在同一个目录后再点击“开始 AI 功能”。');
        }
        showProgress('正在准备本地 AI', 0, Number(model.totalBytes) || 1, '正在检查 LocalHub-AI-Model…');
        await post('/api/auto-tag/model', {action:'install'});
        model = await pollInstall();
      }
      await post('/api/auto-tag/model', {action:'enable'});
      await saveDecision(true);
      await post('/api/auto-tag/library', {action:'start'});
      showProgress('AI Tag 已启用', 1, 1, '完成。LocalHub 将在后台逐步分析整个媒体库。');
      document.dispatchEvent(new CustomEvent('localhub-ai-onboarding-complete', {detail:{enabled:true}}));
      setTimeout(() => overlay?.classList.add('hidden'), 850);
    } catch (error) {
      polling = false;
      setError(error.message || String(error));
      if (start) start.disabled = false;
      if (skip) skip.disabled = false;
    }
  }

  async function skipAI() {
    const start = $('#aiFirstStart');
    const skip = $('#aiFirstSkip');
    if (skip?.disabled) return;
    if (start) start.disabled = true;
    if (skip) skip.disabled = true;
    setError('');
    try {
      overview = overview || await json('/api/ai/overview');
      await post('/api/auto-tag/library', {action:'pause'}).catch(() => {});
      await post('/api/auto-tag/model', {action:'unload'}).catch(() => {});
      await saveDecision(false);
      document.dispatchEvent(new CustomEvent('localhub-ai-onboarding-complete', {detail:{enabled:false}}));
      overlay?.classList.add('hidden');
    } catch (error) {
      setError(error.message || String(error));
      if (start) start.disabled = false;
      if (skip) skip.disabled = false;
    }
  }

  async function boot() {
    try {
      overview = await json('/api/ai/overview');
      if (overview.settings?.onboardingCompleted) return;
      ensureOverlay().classList.remove('hidden');
    } catch {
      // AI onboarding is optional. A status failure must never block LocalHub.
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true});
  else boot();
})();
