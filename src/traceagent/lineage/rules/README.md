# Lineage extraction rules

Per-language YAML rules for ast-grep extraction of `@trace("ALIAS")` bindings.

Language-specific comment kinds (V4 lesson):
  python: comment
  typescript: comment
  rust: line_comment
Symbol resolution descends wrapper nodes (TypeScript `export_statement`).

These YAML rules document the declarative contract; the Python binding in
extract.py uses the ast-grep-py API with the same kind/regex semantics so the
rules remain portable to `sg scan` in CI.
