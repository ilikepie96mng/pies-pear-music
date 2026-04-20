# pies-alac-rip-tool Frontend + Product Roadmap

## Purpose

This document defines the implementation order for the desktop/frontend work on `pies-alac-rip-tool`, along with release boundaries, priorities, review workflow, and quality gates.

The product direction is:

- A Linux-native Apple Music lossless sync and local library management app
- Focused on trust, observability, archival value, and clean local playback
- Not just a script wrapper, but a real desktop product with strong setup, diagnostics, sync visibility, and library stewardship

---

## Product Principles

All design and implementation work should optimize for these principles:

1. Reliability over flash
- The app must clearly show whether sync is healthy, degraded, or broken.
- Errors must be actionable.

2. Local ownership is the value
- The UI should emphasize the user's local library, synced playlists, metadata, files, and history.

3. Operational transparency
- The user should be able to see what happened, what is happening, and what will happen next.

4. Preserve momentum
- Build in vertical slices that can ship cleanly as staged releases.

5. Avoid generic dashboard design
- The app should feel like an archival music workstation, not a default SaaS admin panel.

---

## Release Plan

## Release 1: Trustworthy Core App

### Goal

Ship a frontend that makes the current product understandable and usable end-to-end.

### Scope

- First-run setup wizard
- Main dashboard
- Playlist management UI
- Manual sync UI
- Sync progress and error visibility
- Settings/config editor
- Health/status indicators
- Basic sync history

### User-facing outcomes

- A new user can install, configure, validate setup, add playlists, and run a sync without touching raw config files unless necessary.
- A returning user can immediately see whether the app is healthy and what the last sync did.
- Errors are visible and understandable.

### Required screens

1. Setup Wizard
2. Dashboard
3. Playlist List
4. Playlist Detail
5. Sync Run Status / Live Progress
6. Settings
7. Diagnostics / Health

### Required features

- Dependency status checks
  - Homebrew
  - downloader repo/binary
  - Podman or wrapper runtime requirements
  - ffmpeg
  - config presence
  - token presence
  - systemd timer status
- Config editing
  - music directory
  - state directory
  - media-user-token
  - Apple ID credentials
  - optional Git sync settings
- Playlist CRUD
  - add
  - rename display name
  - remove
  - pause/resume tracking
- Sync controls
  - sync all
  - sync single playlist
  - cancel or stop if feasible
- Sync visibility
  - current phase
  - new/skipped/error counts
  - per-playlist outcome
  - clear surfaced failures
- History
  - last successful sync
  - last failed sync
  - summary of recent runs

### Engineering tasks

1. Define frontend app shell and navigation
2. Define backend API contracts for status, settings, playlists, sync runs, and logs
3. Build setup wizard
4. Build dashboard
5. Build playlist management views
6. Build sync progress UI
7. Build settings page
8. Build diagnostics page
9. Add logging/event model needed by frontend
10. Add tests for basic UI/backend integration

### Release gate

- A clean install can be configured through UI
- A user can add a playlist and trigger sync
- Sync success and sync failure are both visible
- Diagnostics page correctly surfaces missing dependencies and invalid config
- No major dead-end flows

---

## Release 1.5: Library Stewardship

### Goal

Make the app useful not just for syncing, but for maintaining a clean local archive.

### Scope

- Library browser
- Metadata health tools
- Duplicate detection
- Missing file / orphaned DB detection
- Playlist membership/provenance
- Repair/rebuild tools

### User-facing outcomes

- The user can inspect what exists locally.
- The user can identify bad metadata, duplicates, and mismatches between disk and state.
- The user can repair derived artifacts without manual database work.

### Required screens

1. Library Browser
2. Track Detail
3. Album Detail
4. Data Health / Cleanup
5. Repair Tools

### Required features

- **Incremental download** (primary feature)
  - Before triggering a download, fetch the playlist's current track list from the Apple Music API using the stored media user token
  - Diff against the local DB to identify new, removed, and already-owned tracks
  - Download only genuinely new tracks
  - For already-owned tracks that are missing from the playlist file, add them to the M3U8 without re-downloading
  - Store Apple Music track IDs in the DB alongside local paths to enable future diffs
- Search by artist, album, track, playlist
- Recently added view
- Track provenance
  - which playlist(s) caused this track to be downloaded
  - when it was first downloaded
- Duplicate candidate view
- Missing metadata warnings
- Missing cover art warnings
- Missing local file warnings for DB entries
- Orphaned files on disk warnings
- Rebuild actions
  - regenerate `.m3u8`
  - refresh state from library if supported
  - retag library entries where possible

### Engineering tasks

1. Expose library/state query APIs
2. Build searchable library browser
3. Add detail pages for tracks and albums
4. Build health audit logic
5. Build repair actions UI
6. Add tests around data consistency checks

### Release gate

- User can inspect local library and provenance
- User can find and understand common library issues
- Repair actions are safe and well-scoped
- No destructive cleanup action runs without explicit confirmation

---

## Release 2: Serious Desktop Product

### Goal

Turn the app from a utility UI into a polished desktop application with strong operational UX.

### Scope

- Background sync experience
- Rich activity timeline
- Better run diagnostics
- Conflict handling
- Multi-library or profile support
- Notifications
- Import/export workflows

### User-facing outcomes

- The app feels native and persistent.
- Background automation is trustworthy.
- Users can understand historical behavior and manage multiple setups.

### Required screens

1. Activity Timeline
2. Sync Run Detail
3. Notifications / Events Center
4. Profile or Library Switcher
5. Import/Export

### Required features

- Background sync status
- Next scheduled run visibility
- Desktop notifications
  - sync started
  - sync completed
  - sync failed
- Run detail pages
  - phase timeline
  - log excerpts
  - failure context
- Conflict resolution
  - duplicate path collision
  - metadata ambiguity
  - missing source data
- Profile support
  - separate config targets
  - separate libraries or state roots
- Export/import of app state and config package

### Engineering tasks

1. Define persistent run/event model
2. Build timeline/event feed
3. Add system notifications
4. Add profile abstraction if architecture supports it
5. Build import/export UX
6. Expand integration testing around long-running flows

### Release gate

- Background behavior is observable
- Sync history is inspectable
- Failure analysis is materially better than logs alone
- Multi-profile support is stable if included

---

## Release 3: Differentiation and Collector Features

### Goal

Add features that make the app uniquely valuable beyond "download and organize."

### Scope

- Playlist diffing across syncs
- Archive/snapshot mode
- Collection analytics
- Smart organization rules
- Cross-machine awareness
- Self-healing maintenance

### User-facing outcomes

- The app becomes a real archive and collection management tool.
- Users gain insight into how their playlists and library evolve over time.

### Required features

- Playlist diff view
  - tracks added since last sync
  - tracks removed upstream
- Snapshot mode
  - freeze a playlist/library state by date
- Archive mode
  - show what has been preserved locally even if upstream changes
- Collection analytics
  - top artists
  - albums completed
  - most active playlists
  - sync trends over time
- Smart rules
  - map playlists to folders/tags
  - custom naming or organization presets
- Self-healing tools
  - recreate missing derived files
  - validate environment
  - recheck dependencies
  - fix known config mismatches

### Engineering tasks

1. Add historical playlist state model
2. Build diff/snapshot UX
3. Add analytics queries and visualizations
4. Add rules engine for organization behavior
5. Add maintenance automation and validation routines

### Release gate

- Historical changes are trustworthy
- Advanced features do not compromise core sync reliability
- Power-user features remain understandable

---

## Implementation Order

This is the exact recommended order of work.

1. Establish frontend architecture
- Decide framework/runtime
- Define routing
- Define state management
- Define API boundary to backend
- Define event/logging model needed by UI

2. Build shared design system primitives
- Layout shell
- Navigation
- Status badges
- Cards
- Tables
- Empty states
- Confirmation dialogs
- Log viewer
- Progress components

3. Build Release 1 setup wizard first
- This is the highest value screen because the app currently depends on fragile environment setup.

4. Build Release 1 diagnostics page second
- The app needs an immediate trust surface.

5. Build Release 1 dashboard third
- Must summarize system state, playlist count, last sync, errors, and pending actions.

6. Build playlist management UI
- Add/list/remove/pause/resume tracked playlists.

7. Build sync progress and run detail UI
- Must show current phase and failure causes.

8. Build settings/config UI
- Users should not need to hand-edit YAML for routine actions.

9. Add Release 1 tests and stabilize
- Do not rush into 1.5 before the core flows are solid.

10. Build Release 1.5 library browser
- Once core trust exists, expose the actual local archive.

11. Build health/cleanup/repair tools
- These are strong quality-of-life improvements and reinforce archival value.

12. Add Release 1.5 tests and stabilize

13. Build Release 2 event timeline and desktop features
- Background service visibility
- notifications
- profile handling if included

14. Add Release 2 tests and stabilize

15. Build Release 3 differentiators
- diffs
- analytics
- snapshots
- rules
- self-healing

---

## UI/Visual Direction

### Primary recommendation: Archival Workstation

The app should feel like a music archive control room.

### Visual characteristics

- Warm neutral base colors
- Olive, brass, amber, rust, slate accents
- Dense but readable layouts
- Strong typography with character
- Panels that feel like trays, drawers, or record sleeves
- Operational status language: healthy, degraded, failed, syncing
- Real hierarchy and contrast, not generic card spam

### Avoid

- Generic startup dashboard aesthetics
- Default dark-mode-only neon styling
- Purple gradient "AI app" visuals
- Flat CRUD interface without emotional identity

### UX qualities

- Calm when healthy
- Precise when broken
- Rich in detail when expanded
- Minimal friction for common actions

---

## Screen-by-Screen Priorities

## Setup Wizard

Must answer:

- Is the environment usable?
- What is missing?
- What must the user enter?
- Can we run a safe validation before first sync?

Include:

- checklist view
- inline fixes
- token instructions
- credentials fields
- path selection
- test connection / test sync validation

## Dashboard

Must answer:

- Is the app healthy?
- When did it last sync?
- What changed recently?
- What needs attention?

Include:

- system health summary
- playlists tracked
- last run result
- new tracks this week
- failed playlists
- quick actions

## Playlist List and Detail

Must answer:

- What is being tracked?
- What is each playlist doing?
- What changed?

Include:

- state
- counts
- last sync
- recent activity
- manual sync button
- pause/resume

## Sync Run Detail

Must answer:

- What happened during this run?
- Where did it fail?
- What should the user do next?

Include:

- phase timeline
- counters
- logs
- actionable error explanation
- copy diagnostics action

## Library Browser

Must answer:

- What do I actually have locally?
- Where did it come from?
- What is wrong with it?

Include:

- filters
- track provenance
- missing metadata indicators
- missing file indicators
- artist/album drill-down

## Diagnostics

Must answer:

- Why is the app not working?
- Is the problem config, environment, authentication, sync backend, or Git state push?

Include:

- dependency status
- token presence
- timer status
- config validation
- backend reachability
- last error surfaces

---

## Quality Gates for Every Release

Before any release is considered complete:

1. Core flows must work on a clean environment
2. Failure modes must be visible in the UI
3. No silent success on backend failure
4. Config, installer, runtime, and docs must agree
5. Tests must cover the highest-risk integration seams
6. The UI must not hide operational reality

---

## Review Workflow: Claude + Codex

### Claude responsibilities

- Generate frontend structure and UI implementation
- Build screens, components, layout, styling, navigation
- Implement product-facing UX flows
- Draft supporting frontend logic and presentation layer behavior

### Codex responsibilities

- Review implementation for correctness, integration risks, architecture drift, and release readiness
- Check for config/runtime mismatches
- Check for bad assumptions in data flow and failure handling
- Propose cleanup and follow-on improvements
- Validate release boundaries and roadmap discipline

### Joint workflow

1. Claude implements one milestone or screen set at a time
2. Claude provides the diff or completed slice
3. Codex reviews for:
- correctness
- integration risks
- missing edge cases
- test gaps
- release boundary violations
4. Issues are resolved before moving to the next milestone
5. Only then start the next release slice

### Rule

Do not build multiple releases at once.
Ship in clean vertical slices.

---

## Immediate Next Step for Claude

Claude should begin with Release 1 and do this exact sequence:

1. Propose frontend architecture and app shell
2. Propose visual direction consistent with "archival workstation"
3. Build Setup Wizard
4. Build Diagnostics page
5. Build Dashboard
6. Build Playlist management screens
7. Build Sync Run UI
8. Build Settings page
9. Add tests for Release 1 flows
10. Stop and request review before moving to Release 1.5

---

## Non-Goals For The First Release

Do not include these in Release 1 unless they are trivial:

- advanced analytics
- snapshot/history diffing
- multi-profile support
- smart organization rules
- cross-machine views
- heavy data visualizations
- speculative social/music discovery features

Release 1 is about trust and clarity, not breadth.

---

## Final Standard

The finished product should feel like:

- a reliable music archive manager
- a sync control center
- a desktop app with strong operational transparency
- a tool made for collectors and Linux users who care about local ownership
