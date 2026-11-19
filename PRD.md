# PeakCut Editing Studio PRD

**Status:** In progress; product scope drafted and first implementation slice delivered  
**Scope:** Better automatic short creation and a responsive, real-time clip editor  
**First principle:** Preserve the existing application, user data, settings, jobs, and clips.

## 1. Product goal

Make PeakCut create polished vertical clips automatically, then let a person refine the clip in an editor that previews changes quickly and renders a final export on demand. Keep the current AI selection, live clipping, posting, and creator workspaces working as they do today.

## 2. Current product baseline

PeakCut already provides:

- AI or loudness-based automatic highlight selection for uploaded videos and supported video links.
- Automatic transcription and word-timed captions.
- Caption styles: Bounce, Hype, Clean.
- Layouts: Full frame + blurred fill; Zoomed in + blurred fill; Fill the screen (centre crop); Gameplay fills the screen, facecam in the corner.
- Per-clip hook text, caption toggle/style, layout, start/end seconds, title, and description.
- A “Save and re-make clip” action and clip posting/download flows.
- Live recording and “clip last 30/60 seconds” actions.

The current editor is a form with the rendered video preview. It does not offer a timeline, immediate visual preview of unrendered changes, soundtrack selection, or separate source/music volume controls.

## 3. Users and needs

1. **Creator/editor:** wants strong clips with little manual work and controls for timing, framing, captions, audio, and post copy.
2. **Live clipper:** wants highlight clips while a stream is running, and quick corrections after each clip appears.
3. **Workspace owner:** wants reliable automatic rules that can be reused for each creator and posting destination.

## 4. Product requirements

### P0: Safe foundation and preservation

- Keep existing routes, APIs, data formats, databases, user folders, files, and defaults compatible.
- Make additive changes. Do not delete, overwrite, rename, migrate destructively, or bulk rewrite user data.
- Back up or use a disposable copy of user data before any schema/data migration or destructive operation.
- Do not overwrite an existing clip export during preview or failed render. Write previews and new exports to temporary/versioned paths, validate them, then atomically promote the completed result.
- Retain the existing editor and renderer as a fallback until the new editor passes acceptance checks.
- All new clip settings are optional with legacy-equivalent defaults. Old jobs/clips lacking new keys must still load and render.

### P1: Automatic edit controls

- Provide a single reusable edit profile for each creator and optional per-video overrides.
- Profile settings: maximum clips, clip length bounds, captions on/off, caption style, layout, audio mix, optional music, and optional title/description pattern.
- Let the user choose an automatic mode: **Auto-publish-ready draft** (produce suggested edits and copy, but wait for review) or **Auto-post** (respect existing account selection, score thresholds, schedules, and caps).
- Show why a moment was selected and allow accept, reject, regenerate, or adjust boundaries.
- Never silently publish newly generated material unless the existing auto-post setting is explicitly enabled.
- Keep deterministic fallback behavior if no AI service is configured or an AI request fails.

### P1: Clip editor and real-time preview

- Show source/clip preview with play/pause, seek, current time, duration, and keyboard-accessible controls.
- Add a simple timeline with draggable start/end handles, editable numeric seconds, and trim validation (3–180 seconds, constrained to available media).
- Reflect text, caption, layout, and audio setting changes in a preview without restarting the entire clip pipeline where technically possible.
- Provide a clear **Preview** action and a separate **Render final clip** action. Preview may be lower resolution; final exports retain configured output quality.
- Show render status, errors, and a retry action. Polling or streaming status updates must not interrupt playback or lose unsaved form state.
- Desktop and mobile layouts must both remain usable; controls need labels, focus states, and keyboard access.

### P1: Captions and text controls

- Retain **Big text** (the on-video hook), caption enable/disable, and current styles: **Bounce**, **Hype**, **Clean**.
- Keep caption layout options: **Full frame + blurred fill**, **Zoomed in + blurred fill**, **Fill the screen (centre crop)**, and **Gameplay fills the screen, facecam in the corner**.
- Add previewed controls for caption size, vertical position/safe area, and highlight color only if they can be rendered consistently by the server.
- Preserve caption word timing and script safety behavior. Caption edits must not alter the source transcript.

### P1: Music and audio controls

- Allow importing an audio file the user owns or is licensed to use. Do not scrape or download music from online streaming services.
- Provide a small in-app music library only for tracks with documented reuse/monetization rights; display source, license, attribution text, and any restrictions beside each track.
- Let the user choose no music or a licensed track, preview it, trim/loop it to the clip, and set music volume and original-video volume independently.
- Optional fade-in/fade-out and ducking under speech; defaults must preserve the current source audio experience.
- Mix audio with clipping protection, normalize final loudness, and preserve understandable speech. No track is marked “copyright-free” without a verifiable license.
- Make music optional. Missing music, unsupported codecs, or a failed mix must not prevent rendering without music.

### P1: Post text

- Keep editable **Title** and **Description** fields.
- Add generated suggestions as drafts, clearly distinguish suggestions from saved text, and allow regenerate/copy.
- Preserve current post text when re-rendering visual/audio settings unless the user edits it.
- Follow destination length limits and show validation before queue/post.

### P1: Scheduled posting

- Let users select **Post now**, **Add to automatic queue**, or **Schedule for a date and time** for each connected account.
- Show and store the scheduled instant unambiguously; display it in the user's chosen timezone and show the timezone next to the date/time.
- Validate that a chosen time is in the future. Resolve daylight-saving gaps/overlaps explicitly in the UI rather than silently shifting a post.
- Respect existing per-account spacing and daily caps. A user-selected time that conflicts with these rules must be explained and either rejected or moved only after the user chooses.
- Scheduled posts remain visible in the existing post queue and can be edited or cancelled before posting. Retrying a failed post must not erase its intended schedule unless the user changes it.
- Keep current automatic queue behavior as the default for **Add to automatic queue**. Existing scheduled entries and persisted `due_at` values remain valid.
- Posting pause, account disconnect/deletion, account authorization, platform rate limits, and retry behavior continue to apply.
- Do not imply that PeakCut controls post timing after a platform has accepted or rescheduled a post; show the actual state returned by the platform.

### P2: More editing improvements

- Optional subject-aware reframing and facecam placement with user adjustment.
- Optional safe-area guides for vertical platforms.
- Undo/redo for unsaved editor changes.
- Project-level presets and duplicate-as-new-version workflow.
- Batch apply an approved profile to selected clips.

## 5. Out of scope for the first release

- A multi-track nonlinear editor or arbitrary effects/keyframes.
- Auto-posting without explicit existing opt-in.
- Importing music from Spotify, YouTube Music, or other services without a license permitting export and reuse.
- Replacing the current AI provider system or posting integrations.

## 6. Global engineering and product rules

1. **Preserve first:** inspect current state before edits. Never delete user-created content or overwrite original media. Make backups for any data transformation.
2. **Additive and compatible:** existing API clients, old job JSON, and user settings continue to work. New values have safe defaults and input validation.
3. **Private by user:** every new endpoint derives ownership from the authenticated session/context; never trust a user ID from the request body.
4. **Safe media handling:** validate allowed file type, size, duration, path, and ownership. Use generated filenames and temporary work directories. Never execute user-provided command strings.
5. **Responsible AI:** treat transcripts, titles, descriptions, and imported metadata as untrusted text. AI outputs are suggestions and must be validated before use.
6. **Publishing is explicit:** no new path may bypass account authorization, user opt-in, schedules, score thresholds, or daily caps.
7. **Licensed assets only:** store source/license/attribution metadata for bundled or selectable music; do not describe unverified media as copyright-free.
8. **Accessible UI:** semantic labels, keyboard support, visible focus, readable contrast, responsive layout, and status announced for assistive technology.
9. **Failure-safe rendering:** retain previous valid output if a preview/final render fails. Report actionable errors and allow retry.
10. **No secret leakage:** keys and tokens remain in existing secret storage; never emit them in logs, HTML, URLs, PRD, or test fixtures.
11. **Test isolated:** use a disposable data directory and synthetic/local media for tests. Never run destructive tests against the user's live data.
12. **Review before release:** complete functional, regression, security, accessibility, and manual UI checks before enabling the new editor by default.

## 7. Success measures

- Existing jobs, clips, creator profiles, and settings load unchanged after upgrade.
- A creator can complete the edit flow (trim, caption/layout, mix, preview, final render, title/description) without losing edits.
- Preview changes appear without a full source re-download or transcription when only presentation settings change.
- Audio remains intelligible and within configured loudness; optional music can be omitted without errors.
- Existing live clipping, manual re-render, download, queue, and post flows continue to pass regression checks.
- No clip is posted without an authorized account and explicit applicable opt-in.

## 8. Delivery plan

1. **Discovery and safety baseline:** map APIs/data, capture existing behavior, create disposable backup/fixture, list compatibility constraints.
2. **Spec and UX states:** finalize editor states, profile precedence, preview/final render behavior, music license metadata, scheduling/timezone rules, and error/empty/loading states.
3. **Data/API foundation:** add optional validated edit settings, schedule create/update/cancel APIs, and versioned preview/final render APIs; prove old payload compatibility.
4. **Audio pipeline:** implement local licensed/user-owned audio import, mix controls, fades/ducking, and safe no-music fallback.
5. **Editor UI:** timeline trim, immediate settings preview, caption/layout controls, text editing, audio controls, responsive/accessibility behavior.
6. **Automatic profiles and schedule UI:** creator defaults, per-clip overrides, review-first automation, opt-in auto-post integration, and user-selected post times.
7. **Validation and rollout:** full regression and targeted tests, isolated manual end-to-end checks, security and accessibility review, then guarded rollout with fallback.

## 9. Acceptance checklist before full testing

- [ ] Existing user data and source clips are intact; no files were removed or replaced.
- [ ] Old jobs with no new edit/audio fields open and render with existing behavior.
- [ ] New profile and per-clip settings validate and persist across restart.
- [ ] Trim boundaries reject invalid, reversed, out-of-range, or too-short ranges.
- [x] Preview updates hook, captions, layout, trim, and mix without changing saved clip settings or final export.
- [x] Final render succeeds with no music and with imported user-provided audio; synthetic mix and no-music renders pass.
- [ ] Music attribution/license metadata remains visible and is included where required.
- [x] Failed final rendering leaves the previous good export downloadable and reports the failure.
- [ ] Copy/title/description, download, queue, and post flows still work.
- [ ] Auto-post remains disabled unless the existing explicit opt-in and safeguards apply.
- [x] User-selected post time uses an explicit timezone and respects caps, gaps, pause state, and account authorization.
- [ ] Scheduled posts can be reviewed and cancelled; existing scheduled posts survive restart unchanged.
- [ ] Live clipping still works and legacy layouts/styles remain selectable.
- [ ] Keyboard-only and narrow-screen editor flows are usable.
- [x] Automated tests ran only against disposable data and synthetic/sample media; manual UI checks remain pending.

## 10. Decisions to confirm during implementation planning

- Whether real-time means browser preview while scrubbing (recommended first) or collaborative multi-user live editing.
- Whether music library ships empty with user imports first, or includes a curated, license-documented starter pack.
- Whether editor preferences are per creator only, or also support named reusable global presets.

