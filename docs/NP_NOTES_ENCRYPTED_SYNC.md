# NP Notes — encrypted offline-first GitHub sync

Status: **opt-in**; real note synchronization is disabled on each device until separately activated after a verified backup.

## Intended behavior

- Local saves remain authoritative and never wait for the internet.
- Pending UUIDs survive app restart in SQLite, and failures never delete the queue.
- Worker batches outbound sync every 300 seconds (5 minutes).
- When offline or remote access fails, retries occur every 15 seconds.
- Snapshot contains `note.json` and note-local attachments (excluding cache/backups).
- Each snapshot is encrypted before GitHub upload with AES-256-GCM and
  a unique nonce, using a 600,000-iteration PBKDF2-HMAC-SHA256 key.
- Upload requires repository visibility to be **private**, and a previous
  GitHub blob SHA is required when replacing an existing encrypted file.
- A new note from a second device can be imported into an unused folder.
- Existing notes with a previously acknowledged clean local baseline are
  staged in encrypted form by the worker and fast-forwarded only on the GUI
  thread, after creating a full-folder backup under
  `Data/NPNotesSync/remote_update_backups`. Open/edited notes are skipped.
- Divergent incoming ciphertext is quarantined in
  `Data/NPNotesSync/remote_conflicts`. A user can restore conflicts as
  separate UUIDs from the settings UI; automatic destructive merging is
  prohibited.

## Configuration (ONLY after review and synthetic tests)

A **dedicated private repository** is required, not the program's source
repository. Use a fine-grained GitHub token with **Contents: Read and write**
restricted to that one repository. Use the SAME strong passphrase on every
device, but NEVER put it in a repository, config file, command history,
issue or chat.

Install `cryptography` in the application's portable Python environment
using `requirements-sync.txt`.

The application reads these process environment variables on startup:

- `NP_NOTES_SYNC_OWNER`: GitHub account or organization.
- `NP_NOTES_SYNC_REPOSITORY`: private data repository name.
- `NP_NOTES_SYNC_TOKEN`: fine-grained access token.
- `NP_NOTES_SYNC_PASSPHRASE`: strong shared encryption passphrase (16+ chars).
- `NP_NOTES_SYNC_BRANCH`: optional, defaults to `main`.
- **Explicit activation required**: process variable `NP_NOTES_SYNC_ENABLE=1`
  for isolated development, or a persistent `Data/NPNotesSync/sync_enabled.json`
  marker written by `tools/activate_np_notes_sync.ps1` after a verified backup.
  Storing DPAPI credentials alone never activates real-note transfer.

On Windows, use `tools/configure_np_notes_encrypted_sync.ps1` to store the token and passphrase with the current user's DPAPI. Never put secrets in commands or screenshots. `tools/test_np_notes_sync_live_synthetic.py` tests the encrypted private GitHub path using only synthetic note contents and deletes its test object from the current branch. `tools/check_np_notes_sync_ready.ps1` performs a local read-only preflight.

If a required setting is missing, cloud transport does **not** start.
Tokens/passphrases are not stored in the GitHub source repository.
For production, use OS credential storage rather than permanent plain
environment variables.

## Trash and permanent deletion (requires updated clients on every device)

- **Move to local Trash:** do not delete the encrypted GitHub note. Cancel obsolete
  outgoing jobs for that UUID, and do not re-import the same UUID merely because
  it is now only in local Trash. The note can be restored normally.
- **Permanently delete from Trash / Empty Trash:** after an explicit GUI
  confirmation, write a durable local deletion intent *before* removing the
  Trash folder. Commit that intent to the SQLite queue only after removal.
  If the app crashes after removing the folder, startup reconciles the
  prepared intent. A missing local UUID alone is **never** proof of deletion.
- **Offline:** keep the deletion intent until GitHub becomes reachable; retry
  automatically rather than blocking local Trash operations on the internet.
- **Online:** require a private repository and an exact acknowledged remote Git
  blob SHA. Create an AES-GCM encrypted tombstone in
  `tombstones/<uuid>.json`, then conditionally delete
  `encrypted/<uuid>.json`. Retain the tombstone to prevent a modern second
  device from re-uploading the deleted UUID. Refuse to delete an unexpectedly
  newer remote revision; preserve the pending deletion for explicit resolution.
- **Other updated devices:** authenticated tombstones suppress stale uploads
  and stage local active copies for safe movement into local Trash by the GUI
  thread. Open/unsaved notes are deferred. A recovered Trash copy with a
  tombstoned UUID cannot simply be restored as the original UUID.
- **Compatibility:** every device must install this version before using
  permanent deletion; older clients do not understand tombstones and can
  re-upload deleted notes. Existing notes already in local Trash are not
  retroactively deleted by upgrading the client.
- **Git history:** deleting a file removes it from the repository's current
  branch only. Older commits can still contain encrypted versions. Permanent
  removal from Git history requires a separate history-rewrite/rotation
  procedure, which this feature deliberately does not perform.

## Deliberate safety boundaries

- Tests use only temporary synthetic notes and fake network responses.
- The PR does not create a data repository, create tokens, enable production
  credentials, or migrate existing user data.
- Concurrent edits are preserved but **not auto-merged**: the remote revision
  remains encrypted in quarantine. The settings action
  **Сохранить конфликт как отдельную заметку** imports a selected remote
  revision with a new UUID without modifying the original.
  Unchanged local notes can fast-forward to remote revisions only after
  backup and main-thread precondition checks. These paths must pass isolated
  tests before activating real-note transfer.
- A single Contents API snapshot is limited by the program's 24 MiB encoded
  snapshot budget. Oversized content is retained locally and stays pending.
- Permanent deletions use authenticated tombstones and a durable offline queue.
  Remote-triggered deletions preserve local copies in Trash instead of
  permanently destroying them on other devices.
- An encryption key cannot be recovered from the GitHub repository.
  Keep a separate secure backup of the passphrase.
- Adding a private repository and secret handling is necessary before
  production enablement, and must be validated on two isolated machines.

## Test command

From the CODE repository root:

```shell
python -m pip install -r Other_dev/noteapp/requirements-sync.txt
python -m unittest -v tests.test_np_notes_offline_sync tests.test_np_notes_encrypted_sync tests.test_np_notes_sync_snapshot tests.test_np_notes_sync_service tests.test_np_notes_incoming_sync tests.test_np_notes_sync_privacy tests.test_np_notes_sync_credentials tests.test_np_notes_trash_delete_sync
```

These tests never read the real `Launcher/Data` directory.
