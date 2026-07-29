# vendor/

`playcanvas.mjs` — PlayCanvas engine, vendored so this viewer needs no CDN:
it is bundled into AutoSplat.app (walking mode must work offline) and served
from Codeberg Pages.

**It is a copy of `embed/vendor/playcanvas.mjs` and must stay byte-identical.**
`tests/unit/vendor.test.mjs` fails if the two drift. Update both together:

    cp ../embed/vendor/playcanvas.mjs vendor/playcanvas.mjs

Two copies rather than one shared file, deliberately: `embed/` is copied
wholesale into every share bundle and has to be self-contained, and the Pages
deploy is a `git subtree split` of `viewer/` alone, where `../embed/` is absent.
