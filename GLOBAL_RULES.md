# Clipsart Global Rules

These rules apply to every future feature, fix, test, and release in this repository.

## Brand, repository, and support

- Use Clipsart as the product name and the `https://github.com/Vishwajeetsrk/clipsart` repository for clone, update, publishing, and release instructions.
- Preserve existing user settings, `.env` files, storage paths, databases, media, and legacy `CLIPSART_*` configuration compatibility across the rebrand.
- Never rewrite published Git history or force-push to suppress GitHub's automatically generated contributor list without explicit, just-in-time approval from the repository owner.
- Suggestions and problem reports must be validated and saved to the existing feedback store. Email the configured support contact only through a configured SMTP provider, and show the user whether delivery is configured.
- Do not commit local secrets or `.env`; keep support mailbox credentials out of source code.

## Preserve user work

- Do not delete or overwrite existing source code, user settings, databases, videos, clips, exports, or credentials as part of feature work.
- Inspect the current state and use additive, backward-compatible changes.
- Before any migration or data rewrite, create and verify a restorable backup. Prefer a disposable copy for development and tests.
- Write generated previews and exports to temporary/versioned paths. Replace a prior output only after the new output passes validation and is atomically promoted.
- Never remove the existing editor/render path until the replacement is implemented, tested, and has a fallback/rollback path.

## Compatibility and data

- New fields are optional, validated, and assigned safe defaults matching current behavior.
- Existing persisted jobs and creator settings without new fields must continue to load.
- Database changes must be additive and have a documented rollback/backup procedure.
- Preserve current routes and response fields unless a migration plan explicitly maintains compatibility.

## Security and privacy

- Resolve user ownership from the authenticated session/context, not request-supplied owner identifiers.
- Validate user input, media paths, file types, durations, and upload sizes; use generated storage names.
- Keep secrets out of logs, source, URLs, browser storage, and error responses.
- Treat transcripts, video metadata, imported captions, AI responses, and post text as untrusted.
- Keep per-user data isolation and existing authorization checks on all new endpoints.

## AI, rights, and publishing

- AI-generated clip choices, captions, and post copy remain editable suggestions.
- Preserve deterministic fallback when AI is unavailable.
- Do not fetch music from streaming services or claim assets are copyright-free without a verifiable license.
- Keep license and attribution metadata for each supplied/selectable track.
- Never bypass existing user opt-in, connected-account authorization, schedules, score thresholds, or posting caps.

## Rendering and UX

- A render or preview failure must preserve the last valid export and provide a retryable error.
- A thumbnail update keeps the current cover until the replacement is normalized and saved; generated covers remain restorable, and custom covers survive clip re-renders.
- Long media operations must report progress and must not block unrelated UI actions.
- Keep responsive layouts, semantic form labels, keyboard access, visible focus, readable contrast, and accessible status updates.
- Preserve the current visual system and existing caption/layout choices unless the user changes them.

## Validation and release

- Run tests against a disposable data directory and synthetic/sample media; never use live user data as a test fixture.
- Before release, verify old jobs, live clipping, captions, layouts, re-render, download, queue, and posting regressions.
- Review data compatibility, authorization, file handling, asset licensing, accessibility, and failure recovery before enabling new behavior by default.
- Keep changes scoped and document new settings, API behavior, and operator recovery steps.
