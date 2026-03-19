// ─── Scroll Fade-In Observer ─────────────────────────
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      observer.unobserve(entry.target);
    }
  });
}, { threshold: 0.12 });

document.querySelectorAll('.fade-up').forEach(el => {
  observer.observe(el);
});

// ─── Auto-update Footer Year ─────────────────────────
const yearEl = document.getElementById('year');
if (yearEl) {
  yearEl.textContent = new Date().getFullYear();
}
// ─── Theme Toggle ─────────────────────────────────────
const toggle = document.getElementById('theme-toggle');

toggle.addEventListener('click', () => {
  document.body.classList.toggle('light-mode');

  // Update button icon
  const isLight = document.body.classList.contains('light-mode');
  toggle.textContent = isLight ? '🌙' : '☀️';

  // Remember user's preference
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
});

// Load saved preference on page load
const savedTheme = localStorage.getItem('theme');
if (savedTheme === 'light') {
  document.body.classList.add('light-mode');
  toggle.textContent = '🌙';
}