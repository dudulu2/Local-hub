// LH_PORTRAIT_HARD_FIT_V2
(() => {
  'use strict';
  const viewer = document.querySelector('#viewer');
  const stage = document.querySelector('#viewerStage');
  const video = document.querySelector('#videoPlayer');
  const diagnostics = document.querySelector('#mediaDiagnostics');
  const pathNode = document.querySelector('#viewerPath');
  if (!viewer || !stage || !video || !pathNode) return;

  let hardApplied = false;
  let scheduled = 0;

  function diagnosticGeometry() {
    const text = (diagnostics?.textContent || '').trim();
    const match = text.match(/(\d{2,5})\s*[×x]\s*(\d{2,5})/i);
    if (!match) return null;
    const width = Number(match[1]) || 0;
    const height = Number(match[2]) || 0;
    return width && height ? {width, height} : null;
  }

  function intrinsicGeometry() {
    const width = Number(video.videoWidth) || 0;
    const height = Number(video.videoHeight) || 0;
    return width && height ? {width, height} : null;
  }

  function clearHardFit() {
    if (!hardApplied) return;
    hardApplied = false;
    stage.classList.remove('lh-hard-portrait');
    for (const prop of ['position','left','top','transform','margin','min-width','min-height']) video.style.removeProperty(prop);
    for (const prop of ['width','height','max-width','max-height','aspect-ratio','object-fit','object-position']) video.style.removeProperty(prop);
  }

  function applyHardPortrait() {
    scheduled = 0;
    if (!viewer.open) return;
    const diagnostic = diagnosticGeometry();
    const intrinsic = intrinsicGeometry();
    const g = diagnostic || intrinsic;
    if (!g || g.height <= g.width * 1.08) return;

    const widthAvailable = Math.max(1, stage.clientWidth || 0);
    const heightAvailable = Math.max(1, stage.clientHeight || 0);
    if (widthAvailable <= 1 || heightAvailable <= 1) return;

    const scale = Math.min(widthAvailable / g.width, heightAvailable / g.height);
    if (!Number.isFinite(scale) || scale <= 0) return;
    const fittedWidth = Math.max(1, Math.floor(g.width * scale));
    const fittedHeight = Math.max(1, Math.floor(g.height * scale));

    hardApplied = true;
    stage.classList.add('lh-hard-portrait');
    stage.style.setProperty('position', 'relative', 'important');
    stage.style.setProperty('overflow', 'hidden', 'important');
    video.style.setProperty('position', 'absolute', 'important');
    video.style.setProperty('left', '50%', 'important');
    video.style.setProperty('top', '50%', 'important');
    video.style.setProperty('transform', 'translate(-50%, -50%)', 'important');
    video.style.setProperty('margin', '0', 'important');
    video.style.setProperty('min-width', '0', 'important');
    video.style.setProperty('min-height', '0', 'important');
    video.style.setProperty('width', `${fittedWidth}px`, 'important');
    video.style.setProperty('height', `${fittedHeight}px`, 'important');
    video.style.setProperty('max-width', 'none', 'important');
    video.style.setProperty('max-height', 'none', 'important');
    video.style.setProperty('aspect-ratio', `${g.width} / ${g.height}`, 'important');
    video.style.setProperty('object-fit', 'contain', 'important');
    video.style.setProperty('object-position', 'center center', 'important');
    stage.dataset.lhPortraitFit = `${g.width}x${g.height}:${fittedWidth}x${fittedHeight}`;
  }

  function scheduleFit() {
    if (scheduled) cancelAnimationFrame(scheduled);
    scheduled = requestAnimationFrame(() => {
      requestAnimationFrame(applyHardPortrait);
      setTimeout(applyHardPortrait, 80);
      setTimeout(applyHardPortrait, 260);
    });
  }

  video.addEventListener('loadedmetadata', scheduleFit);
  video.addEventListener('loadeddata', scheduleFit);
  video.addEventListener('resize', scheduleFit);
  if (diagnostics) new MutationObserver(scheduleFit).observe(diagnostics, {subtree:true, childList:true, characterData:true});

  new MutationObserver(() => {
    clearHardFit();
    delete stage.dataset.lhPortraitFit;
    scheduleFit();
  }).observe(pathNode, {subtree:true, childList:true, characterData:true});

  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(scheduleFit).observe(stage);
  else window.addEventListener('resize', scheduleFit);

  viewer.addEventListener('close', () => {
    clearHardFit();
    delete stage.dataset.lhPortraitFit;
  });
})();
