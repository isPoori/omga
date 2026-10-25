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

Pushes to `main` that touch `website/` are deployed by `.github/workflows/pages.yml`.

In the GitHub repo: **Settings → Pages → Build and deployment → Source: GitHub Actions**.

## Structure

| File        | Purpose                          |
| ----------- | -------------------------------- |
| `index.html`| Landing page                     |
| `styles.css`| Layout and theme                 |
| `script.js` | Smooth scroll, copy install cmds |
