# NP Notes editor audit — 25 November 2026

## Scope and safety
A comprehensive automated audit of the desktop rich-text editor (EditorMixin,
CustomTextEdit, dropdowns, and selected real NotesApp toolbar actions).
Windows Qt offscreen tests use synthetic text and a disposable Launcher/Data.
No production notes, attachments, passwords, tokens, or DPAPI data accessed.

## Automated coverage
- Character formatting: bold, italic, underline, strike, fonts, sizes, foreground and background colors.
- Paragraph formatting: horizontal alignment, H1/H2/H3, line-height, after-paragraph spacing, reset formatting.
- Bullets, numbered lists, checklists: selection, Enter continuation, checkbox toggling.
- Hyperlinks: creation, changing URL, removing link and preserving display text.
- Tables: insertion, row/column insertion/deletion, deleting whole structure without erasing surrounding text.
- Horizontal lines and UPD template, HTML round-trip.
- Inline dropdown tokens: insertion, value change, saving and reloading.
- Clipboard: rich-text, plain-text, HTML paste, image callback, punctuation-only context menu.
- Audio-file link filename HTML escaping.
- Real NotesApp toolbar: bold, font selection, spacing, horizontal rule, saving and reopening a synthetic note.json.
- Existing tests also cover undo/redo history, content search, autosave, note switching, snapshots, sync safeguards.

## Fixed defects
1. Existing link editing crashed with AttributeError: helper accidentally nested in insert_link. Now a real EditorMixin method.
2. Changing a selected font family reset the point size and could lose styling. Now only font family changes.
3. Delete entire table cleared cell content but left table frame. Now removes all table rows, deleting the table frame.
4. Reset formatting left custom line-height and paragraph-bottom margin. Now resets both to defaults.
5. Dropdown selected value accumulated a visible triangle glyph after Qt HTML round-trip. Now strips decorative arrow.
6. Audio filename was interpolated unescaped in HTML. Now HTML-escaped.
7. Rich/plain copy actions were missing in the context menu when no alphabetic word was under the mouse. Now always available.

## Coverage limits
Automated success does not establish that every scenario works on every device.
The following require separate device/integration tests:
- Microphone, audio recording, codecs and Windows permissions.
- Drawing tablet/stylus, complex drawings and export.
- Drag-and-drop of real images/files from external applications.
- Spelling dictionaries, online grammar providers and third-party plugins.
- Opening links or local files in external applications.
- Complicated merged/split table-cell layouts.
- Concurrent editing and live GitHub sync: handled by separate sync test suite, not this editor UI audit.

## Tests and release discipline
New tests: tests/test_np_notes_editor_audit_qt.py.
Extended: tests/test_np_notes_full_app_qt.py.
CI: NP Notes integrity checks (Windows, Linux, Qt full-app smoke).
Publish version manifest only after all CI jobs succeed.
