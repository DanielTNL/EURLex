(() => {
  const ACCENTS = [ {name:'indigo', hue:221}, {name:'violet', hue:267}, {name:'teal', hue:172}, {name:'rose', hue:347}, {name:'amber', hue:38} ];
  const LS = window.localStorage;
  function setAccent(h){ document.documentElement.style.setProperty('--accent-h', h); LS.setItem('accentHue', String(h)); window.dispatchEvent(new CustomEvent('themechange',{detail:{type:'accent',hue:h}})); }
  function setTheme(mode){ LS.setItem('theme', mode); document.documentElement.removeAttribute('data-theme'); if(mode==='dark') document.documentElement.setAttribute('data-theme','dark'); if(mode==='light') document.documentElement.setAttribute('data-theme','light'); window.dispatchEvent(new CustomEvent('themechange',{detail:{type:'mode',mode}})); }
  const savedHue = Number(LS.getItem('accentHue')); setAccent(isNaN(savedHue)? ACCENTS[new Date().getDay()%ACCENTS.length].hue : savedHue); setTheme(LS.getItem('theme')||'auto');
  window.Theme = { ACCENTS, setAccent, setTheme };
})();
