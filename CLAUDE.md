# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository overview

This is a personal learning journal / portfolio for the **100 Days of Code** challenge by Isarael Ojo (citeChris), an entry-level developer based in Ibadan, Nigeria. The repo tracks progress through **freeCodeCamp's Responsive Web Design** certification and adjacent learning (JavaScript, Python basics). It is publicly hosted at `https://citechris.github.io/100-days-of-code/`.

The current capstone in progress is **SecureVault** — a password health checker (HTML/CSS frontend, Python/Flask backend, HaveIBeenPwned API). It is deferred until JavaScript fundamentals are complete. The `SecureVault/` directory is intentionally empty for now.

## Tech stack

- **HTML5, CSS3** — primary content; vanilla only, no framework
- **JavaScript** — vanilla (no Node, no bundler, no packages)
- **Python** — notes only (`python_notes.md`); no Python code in the repo yet
- **GitHub Pages** — static hosting target
- **Tools:** VS Code, Git, GitHub

## Build / lint / test

**There is no build step, no linter, and no test suite.** Everything is plain static files. Open files directly in a browser, or serve the directory locally for projects that need a server:

- Quick local serve (Python): `python -m http.server 8000` from the repo root
- Or open any `*.html` file directly (e.g. `index.html`, `matrix_rain.html`, `todo-list.html`)

There is no `package.json`, no `requirements.txt`, no CI config.

## High-level architecture

The repo is a **flat directory** of small standalone projects plus a few flagship files. There is no shared runtime or module system — each file is self-contained.

### Flagship portfolio (the link in the README)

These three files together form the cited portfolio site:

- `index.html` — semantic HTML5 landing page with navbar, hero, about, projects grid, and contact sections. Anchors: `#welcome-section`, `#about`, `#project-section`, `#contact`.
- `styles.css` — design system via CSS custom properties on `:root` (defined under `/* Variables */`); dark by default, light theme toggled via `body.light-mode`. Sidebar layout uses `--sidebar-w` variable.
- `index.js` — three small features wired to the page: `IntersectionObserver` fade-up on `.fade-up` elements, auto-updating footer year (`#year`), and a theme toggle (`#theme-toggle`) that persists to `localStorage['theme']`.

### Featured interactive demos

- `matrix_rain.html` — single-file `<canvas>` demo. All animation is inline `<script>` at the bottom. Tunable via CSS custom properties on `:root` (`--glyph-color`, `--speed`, `--density`, `--trail-length`, `--random-charset`, etc.) and keyboard shortcuts (`+`/`-` speed, `s`/`d` density, `t`/`g` trail). Capped DPR for perf.
- `todo-list.html` — vanilla task manager. State held in an in-memory `tasks` array (no persistence). Filters (`all`/`active`/`done`), per-task color dot from a fixed `DOTS` palette, full re-render on every mutation.
- `homescreen-bg.html` + `homescreen-bg.css` — animated terminal-style landing page with floating code snippets, custom cursor (toggleable), and a staged progress-bar animation.

### Learning exercises (sub-100 LoC each)

The remaining files are individual freeCodeCamp exercises, one project per file pair (e.g. `build-a-tribute-page.html` + `build-a-tribute-page.css`). Naming conventions:

- `build-a-*.html` / `build-a-*.css` — freeCodeCamp "build" labs
- `design-a-*.html` / `design-a-*.css` — freeCodeCamp "design" labs
- `debug-*.js` — small JS debugging exercises
- `lab-*.html` / `lab-*.css` — lab exercises
- `new *.html` — early/scratch HTML explorations (kept for history; treat as ephemeral)

These are intentionally flat — no shared CSS, no module imports. When extending an exercise, keep its CSS in the matching `.css` file.

## Conventions observed

- **Two-file projects** for HTML exercises: stylesheet lives next to the HTML with the same stem (e.g. `build-a-tribute-page.html` → `build-a-tribute-page.css`).
- **No build artifacts** committed — no `node_modules`, no `dist/`, no compiled output.
- **Live demos are linked** from `README.md` as `https://citechris.github.io/100-days-of-code/&lt;filename&gt;`. When adding a new project, ensure `README.md` links still point to the correct file.
- **External assets** (Google Fonts, freeCodeCamp CSS) are loaded via CDN `<link>` tags; no vendored copies.
- **Accessibility:** forms use semantic HTML5 input types; nav buttons use `aria-label`.

## Things to be careful about

- The repo is a **journal**, not a library. Many files are scratch/duplicates (`new *.html`, `index.htm`, `Build a Celsius to Fahrenheit Converter.js`). Don't refactor them into a unified structure unless asked — the chronological record is intentional.
- There are **image assets and binaries** at the root (`*.png`, `*.jpg`, `*.webp`, `*.gif`, `logo.jpeg`) used by various projects. Don't delete or rename without checking which file references them.
- `.vs/100-days-of-code.slnx/` is a **Visual Studio solution folder** — local IDE state, not part of the published portfolio.
- Commits use the project's `git commit -m "..."` style and the Co-Authored-By trailer is **not** used here historically; follow the existing log if asked to commit.
