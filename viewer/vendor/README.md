# vendor/

`playcanvas.mjs` and `camera-controls.mjs` — PlayCanvas engine + its camera
control script, vendored so this viewer needs no CDN: it is bundled into
AutoSplat.app (walking mode must work offline) and served from Codeberg Pages.

**Both are copies of `embed/vendor/playcanvas.mjs` and
`embed/vendor/camera-controls.mjs` and must stay byte-identical.**
`tests/unit/vendor.test.mjs` fails if either drifts. Update both together:

    cp ../embed/vendor/playcanvas.mjs vendor/playcanvas.mjs
    cp ../embed/vendor/camera-controls.mjs vendor/camera-controls.mjs

Two copies rather than one shared file, deliberately: `embed/` is copied
wholesale into every share bundle and has to be self-contained, and the Pages
deploy is a `git subtree split` of `viewer/` alone, where `../embed/` is absent.
