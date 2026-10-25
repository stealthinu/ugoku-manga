#!/usr/bin/env bash
# Hygiene gate: case-insensitive deny-list over every tracked or new (non-ignored) file, and over commit metadata.
# Exit 1 on any hit. Hits are printed as file:line only, never the matching text.
#
# The generic patterns below are public. Project-private terms (names, internal hosts, slugs) are never committed: they are read
# from the file in $UGOKU_DENY_FILE (default ~/.config/ugoku/deny-patterns.txt), one extended regex per line, '#' comments allowed,
# and from $UGOKU_DENY_PATTERNS (newline-separated, e.g. a CI secret). Without either, only the generic patterns run.
set -u
cd "$(git rev-parse --show-toplevel)"
PATTERNS=(
  '/home/[a-z]|/Users/[A-Za-z]|C:\\Users'
  '100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]+\.[0-9]+'
  '\b[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+'
  '\.ts\.net\b|tailscale'
  '-----BEGIN [A-Z ]*PRIVATE KEY'
  '@[a-z0-9-]+\.(com|net|org|io|jp)\b'
)
DENY_FILE="${UGOKU_DENY_FILE:-$HOME/.config/ugoku/deny-patterns.txt}"
n_private=0
add_private() { while IFS= read -r line; do line="${line%$'\r'}"; [[ -z "$line" || "$line" == \#* ]] && continue; PATTERNS+=("$line"); n_private=$((n_private + 1)); done; }
[ -f "$DENY_FILE" ] && add_private < "$DENY_FILE"
[ -n "${UGOKU_DENY_PATTERNS:-}" ] && add_private <<< "$UGOKU_DENY_PATTERNS"
[ $n_private -eq 0 ] && echo "deny-grep: no private pattern list ($DENY_FILE or UGOKU_DENY_PATTERNS); generic patterns only" >&2
rc=0
mapfile -d '' FILES < <(git ls-files --cached --others --exclude-standard -z | grep -zv -e '^scripts/deny_grep.sh$' -e '^\.gitleaks.toml$')
for i in "${!PATTERNS[@]}"; do
  pat="${PATTERNS[$i]}"
  for f in "${FILES[@]}"; do
    [ -f "$f" ] || continue
    if grep -I -i -n -E -q -- "$pat" "$f" 2>/dev/null; then
      # allowlist: noreply@ addresses
      hits=$(grep -I -i -n -E -- "$pat" "$f" | grep -v -i 'noreply@' | cut -d: -f1 | tr '\n' ',' )
      if [ -n "$hits" ]; then echo "DENY pattern#$i $f:${hits%,}"; rc=1; fi
    fi
  done
done
# commit metadata (author, message) and, with --history, full diffs
if git rev-parse HEAD >/dev/null 2>&1; then
  SRC=$(git log --format='%an %ae %cn %ce %B')
  [ "${1:-}" = "--history" ] && SRC=$(git log -p --format='%an %ae %B' -- . ':!scripts/deny_grep.sh' ':!.gitleaks.toml')
  for i in "${!PATTERNS[@]}"; do
    if printf '%s\n' "$SRC" | grep -i -E -v 'noreply@' | grep -q -i -E -- "${PATTERNS[$i]}"; then echo "DENY history pattern#$i"; rc=1; fi
  done
fi
[ $rc -eq 0 ] && echo "deny-grep: 0 hits (${#PATTERNS[@]} patterns, $n_private private)"
exit $rc
