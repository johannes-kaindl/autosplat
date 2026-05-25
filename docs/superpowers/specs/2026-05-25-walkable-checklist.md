# Walking-mode — manual smoke checklist

**For:** v1.x release of walkable-mode (slices 0–8, commits `f44e6b6` → `45e3fbf`+)
**Run before:** pushing `main:pages` to Codeberg

This is the human-in-the-loop smoke. Automated tests cover unit logic +
DOM lifecycle in headless Chrome; everything below needs a real GPU,
real touch input, or real timing to verify.

## Desktop — Chrome / Firefox / Safari (macOS)

Run `./serve.sh` and open `http://localhost:8123/`.

- [ ] Page loads, demo splat renders with auto-orbit
- [ ] After the splat loads, the **"▶ Walk through this scene"** CTA
      fades in at centre-top of the stage
- [ ] If untouched, CTA auto-fades after ~4 seconds
- [ ] Reload, click CTA → walking-mode HUD appears:
      - [ ] Mode pill **🚶 Walk** top-left
      - [ ] Crosshair in centre
      - [ ] **✕** exit button top-right
      - [ ] Controls hint bottom-centre (dims after a few seconds)
- [ ] Pointer-lock engages (cursor disappears, browser shows a hint)
- [ ] **W / A / S / D** moves the camera; arrow keys do the same
- [ ] Mouse movement looks around smoothly (no roll on the horizon)
- [ ] Pitch clamps just under vertical — no upside-down flip
- [ ] **Space** jumps with a clear arc; you land back on the ground
- [ ] **Shift** held doubles speed
- [ ] **F** toggles fly mode → pill becomes **✈ Fly**, gravity off
- [ ] In fly: **Q / E** moves down / up; **Space** also moves up
- [ ] **F** again → back to **🚶 Walk**, gravity returns
- [ ] **Mouse wheel** changes eye height — overlay shows "Eye height: X.XX"
- [ ] Reload page → previous eye-height is restored (localStorage)
- [ ] **Esc** exits walking → orbit camera restored at the original pose
- [ ] Loading a fresh splat (drag-and-drop or file picker) → CTA appears again
- [ ] Walking on a hostile splat (no extractable positions) → error toast
      "Splat has no usable geometry for walking-mode" instead of a hang
- [ ] Lose pointer-lock by clicking outside the canvas → walking exits
      cleanly (HUD hidden, orbit restored)

## Mobile — iPad Safari + iPhone Safari

Same `http://<your-mac-ip>:8123/` from the mobile device.

- [ ] CTA appears after splat load (no overlap with the hero overlay)
- [ ] Tap CTA → HUD shows + Jump (**↑**) and Fly (**✈**) buttons appear
      on the right edge (visible only on coarse-pointer devices)
- [ ] Drag in the **left** half → virtual joystick steers movement
- [ ] Push joystick to the rim → sprint engages (visible from camera speed)
- [ ] Drag in the **right** half → look-around works smoothly
- [ ] **↑** button jumps
- [ ] **✈** button toggles fly mode (mode pill flips); fly-mode vertical
      uses the joystick + jump-button for up (no Q/E on touch)
- [ ] **✕** button exits walking cleanly
- [ ] Orientation change (portrait ↔ landscape) doesn't break the joystick

## Performance

- [ ] On the demo splat (~12 MB SOG, ~500 K splats), walking maintains
      a smooth framerate — no visible stutter from heightmap-build
- [ ] On a 1 M-point user splat, walking-mode enters within ~2 s of CTA
      click (heightmap build ≤ 50 ms + pointer-lock acquire)

## Known limitations (don't fail the checklist)

- Indoor multi-room scenes feel like flat floors with invisible walls
  — this is the Tier-2 heightmap design; Tier-3 mesh-collision is a
  separate follow-up.
- Pointer-lock is unavailable on iOS Safari; touch users bypass this
  entirely via the joystick.
- Splats rotated heavily off the world-Y axis will have a wider AABB
  than necessary; walking still works, just with extra empty space.
