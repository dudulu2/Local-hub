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
  let profileCache = null;

  async function json(url, opt = {}) {
    const response = await fetch(url, {cache:'no-store', ...opt});
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function post(url, payload) {
    return json(url, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  }

  function currentPath() { return (pathNode.textContent || '').trim(); }
  function esc(value) { return String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

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

  function stopHeartbeat() { clearInterval(heartbeatTimer); heartbeatTimer = null; }
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

  function ensurePanel() {
    let panel = $('#autoTagPanel');
    if (panel) return panel;
    panel = document.createElement('section');
    panel.id = 'autoTagPanel';
    panel.className = 'autotag-panel';
    panel.innerHTML = `<div class="autotag-head"><div><b>AI Tag</b><span>第一次见你就会整理，用得越久越懂你</span></div><span id="autoTagState" class="autotag-state"></span></div><div id="autoTagSuggestions" class="autotag-suggestions"></div><div id="autoTagActions" class="autotag-actions"></div>`;
    tagStrip.insertAdjacentElement('afterend', panel);
    return panel;
  }

  function setPanel(state, suggestions = '', actions = '') {
    ensurePanel();
    $('#autoTagState').textContent = state || '';
    $('#autoTagSuggestions').innerHTML = suggestions;
    $('#autoTagActions').innerHTML = actions;
  }

  function button(label, action, primary = false) {
    return `<button type="button" class="autotag-btn${primary ? ' primary' : ''}" data-auto-action="${action}">${label}</button>`;
  }

  async function loadProfile() {
    const data = await json('/api/auto-tag/profile');
    profileCache = data;
    return data;
  }

  function starterMarkup(data) {
    const packs = data.packs || [];
    return `<div class="autotag-onboard"><b>这里主要存放什么类型的视频？</b><small>选择后会准备一套可修改的初始 Tag，以后随时可以更换。</small><div class="autotag-pack-grid">${packs.map(p=>`<button type="button" class="autotag-pack" data-auto-pack="${esc(p.id)}"><b>${esc(p.label)}</b><span>${p.tagCount} 个初始 Tag</span></button>`).join('')}</div></div>`;
  }

  function profileEditorMarkup(profile) {
    const tags = profile.tags || [];
    return `<div class="autotag-profile"><div class="autotag-profile-title"><b>${esc(profile.packLabel || 'Tag 组合')}</b><button type="button" class="autotag-link" data-auto-action="change-pack">更换类型</button></div><small>Tag 和解释都可以修改。AI 会优先按这套规则判断。</small><div class="autotag-profile-list">${tags.map((row,i)=>`<div class="autotag-profile-row"><input data-auto-tag-name="${i}" value="${esc(row.tag)}" maxlength="48"><input data-auto-tag-desc="${i}" value="${esc(row.description || '')}" maxlength="400" placeholder="这个 Tag 对你意味着什么"><button type="button" data-auto-tag-remove="${i}">×</button></div>`).join('')}</div><button type="button" class="autotag-btn" data-auto-action="add-profile-tag">＋ 添加 Tag</button></div>`;
  }

  async function showProfileSetup(forcePacks = false) {
    const data = profileCache || await loadProfile();
    if (forcePacks || !data.profile?.configured) {
      setPanel('设置分类方式', starterMarkup(data), '');
      return true;
    }
    setPanel('Tag 组合', profileEditorMarkup(data.profile), `${button('保存 Tag 组合', 'save-profile', true)}${button('开始一键分析', 'library-start')}`);
    return true;
  }

  function readProfileRows() {
    const rows = [];
    document.querySelectorAll('[data-auto-tag-name]').forEach(input => {
      const i = input.dataset.autoTagName;
      const tag = input.value.trim();
      const desc = document.querySelector(`[data-auto-tag-desc="${i}"]`)?.value.trim() || '';
      if (tag) rows.push({tag, description:desc});
    });
    return rows;
  }

  function addViewerTag(tag) {
    const add = $('#viewerTagAdd') || tagStrip.querySelector('.viewer-tag-add');
    if ([...tagStrip.querySelectorAll('[data-viewer-tag]')].some(n => (n.dataset.viewerTag || '').toLowerCase() === tag.toLowerCase())) return;
    tagStrip.querySelector('.viewer-no-tags')?.remove();
    const chip = document.createElement('button');
    chip.type = 'button'; chip.className = 'viewer-tag-chip'; chip.dataset.viewerTag = tag; chip.textContent = `#${tag}`;
    tagStrip.insertBefore(chip, add || null);
  }

  async function loadSuggestions(path, token) {
    const data = await json(`/api/auto-tag/suggestions?path=${encodeURIComponent(path)}`);
    if (token !== uiToken || currentPath() !== path) return;
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) {
      setPanel('已分析', '<span class="autotag-empty">暂时没有足够可靠的建议</span>', `${button('编辑 Tag 组合','profile')}${button('重新分析','analyze')}`);
      return;
    }
    const markup = items.map((item,index)=>`<div class="autotag-suggestion" data-auto-index="${index}"><button type="button" class="autotag-accept" data-auto-tag="${encodeURIComponent(item.tag)}">＋ #${esc(item.tag)}</button><span title="未校准排序分数，不代表概率">${Number(item.score ?? item.confidence ?? 0).toFixed(3)}</span><button type="button" class="autotag-reject" data-auto-reject="${encodeURIComponent(item.tag)}">×</button></div>`).join('');
    setPanel('建议 Tag', markup, `${button('编辑 Tag 组合','profile')}${button('分析新视频','new-media')}${button('空闲时分析全库','library-start')}`);
  }

  async function refreshPanel({poll=false}={}) {
    clearTimeout(uiPollTimer);
    const path = currentPath();
    if (!viewer.open || !path) return;
    const token = ++uiToken;
    try {
      const profileData = await loadProfile();
      if (!profileData.profile?.configured) return showProfileSetup();
      const status = await json(`/api/auto-tag/status?path=${encodeURIComponent(path)}`);
      if (token !== uiToken || currentPath() !== path) return;
      const model = status.model || {};
      if (!model.installed) {
        if (model.installing) {
          const pct = model.totalBytes ? Math.min(100, model.downloadedBytes / model.totalBytes * 100) : 0;
          setPanel(`模型下载 ${pct.toFixed(0)}%`, `<div class="autotag-progress"><i style="width:${pct}%"></i></div>`, '');
          uiPollTimer = setTimeout(()=>refreshPanel({poll:true}),900);
        } else {
          setPanel('AI 模型未安装','<span class="autotag-empty">首次使用需要下载本地 SigLIP 模型。模型只保存在本机。</span>',`${button('编辑 Tag 组合','profile')}${button('安装 SigLIP 模型','install',true)}`);
        }
        return;
      }
      if (!status.pathIndexed) {
        const waiting = status.current === path || status.queued > 0;
        if (waiting) {
          setPanel(status.io?.playing || status.io?.seeking ? '已排队 · 播放优先' : '正在分析','<span class="autotag-empty">后台 AI 会主动让位于播放。</span>',button('编辑 Tag 组合','profile'));
          uiPollTimer=setTimeout(()=>refreshPanel({poll:true}),1000);
        } else {
          setPanel('尚未分析','<span class="autotag-empty">使用当前 Tag 组合分析这个视频。</span>',`${button('编辑 Tag 组合','profile')}${button('分析当前视频','analyze',true)}`);
        }
        return;
      }
      await loadSuggestions(path,token);
      if (status.rematchPending > 0) $('#autoTagActions')?.insertAdjacentHTML('beforeend',button(`重新匹配 ${status.rematchPending} 项`,'rematch'));
    } catch (error) {
      if (token !== uiToken) return;
      setPanel('不可用',`<span class="autotag-error">${esc(error.message || error)}</span>`,'');
    }
  }

  document.addEventListener('click', async event => {
    const pack = event.target.closest?.('[data-auto-pack]');
    if (pack) {
      try {
        const data = await post('/api/auto-tag/profile',{action:'select-pack',packId:pack.dataset.autoPack});
        profileCache={...(profileCache||{}),profile:data.profile};
        showProfileSetup();
      } catch (e) { toast(e.message || e); }
      return;
    }

    const remove = event.target.closest?.('[data-auto-tag-remove]');
    if (remove) { remove.closest('.autotag-profile-row')?.remove(); return; }

    const actionButton = event.target.closest?.('[data-auto-action]');
    if (actionButton) {
      event.preventDefault(); event.stopPropagation();
      const action = actionButton.dataset.autoAction;
      const path = currentPath();
      try {
        if (action === 'profile') return showProfileSetup();
        if (action === 'change-pack') return showProfileSetup(true);
        if (action === 'add-profile-tag') {
          const list = $('.autotag-profile-list'); const i = Date.now();
          list?.insertAdjacentHTML('beforeend',`<div class="autotag-profile-row"><input data-auto-tag-name="${i}" maxlength="48" placeholder="Tag"><input data-auto-tag-desc="${i}" maxlength="400" placeholder="这个 Tag 对你意味着什么"><button type="button" data-auto-tag-remove="${i}">×</button></div>`); return;
        }
        if (action === 'save-profile') {
          const data = await post('/api/auto-tag/profile',{action:'update',tags:readProfileRows(),configured:true});
          profileCache={...(profileCache||{}),profile:data.profile}; toast('Tag 组合已保存，现有索引可重新匹配'); return refreshPanel();
        }
        actionButton.disabled = true;
        if (action === 'install') await post('/api/auto-tag/model',{action:'install'});
        else if (action === 'analyze') await post('/api/auto-tag/queue',{path});
        else if (action === 'library-start') { if ($('[data-auto-tag-name]')) await post('/api/auto-tag/profile',{action:'update',tags:readProfileRows(),configured:true}); await post('/api/auto-tag/library',{action:'start'}); }
        else if (action === 'library-pause') await post('/api/auto-tag/library',{action:'pause'});
        else if (action === 'new-media') { const r=await post('/api/auto-tag/new-media',{}); toast(`已排队 ${r.queued||0} 个新视频`); }
        else if (action === 'rematch') { const r=await post('/api/auto-tag/rematch',{}); toast(`已刷新 ${r.count||0} 个已有索引的匹配状态`); }
        refreshPanel({poll:true});
      } catch (error) { toast(error.message || String(error)); actionButton.disabled=false; }
      return;
    }

    const accept = event.target.closest?.('[data-auto-tag]');
    if (accept) {
      const path=currentPath(), tag=decodeURIComponent(accept.dataset.autoTag||''); if(!path||!tag)return;
      try {
        await post('/api/manage',{action:'set_tags',paths:[path],tags:[tag],mode:'add'});
        await post('/api/auto-tag/feedback-v2',{path,tag,value:1}); addViewerTag(tag); accept.closest('.autotag-suggestion')?.remove(); toast(`已添加 #${tag}，并作为正样本学习`);
      } catch(e){toast(e.message||e);} return;
    }

    const reject = event.target.closest?.('[data-auto-reject]');
    if (reject) {
      const path=currentPath(), tag=decodeURIComponent(reject.dataset.autoReject||''); if(!path||!tag)return;
      try { await post('/api/auto-tag/feedback-v2',{path,tag,value:-1}); reject.closest('.autotag-suggestion')?.remove(); toast(`已拒绝 #${tag}，并作为负样本学习`); } catch(e){toast(e.message||e);} return;
    }
  }, true);

  new MutationObserver(()=>{ if(viewer.open&&currentPath()) setTimeout(()=>refreshPanel(),80); }).observe(pathNode,{subtree:true,childList:true,characterData:true});
  viewer.addEventListener('close',()=>{clearTimeout(uiPollTimer);uiToken++;});
})();
