(() => {
  const ACCENTS = [
    {name:'indigo', hue:221, hex:'#4f46e5'},
    {name:'violet', hue:267, hex:'#7c3aed'},
    {name:'teal', hue:172, hex:'#14b8a6'},
    {name:'rose', hue:347, hex:'#e11d48'},
    {name:'amber', hue:38,  hex:'#f59e0b'},
  ];
  const LS = window.localStorage;

  function setAccent(h){
    document.documentElement.style.setProperty('--accent-h', h);
    LS.setItem('accentHue', String(h));
    window.dispatchEvent(new CustomEvent('themechange', {detail:{type:'accent', hue:h}}));
  }
  function nextAccent(){
    const current = Number(LS.getItem('accentHue')) || ACCENTS[new Date().getDay() % ACCENTS.length].hue;
    const idx = ACCENTS.findIndex(a => a.hue === current);
    setAccent(ACCENTS[(idx+1)%ACCENTS.length].hue);
  }
  function setTheme(mode){ // 'light' | 'dark' | 'auto'
    LS.setItem('theme', mode);
    document.documentElement.removeAttribute('data-theme');
    if(mode === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
    if(mode === 'light') document.documentElement.setAttribute('data-theme', 'light');
    window.dispatchEvent(new CustomEvent('themechange', {detail:{type:'mode', mode}}));
  }

  // initial
  const savedHue = Number(LS.getItem('accentHue'));
  const defaultHue = ACCENTS[new Date().getDay() % ACCENTS.length].hue;
  setAccent(isNaN(savedHue) ? defaultHue : savedHue);
  setTheme(LS.getItem('theme') || 'auto');

  // expose globally for UI hooks
  window.Theme = { ACCENTS, setAccent, nextAccent, setTheme };
})();
