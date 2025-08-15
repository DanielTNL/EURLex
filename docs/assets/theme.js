(() => {
  const LS = localStorage;
  const savedHue = Number(LS.getItem('accentHue'));
  document.documentElement.style.setProperty('--h', isNaN(savedHue) ? 221 : savedHue);

  function setAccent(h){ document.documentElement.style.setProperty('--h', h); LS.setItem('accentHue', String(h)); }
  function setTheme(mode){ if(mode==='light') document.documentElement.setAttribute('data-theme','light'); else document.documentElement.removeAttribute('data-theme'); LS.setItem('theme', mode); }
  setTheme(LS.getItem('theme') || 'auto');

  document.getElementById('themeBtn')?.addEventListener('click', () => setTheme((localStorage.getItem('theme')||'auto')==='light'?'auto':'light'));
  document.querySelectorAll('.swatch').forEach(b => b.addEventListener('click', () => setAccent(Number(b.style.getPropertyValue('--h')))));
})();
