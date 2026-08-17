(() => {
  'use strict';
  const reader = document.querySelector('#reader');
  const stage = document.querySelector('.reader-stage');
  const image = document.querySelector('#readerImage');
  if (!reader || !stage || !image) return;

  const FOOTER_HEIGHT = 52;
  const LONG_RATIO = 2.35;

  function fitReader() {
    const nw = image.naturalWidth || 0;
    const nh = image.naturalHeight || 0;
    if (!nw || !nh) return;

    reader.classList.remove('reader-loading');
    const viewportW = Math.max(360, window.innerWidth * 0.96);
    const viewportH = Math.max(320, window.innerHeight * 0.94);
    const imageRatio = nw / nh;
    const heightRatio = nh / nw;

    if (heightRatio >= LONG_RATIO) {
      reader.classList.add('reader-long');
      const targetW = Math.min(viewportW, Math.max(420, Math.min(nw, 980)));
      reader.style.width = `${Math.round(targetW)}px`;
      reader.style.height = `${Math.round(viewportH)}px`;
      requestAnimationFrame(() => { stage.scrollTop = 0; });
      return;
    }

    reader.classList.remove('reader-long');
    const availableH = Math.max(220, viewportH - FOOTER_HEIGHT);
    let scale = Math.min(viewportW / nw, availableH / nh, 1.35);
    if (!Number.isFinite(scale) || scale <= 0) scale = 1;

    const displayW = Math.max(360, Math.min(viewportW, nw * scale));
    const displayH = Math.max(220, Math.min(availableH, nh * scale));
    let dialogW = displayW;
    let dialogH = displayH + FOOTER_HEIGHT;

    // Keep the outer frame proportional to the image instead of forcing every
    // page into the same landscape rectangle.
    const expectedW = displayH * imageRatio;
    if (expectedW > 0 && expectedW < viewportW) dialogW = Math.max(360, expectedW);

    reader.style.width = `${Math.round(Math.min(viewportW, dialogW))}px`;
    reader.style.height = `${Math.round(Math.min(viewportH, dialogH))}px`;
    stage.scrollTop = 0;
  }

  const srcObserver = new MutationObserver(() => {
    reader.classList.add('reader-loading');
    reader.classList.remove('reader-long');
    stage.scrollTop = 0;
  });
  srcObserver.observe(image, {attributes:true, attributeFilter:['src']});

  image.addEventListener('load', fitReader);
  image.addEventListener('error', () => reader.classList.remove('reader-loading'));
  window.addEventListener('resize', () => {
    if (reader.open && image.complete && image.naturalWidth) fitReader();
  });
  reader.addEventListener('close', () => {
    reader.classList.remove('reader-long','reader-loading');
    reader.style.removeProperty('width');
    reader.style.removeProperty('height');
    stage.scrollTop = 0;
  });
})();
