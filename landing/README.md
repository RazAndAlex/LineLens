# Landing page

One self-contained page. It is `index.html` plus the four screenshots in
`img/`. There is no build step and no dependency. Open the file to preview it.

The page carries its own favicon, the LineLens L mark, inlined as an SVG data
URI, so the browser tab shows the logo.

## How it is published

`.github/workflows/pages.yml` deploys this folder to GitHub Pages on every
push that touches it. The live page is at
https://razandalex.github.io/LineLens/

The workflow uploads the folder as an artifact rather than using branch
deployment. Branch deployment only offers the repository root or `/docs`, and
this folder is neither. Publishing the root would serve the whole repository
as a website, and `/docs` holds the architecture decisions.

To deploy without pushing, run the workflow by hand from the Actions tab. It
declares `workflow_dispatch` for that.

## Screenshots

The images here are copies of the ones in `../docs/screenshots/`. They live in
this folder so it can be deployed on its own. If you take new screenshots,
replace both copies.
