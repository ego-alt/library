# Library roadmap

Left over from the UX audit (October 2026; the audit itself is in git history). Everything else from it is done.

- **Fold genre into tags.** Search already matches genre with title, author and tags, and the separate genre filter is gone. Genre is still its own single field in the details panel. Merging it into tags is a data migration, so it waits for a decision (and, if wanted, turning an EPUB's `dc:subject` into tags on import).
