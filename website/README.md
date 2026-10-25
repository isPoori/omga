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

Pushes to `main` run `.github/workflows/pages.yml` (uploads the `website/` folder).

**Required once** (admin): GitHub repo → **Settings → Pages → Build and deployment → Source: GitHub Actions**.

If Source is not set to GitHub Actions, the workflow fails at `configure-pages` with `Get Pages site failed` / `Not Found`.

## Structure

| File        | Purpose                          |
| ----------- | -------------------------------- |
| `index.html`| Landing page                     |
| `styles.css`| Layout and theme                 |
| `script.js` | Smooth scroll, copy install cmds |
