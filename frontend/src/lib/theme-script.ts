// Runs synchronously in <head> before first paint so the correct theme
// applies immediately on hard navigation (no flash of the wrong theme).
// Kept as a plain string (not a component) per the Next.js guidance on
// preventing hydration-flash for client-only preferences like theme.
export const THEME_SCRIPT = `(function(){try{
  var t = localStorage.getItem('lumen_theme');
  if (!t) t = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', t);
} catch (e) {}})();`;
