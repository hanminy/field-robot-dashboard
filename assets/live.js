(() => {
  const base = new URL('../version.json', document.currentScript.src);
  const current = document.querySelector('meta[name="deployment-revision"]')?.content;
  async function check() {
    if (document.hidden || !current) return;
    try {
      const url = new URL(base); url.searchParams.set('t', Date.now());
      const response = await fetch(url, {cache: 'no-store'});
      if (!response.ok) return;
      const next = await response.json();
      if (next.revision && next.revision !== current) {
        const page = new URL(location.href);
        page.searchParams.set('v', next.revision);
        location.replace(page);
      }
    } catch (_) { /* Offline viewing remains available. */ }
  }
  setInterval(check, 60000);
  document.addEventListener('visibilitychange', check);
})();
