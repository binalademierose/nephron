SweetAlert2 (interactive pop-ups) - not shipped with the project; download it once:

  1. Open:  https://cdn.jsdelivr.net/npm/sweetalert2@11/dist/sweetalert2.all.min.js
  2. Save it here as:  static/vendor/sweetalert2/sweetalert2.all.min.js

The app detects the file when it starts (restart it after adding the file). Until it is present, every pop-up
falls back to Nephron's own built-in dialog and toasts, so nothing breaks without it.
