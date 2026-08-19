(() => {
  'use strict';
  if (window.__localhubNativePlayerUI) return;
  window.__localhubNativePlayerUI = true;

  const css = document.createElement('style');
  css.textContent = `
    #nativeViewer{width:min(1180px,96vw);max-width:96vw;height:min(88vh,860px);max-height:94vh;padding:0;border:1px solid #2a2a2d;border-radius:16px;background:#111113;color:#eee;box-shadow:0 28px 90px #000b;overflow:hidden}
    #nativeViewer::backdrop{background:rgba(0,0,0,.76);backdrop-filter:blur(3px)}
    .np-shell{height:100%;display:grid;grid-template-rows:minmax(0,1fr) auto auto;background:#0b0b0c}
    .np-stage{position:relative;min-height:280px;background:#000;display:flex;align-items:center;justify-content:center;overflow:hidden}
    #nativePlayerSlot{position:absolute;inset:0;background:#000}
    .np-stage-message{position:relative;z-index:1;color:#999;font-size:13px;pointer-events:none;text-align:center;padding:20px}
    .np-controls{display:flex;align-items:center;gap:10px;padding:10px 14px;background:#151517;border-top:1px solid #262629}
    .np-controls button,.np-controls select{border:1px solid #343438;background:#202024;color:#eee;border-radius:8px;height:34px;padding:0 10px}
    .np-controls button{cursor:pointer}.np-controls button:hover{background:#2a2a2f}
    .np-controls input[type=range]{accent-color:#ff9700}.np-seek{flex:1;min-width:120px}.np-volume{width:90px}
    .np-time{font-variant-numeric:tabular-nums;color:#bbb;font-size:12px;min-width:42px;text-align:center}
    .np-info{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:13px 18px 16px;background:#111113;border-top:1px solid #222226}
    .np-copy{min-width:0}.np-title{font-size:18px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.np-path{margin-top:5px;color:#777;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.np-diagnostics{margin-top:7px;color:#aaa;font-size:12px}
    .np-mode{flex:0 0 auto;border:1px solid #7f5100;background:#2e1f08;color:#ffb23f;border-radius:999px;padding:4px 9px;font-size:11px}
    .np-close{position:fixed;z-index:3;margin:12px 0 0 calc(min(1180px,96vw) - 50px);width:36px;height:36px;border:0;border-radius:10px;background:#252529;color:#ddd;font-size:22px;cursor:pointer}
    .np-error{color:#ff7f7f}.np-hidden{display:none!important}
    @media(max-width:760px){#nativeViewer{width:100vw;max-width:100vw;height:100vh;max-height:100vh;border-radius:0}.np-stage{min-height:220px}.np-controls{gap:6px;padding:8px}.np-volume{display:none}.np-info{padding:10px 12px}.np-close{right:8px;margin-left:0}}
  `;
  document.head.appendChild(css);

  const dialog = document.createElement('dialog');
  dialog.id = 'nativeViewer';
  dialog.innerHTML = `
    <button class="np-close" type="button" aria-label="关闭">×</button>
    <div class="np-shell">
      <div class="np-stage">
        <div id="nativePlayerSlot"></div>
        <div class="np-stage-message" id="npStageMessage">正在启动 libmpv…</div>
      </div>
      <div class="np-controls">
        <button id="npPlay" type="button" aria-label="播放">▶</button>
        <span class="np-time" id="npCurrent">0:00</span>
        <input id="npSeek" class="np-seek" type="range" min="0" max="1000" value="0" step="1" aria-label="播放进度">
        <span class="np-time" id="npDuration">0:00</span>
        <button id="npMute" type="button" aria-label="静音">🔊</button>
        <input id="npVolume" class="np-volume" type="range" min="0" max="100" value="100" step="1" aria-label="音量">
        <select id="npSpeed" aria-label="倍速"><option value="0.5">0.5×</option><option value="0.75">0.75×</option><option value="1" selected>1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option></select>
        <button id="npFullscreen" type="button" aria-label="全屏">⛶</button>
      </div>
      <div class="np-info">
        <div class="np-copy"><div class="np-title" id="npTitle"></div><div class="np-path" id="npPath"></div><div class="np-diagnostics" id="npDiagnostics">libmpv 原生播放 · 不转码</div></div>
        <div class="np-mode">Native · libmpv</div>
      </div>
    </div>`;
  document.body.appendChild(dialog);

  const $ = s => dialog.querySelector(s);
  const slot = $('#nativePlayerSlot');
  const stageMessage = $('#npStageMessage');
  const play = $('#npPlay');
  const seek = $('#npSeek');
  const current = $('#npCurrent');
  const durationNode = $('#npDuration');
  const volume = $('#npVolume');
  const mute = $('#npMute');
  const speed = $('#npSpeed');
  const diagnostics = $('#npDiagnostics');
  const title = $('#npTitle');
  const pathNode = $('#npPath');
  const closeBtn = dialog.querySelector('.np-close');
  const fullscreen = $('#npFullscreen');

  let activePath = '';
  let pollTimer = 0;
  let state = {time:0,duration:0,paused:true,volume:100,speed:1};
  let dragging = false;
  let mutedBefore = 100;
  let lastProgressWrite = 0;
  let rectTimer = 0;

  const fmt = sec => {
    sec = Math.max(0, Number(sec)||0);
    const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=Math.floor(sec%60);
    return h?`${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`:`${m}:${String(s).padStart(2,'0')}`;
  };
  const bridge = () => window.pywebview?.api || null;
  const toast = text => {
    const t=document.querySelector('#toast'); if(!t)return;
    t.textContent=text;t.classList.add('show');clearTimeout(toast.t);toast.t=setTimeout(()=>t.classList.remove('show'),2200);
  };
  const readProgress = path => {
    try { return Number(JSON.parse(localStorage.getItem('localhub:progress')||'{}')?.[path]?.time)||0; } catch { return 0; }
  };
  const saveProgress = force => {
    if(!activePath||!state.duration)return;
    const now=Date.now();if(!force&&now-lastProgressWrite<2500)return;lastProgressWrite=now;
    try{
      const all=JSON.parse(localStorage.getItem('localhub:progress')||'{}');
      all[activePath]={time:Number(state.time)||0,duration:Number(state.duration)||0,at:now};
      localStorage.setItem('localhub:progress',JSON.stringify(all));
    }catch{}
  };

  async function syncRect(visible=dialog.open){
    const api=bridge();if(!api||!slot)return;
    const r=slot.getBoundingClientRect();
    if(r.width<2||r.height<2)visible=false;
    try{await api.player_rect(r.left,r.top,r.width,r.height,!!visible&&!document.hidden);}catch{}
  }
  const scheduleRect=()=>{clearTimeout(rectTimer);rectTimer=setTimeout(()=>void syncRect(),30);};
  new ResizeObserver(scheduleRect).observe(slot);
  addEventListener('resize',scheduleRect);
  addEventListener('scroll',scheduleRect,true);
  document.addEventListener('fullscreenchange',()=>{setTimeout(scheduleRect,40);setTimeout(scheduleRect,260);});
  document.addEventListener('visibilitychange',()=>void syncRect(dialog.open&&!document.hidden));

  function updateUI(s){
    state={...state,...s};
    play.textContent=state.paused?'▶':'❚❚';
    if(!dragging){seek.value=state.duration>0?String(Math.round(Math.max(0,Math.min(1,state.time/state.duration))*1000)):'0';current.textContent=fmt(state.time);}
    durationNode.textContent=fmt(state.duration);
    volume.value=String(Math.round(state.volume??100));
    mute.textContent=(state.volume||0)<=0?'🔇':((state.volume||0)<45?'🔉':'🔊');
    if(Math.abs(Number(speed.value)-Number(state.speed||1))>.01)speed.value=String(state.speed||1);
    const info=[state.videoCodec,state.videoFormat,state.width&&state.height?`${state.width}×${state.height}`:'',state.hwdec?`硬解 ${state.hwdec}`:''].filter(Boolean);
    diagnostics.textContent=info.length?`libmpv 原生播放 · ${info.join(' · ')}`:'libmpv 原生播放 · 不转码';
    diagnostics.classList.remove('np-error');
    stageMessage.classList.toggle('np-hidden',!!state.ready);
    if(!state.ready)stageMessage.textContent='libmpv 正在打开视频…';
  }

  async function poll(){
    if(!dialog.open)return;
    const api=bridge();if(!api){stageMessage.textContent='WebView2 原生桥尚未准备好';return;}
    try{
      const r=await api.player_status();
      if(!r?.ok){diagnostics.textContent=r?.error||'libmpv 不可用';diagnostics.classList.add('np-error');stageMessage.textContent=r?.error||'libmpv 不可用';return;}
      updateUI(r.state||{});saveProgress(false);
    }catch(e){diagnostics.textContent=`原生播放器通信失败：${e}`;diagnostics.classList.add('np-error');}
  }

  async function openNative(card){
    const api=bridge();
    if(!api){toast('原生播放器正在初始化，请稍后再试');return;}
    const path=String(card.dataset.id||'').trim();if(!path)return;
    activePath=path;
    title.textContent=card.querySelector('.card-title')?.textContent?.trim()||path.split('/').pop()||path;
    pathNode.textContent=path;
    diagnostics.textContent='libmpv 原生播放 · 不转码';diagnostics.classList.remove('np-error');
    stageMessage.textContent='正在启动 libmpv…';stageMessage.classList.remove('np-hidden');
    state={time:0,duration:0,paused:true,volume:100,speed:1};
    if(!dialog.open)dialog.showModal();
    await syncRect(true);
    const resume=readProgress(path);
    try{
      const result=await api.player_load(path,resume);
      if(!result?.ok)throw new Error(result?.error||'libmpv 加载失败');
      clearInterval(pollTimer);pollTimer=setInterval(()=>void poll(),220);
      await poll();
      toast('libmpv 已接管播放');
    }catch(e){
      diagnostics.textContent=String(e?.message||e);diagnostics.classList.add('np-error');
      stageMessage.textContent=String(e?.message||e);
    }
  }

  async function closeNative(){
    saveProgress(true);clearInterval(pollTimer);pollTimer=0;
    const api=bridge();
    try{await api?.player_stop();}catch{}
    await syncRect(false);
    activePath='';
    if(dialog.open)dialog.close();
  }

  document.addEventListener('click',e=>{
    if(dialog.open)return;
    if(e.target.closest('[data-fav],[data-edit-tags],[data-tag],button,input,select,a'))return;
    const card=e.target.closest('.card[data-id]');
    if(!card||!card.querySelector('.video-thumb'))return;
    e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();
    void openNative(card);
  },true);

  closeBtn.addEventListener('click',()=>void closeNative());
  dialog.addEventListener('cancel',e=>{e.preventDefault();void closeNative();});
  dialog.addEventListener('close',()=>void syncRect(false));
  play.addEventListener('click',()=>void bridge()?.player_toggle_pause());
  seek.addEventListener('pointerdown',()=>{dragging=true;});
  seek.addEventListener('input',()=>{if(state.duration>0)current.textContent=fmt(Number(seek.value)/1000*state.duration);});
  seek.addEventListener('change',()=>{dragging=false;if(state.duration>0)void bridge()?.player_seek(Number(seek.value)/1000*state.duration);});
  seek.addEventListener('pointerup',()=>{dragging=false;});
  volume.addEventListener('input',()=>{const v=Number(volume.value)||0;if(v>0)mutedBefore=v;void bridge()?.player_volume(v);});
  mute.addEventListener('click',()=>{const next=(state.volume||0)>0?0:(mutedBefore||80);void bridge()?.player_volume(next);});
  speed.addEventListener('change',()=>void bridge()?.player_speed(Number(speed.value)||1));
  fullscreen.addEventListener('click',async()=>{try{await bridge()?.player_fullscreen();setTimeout(scheduleRect,120);}catch{}});
  document.addEventListener('keydown',e=>{
    if(!dialog.open)return;
    if(e.target.matches('input,select,textarea'))return;
    if(e.code==='Space'){e.preventDefault();void bridge()?.player_toggle_pause();}
    else if(e.key==='ArrowLeft'){e.preventDefault();void bridge()?.player_seek_relative(-5);}
    else if(e.key==='ArrowRight'){e.preventDefault();void bridge()?.player_seek_relative(5);}
  },true);

  window.addEventListener('beforeunload',()=>{if(activePath){saveProgress(true);try{bridge()?.player_stop();}catch{}}});
})();
