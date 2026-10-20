#!/usr/bin/env bash
# Fails when the repository (tracked or untracked, not ignored) contains a
# forbidden token. Run it locally before every push; CI runs it too.
#
# - the script itself is excluded: it has to contain the patterns;
# - *.lock files are excluded: base64 hashes there produce false hits.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# PCRE2 needs UTF-8 mode for case-insensitive matching of Cyrillic letters.
# git enables it when the locale is UTF-8, so pin one that exists everywhere.
export LC_ALL=C.UTF-8

# (*UTF) switches PCRE2 to UTF mode and (?i) folds case, so "Академия" and
# "дпар" match regardless of the capitalisation.
PATTERN='(*UTF)(?i)arlan|afm|академ|ДПАР|dpar|109\.199|84\.240'

# git grep exits 1 when nothing matches (the good outcome here) and above 1
# on real errors, which must not be mistaken for "no leaks".
status=0
matches=$(git grep --untracked -nP -e "$PATTERN" -- \
    ':!scripts/check_leaks.sh' ':!*.lock') || status=$?
if [ "$status" -gt 1 ]; then
    echo "git grep failed with status $status" >&2
    exit "$status"
fi

if [ -n "$matches" ]; then
    echo "$matches"
    echo "forbidden tokens found" >&2
    exit 1
fi

echo "no leaks"
