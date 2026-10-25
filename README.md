# OMGA landing site

Static one-page site for [GitHub Pages](https://pages.github.com/). No build step.

## Run locally

From this directory:

```bash
cd website
python -m http.server 8080
```

Open [http://localhost:8080](http://localhost:8080).

Any static file server works (e.g. `npx serve .`).

## Deploy

Pushes to `main` run `.github/workflows/pages.yml`, which publishes `website/` to the `gh-pages` branch and tries to point Pages at that branch.

If the site URL is still empty after the first green run: **Settings → Pages → Deploy from a branch → `gh-pages` / root**.

## Structure

| File        | Purpose                          |
| ----------- | -------------------------------- |
| `index.html`| Landing page                     |
| `styles.css`| Layout and theme                 |
| `script.js` | Smooth scroll, copy install cmds |
