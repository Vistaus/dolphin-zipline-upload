# Changelog

## 1.1.0 — 2026-09-19

- Windowed settings GUI (PySide6) with dark green-black/teal theme and
  sidebar navigation: Server / Upload Options / Behaviour / History pages,
  background-threaded connection test, upload history browser, unsaved-
  changes guard. Ships as a private venv install (`install.sh`) or a
  one-time guided download on first configure; kdialog menus remain the
  automatic fallback, so the addon itself still has zero dependencies.
- Import reconciliation policy centralised in `reconcile_import()`.
- Context-menu entries promoted to the top level of Dolphin's right-click
  menu (`X-KDE-Priority=TopLevel`) — no more "Actions" submenu nesting.
- Settings window sizes itself to the screen (opens at 840×740 on typical
  displays, clamped to smaller screens) and never crops pages horizontally.
- Hardening: browser-open action only accepts http(s) URLs; clipboard text
  passed to wl-copy via stdin.
- KDE Store packaging: portable service-menu Exec (no hard-coded paths),
  flat release tarball (`make-store-package.sh`).

## 1.0.0 — 2026-09-06

- Initial release: Dolphin service menu upload action, streamed multipart
  uploads with byte-accurate progress (kdialog bar with Cancel, or
  notification progress), Zipline shell-script importer, x-zipline-* upload
  options, Klipper/wl-copy/xclip/xsel clipboard chain with Wayland/X11
  auto-detection, history log, optional post-upload hook.
