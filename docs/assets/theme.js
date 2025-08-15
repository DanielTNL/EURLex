// Always-blue accent, no UI controls.
(() => {
  const LS = localStorage;
  document.documentElement.style.setProperty('--h', 221);
  const saved = LS.getItem('theme') || 'auto';
  if(saved === 'light') document.documentElement.setAttribute('data-theme','light');
})();
