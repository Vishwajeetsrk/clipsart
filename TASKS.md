# Clipsart Editing Studio Task List

**Project status:** Editor, exact-time scheduling, caption/effect, music, image overlay, and video-based thumbnail features implemented.
**Last updated:** 2026-11-19  
**Progress:** Scheduling and editing foundations implemented; combined full regression suite passed.

Status key: `[x]` done · `[~]` in progress · `[ ]` pending

## Done

- [x] Clone Clipsart and run the existing app locally.
- [x] Inspect the current clip editor, renderer, caption/layout choices, creator settings, and post queue.
- [x] Write the initial product requirements document in `PRD.md`.
- [x] Write preservation, compatibility, security, licensing, and validation rules in `GLOBAL_RULES.md`.
- [x] Confirm existing post queue already schedules posts by `due_at`, displays queued post times, and supports cancellation.
- [x] Add user-selected scheduled posting requirements, timezone/DST handling, conflict rules, and acceptance checks to the PRD.
- [x] Add exact date/time scheduling to the clip editor using the browser's IANA timezone.
- [x] Convert selected local times to UTC instants; reject past times, DST gaps/overlaps, and unknown timezones.
- [x] Enforce per-account spacing and daily caps; preserve automatic queueing and duplicate-post protection.
- [x] Add scheduling regression coverage and include it in the isolated full-suite runner.
- [x] Run the full test suite with UTF-8 output; all groups passed.
- [x] Add a trim timeline; dragging either handle updates the time fields and preview loop immediately.
- [x] Add user-provided audio upload with reuse-rights confirmation, attribution, and optional source/license link.
- [x] Add separate source/music volume controls, music fade in/out, limiting, and final render mixing.
- [x] Keep imported tracks in the clip workspace, preview them in the editor, and include supplied attribution when posting.
- [x] Add music upload/mix tests and remove a track when its clip is deleted.
- [x] Re-run the full isolated suite after the combined editing/audio changes; all groups passed.
- [x] Add a low-resolution preview API and editor action for trim, hook, captions, layout, and audio settings.
- [x] Store previews separately from final exports and verify previewing leaves clip settings and final output unchanged.
- [x] Render final versions to distinct filenames; failed re-renders keep the last good export available with a warning.
- [x] Remove temporary preview and generated version files when the user deletes that clip.
- [x] Run the full regression suite after preview and safe-version changes; all groups passed.

## Clipsart rebrand and support feedback (2026-11-19)

- [x] Confirm only the `Vishwajeetsrk/clipsart` GitHub remote is configured.
- [x] Rebrand user-facing app text, documentation, mail templates, admin pages and project files from the previous project name to Clipsart.
- [x] Replace the reused logo and favicon assets with a Clipsart play mark and orange/maroon wordmark.
- [x] Rewrite the README with verified clone, launch, deployment, environment, editing, scheduling, thumbnail, feedback and test guidance.
- [x] Replace the MIT copyright line with the Clipsart owner notice while retaining the MIT terms.
- [x] Set the updater default and repository URL to `Vishwajeetsrk/clipsart`.
- [x] Add safe `CLIPSART_*` to `PEAKCUT_*` configuration compatibility.
- [x] Add an in-app suggestion/problem form using the existing saved feedback inbox.
- [x] Add optional SMTP notifications for `support.learnifyai@gmail.com`; preserve saved feedback when SMTP is not configured.
- [x] Add migration and feedback-email regression checks.
- [x] Update the GitHub repository description.
- [x] Run Python compilation, frontend JavaScript parsing, Docker Compose validation and the full isolated regression suite.
- [x] Push the rebrand and feedback changes to `Vishwajeetsrk/clipsart` (`c661730`).
- [ ] Decide whether GitHub's generated Contributors list can remain; removing it requires rewriting published history.

## Thumbnail editor plan and implementation

- [x] Specify user flow, safe defaults, compatibility behavior, ownership, upload limits, and acceptance criteria in `PRD.md`.
- [x] Add thumbnail implementation steps to this task list before coding.
- [x] Add frame capture from a finished clip with validated in-range time.
- [x] Add browser canvas preview with optional title text styles and custom image import.
- [x] Save normalized thumbnails without overwriting the current cover before validation; support restore to generated cover.
- [x] Preserve custom thumbnails across final clip re-renders and delete thumbnail assets with their clip.
- [x] Test capture, upload validation, save, restore, ownership, and rerender behavior on disposable data.
- [ ] Manually inspect thumbnail controls and canvas sizing in the signed-in desktop and mobile editor.
- [x] Run the full regression suite and push changes only to `Vishwajeetsrk/clipsart`.

## Pending: product decisions

- [x] First release scheduling uses exact date/time per post; recurring schedules are deferred.
- [x] Browser IANA timezone is the scheduling default and is displayed with the scheduled time.
- [ ] Decide whether a scheduled post may be edited in place before it is due, beyond cancellation and re-queueing.
- [x] First release accepts user-owned/licensed uploads; a curated rights-verified starter library is deferred.
- [x] First release “real-time editing” means immediate local preview and a fast low-resolution render; multi-user collaboration is deferred.
- [ ] Decide whether edit profiles are per creator only or include reusable global presets.

## Pending: implementation work

### Phase 0 — protect current behavior

- [x] Record current git/runtime state and preserve the existing `data` folder.
- [x] Use the test runner's disposable data folders; no test used the real `data` folder.
- [x] Run existing regression coverage for permissions, queueing, clips, posting, and storage behavior.

### Phase 1 — schedule design and backend

- [x] Specify schedule payload, timezone handling, DST ambiguity policy, validation errors, and API compatibility.
- [x] Add per-post explicit-time scheduling while retaining automatic queue slots and old `due_at` records.
- [~] Cancellation is supported; editing/rescheduling an existing queued post is not yet implemented.
- [x] Enforce per-account gap, daily cap, pause, ownership, and authorization rules for selected times.
- [ ] Verify scheduler recovery after server restart and behavior around a missed due time.
- [x] Add exact-time scheduling while keeping existing automatic queue entries and `due_at` values compatible.
- [x] Enforce account spacing, daily caps, user ownership through the current session, and future-time validation.
- [x] Show the scheduled timezone in the queue and clip post badges.
- [ ] Add edit/reschedule controls for already queued posts; cancellation is already supported.

### Phase 2 — editor preview and audio

- [ ] Design editor settings precedence (global/creator/video/clip).
- [x] Add versioned, low-resolution preview rendering and keep final rendering separate.
- [x] Add trim start/end sliders and loop the existing clip preview over the selected interval.
- [x] Add immediate visual preview for text, caption, and layout changes.
- [x] Add local track import, playback preview, rights confirmation, attribution/source metadata, and independent volume controls.
- [x] Mix optional music with ffmpeg, add fades, limit peaks, and retain source audio when music is off.
- [ ] Add optional speech ducking and user-adjustable fade durations.
- [x] Keep the last valid export downloadable after a failed re-render.

### Phase 3 — automatic profiles and posting UI

- [ ] Add reusable edit profiles and per-clip overrides with legacy-compatible defaults.
- [ ] Keep automatic clip suggestions review-first unless existing explicit auto-post is enabled.
- [x] Add Post now / Automatic queue / Schedule date and time choice to the clip workflow.
- [x] Show timezone, validate date/time, present gap/cap conflicts, and show scheduled state in the post queue.
- [ ] Keep title and description editable; preview generated suggestions before saving/posting.

### Phase 4 — verification before full release

- [x] Run unit/integration/regression tests against disposable data.
- [ ] Manually verify end-to-end: create clip → adjust trim → import/mix track → final render → schedule → cancel/reschedule → post.
- [ ] Verify old jobs/settings/posts still load and existing live workflows continue to work.
- [ ] Review authorization, per-user isolation, upload validation, secret handling, licensing metadata, and failure recovery.
- [ ] Review keyboard access, screen reader labels/statuses, focus handling, and narrow-screen layout.
- [ ] Enable new editor behind a guarded rollout/fallback only after acceptance checklist passes.

## Current progress

- **Planning:** `PRD.md`, `GLOBAL_RULES.md`, and this task list are written. First-release choices for one-time scheduling, browser timezone, local preview, and user-provided music are recorded.
- **Implementation:** exact-time scheduling, trim editing, low-resolution visual preview, user-provided music, caption/effect choices, custom image overlays, safe versioned exports, and frame-based/custom thumbnail editing are implemented. Queued-post rescheduling, speech ducking, adjustable fades, reusable profiles, and automatic editing remain pending.
- **Testing:** full disposable-data suite passed after thumbnail work, including seven thumbnail checks and existing caption, schedule, render, security, and storage groups. Python compilation and JavaScript parsing passed.
- **Data safety:** feature tests used disposable directories. The live `data` folder was not used by tests or modified by the feature.
- **Next:** manually inspect thumbnail editor sizing/keyboard flow, then continue queued-post rescheduling, reusable creator edit profiles, and rule-based automatic editing. Finish manual end-to-end, legacy-data, accessibility, and responsive UI review before default rollout.

