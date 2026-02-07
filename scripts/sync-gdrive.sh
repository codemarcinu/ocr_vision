#!/bin/bash
# Second Brain <-> Google Drive bidirectional selective sync
# Runs on HOST as systemd timer. Uses rclone copy (never sync — no deletions).
#
# Usage:
#   ./scripts/sync-gdrive.sh             # full bidirectional sync
#   ./scripts/sync-gdrive.sh --inbox     # inbox download only
#   ./scripts/sync-gdrive.sh --upload    # vault upload only
#   ./scripts/sync-gdrive.sh --dry-run   # preview without changes
#
# Config: /etc/secondbrain/gdrive.env (or env vars)
# Logs:   /var/log/secondbrain-gdrive-sync.log

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────

CONFIG_FILE="/etc/secondbrain/gdrive.env"
if [ -f "$CONFIG_FILE" ]; then
    # shellcheck source=/dev/null
    source "$CONFIG_FILE"
fi

RCLONE_REMOTE="${RCLONE_REMOTE:-gdrive:SecondBrain}"
VAULT_PARAGONY="${VAULT_PARAGONY:-/home/marcin/Dokumenty/sejf/2brain/zakupy/paragony}"
VAULT_SUMMARIES="${VAULT_SUMMARIES:-/home/marcin/Dokumenty/sejf/2brain/artykuly}"
VAULT_BOOKMARKS="${VAULT_BOOKMARKS:-/home/marcin/Dokumenty/sejf/2brain/zakupy/bookmarks}"
LOCAL_INBOX="${LOCAL_INBOX:-/home/marcin/Dokumenty/projekty/ocr_vision/paragony/inbox}"
SYNC_LOG="${SYNC_LOG:-/var/log/secondbrain-gdrive-sync.log}"
SYNC_STATUS_FILE="${SYNC_STATUS_FILE:-/tmp/secondbrain-gdrive-sync-status.json}"
GDRIVE_INBOX_MAX_AGE="${GDRIVE_INBOX_MAX_AGE:-72h}"
LOCK_FILE="/tmp/secondbrain-gdrive-sync.lock"

# ─── Parse arguments ─────────────────────────────────────────────────────────

MODE="full"
DRY_RUN=""

for arg in "$@"; do
    case "$arg" in
        --inbox)   MODE="inbox" ;;
        --upload)  MODE="upload" ;;
        --dry-run) DRY_RUN="--dry-run" ;;
        --help|-h)
            echo "Usage: $0 [--inbox|--upload|--dry-run]"
            echo "  --inbox    Download from Drive inbox only"
            echo "  --upload   Upload vault to Drive only"
            echo "  --dry-run  Preview changes without syncing"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg"
            exit 1
            ;;
    esac
done

# ─── Helpers ─────────────────────────────────────────────────────────────────

log() {
    local level="$1"
    shift
    local msg="$(date '+%Y-%m-%d %H:%M:%S') [$level] $*"
    echo "$msg" >> "$SYNC_LOG" 2>/dev/null || true
    if [ -t 1 ]; then
        echo "$msg"
    fi
}

# Track file counts for status
INBOX_DOWNLOADED=0
PARAGONY_UPLOADED=0
SUMMARIES_UPLOADED=0
BOOKMARKS_UPLOADED=0
SYNC_ERROR=""

count_transferred() {
    # Parse rclone output for transferred file count
    local output="$1"
    local count
    count=$(echo "$output" | grep -oP 'Transferred:\s+\K\d+' | head -1 || echo "0")
    echo "${count:-0}"
}

write_status() {
    local success="$1"
    local duration="$2"
    cat > "$SYNC_STATUS_FILE" <<STATUSEOF
{
  "last_run": "$(date -Iseconds)",
  "success": $success,
  "mode": "$MODE",
  "inbox_downloaded": $INBOX_DOWNLOADED,
  "paragony_uploaded": $PARAGONY_UPLOADED,
  "summaries_uploaded": $SUMMARIES_UPLOADED,
  "bookmarks_uploaded": $BOOKMARKS_UPLOADED,
  "duration_sec": $duration,
  "dry_run": $([ -n "$DRY_RUN" ] && echo "true" || echo "false"),
  "error": $([ -n "$SYNC_ERROR" ] && echo "\"$SYNC_ERROR\"" || echo "null")
}
STATUSEOF
}

# ─── Lock ────────────────────────────────────────────────────────────────────

exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    log "WARN" "Another sync is already running (lock: $LOCK_FILE)"
    exit 2
fi

# ─── Pre-flight checks ──────────────────────────────────────────────────────

if ! command -v rclone &>/dev/null; then
    log "ERROR" "rclone not found. Install: sudo apt install rclone"
    SYNC_ERROR="rclone not installed"
    write_status "false" "0"
    exit 1
fi

# Ensure log directory exists
mkdir -p "$(dirname "$SYNC_LOG")" 2>/dev/null || true

# Ensure inbox directory exists
mkdir -p "$LOCAL_INBOX" 2>/dev/null || true

# ─── Sync functions ──────────────────────────────────────────────────────────

sync_inbox_from_drive() {
    log "INFO" "Downloading inbox from $RCLONE_REMOTE/inbox/ -> $LOCAL_INBOX/"
    local output
    output=$(rclone copy "$RCLONE_REMOTE/inbox/" "$LOCAL_INBOX/" \
        --max-age "$GDRIVE_INBOX_MAX_AGE" \
        --update \
        --stats-one-line \
        --stats 0 \
        --log-file="$SYNC_LOG" \
        --log-level INFO \
        $DRY_RUN \
        -v 2>&1) || true
    INBOX_DOWNLOADED=$(count_transferred "$output")
    log "INFO" "Inbox: $INBOX_DOWNLOADED file(s) downloaded"
}

sync_paragony_to_drive() {
    if [ ! -d "$VAULT_PARAGONY" ]; then
        log "WARN" "Paragony directory not found: $VAULT_PARAGONY"
        return
    fi
    log "INFO" "Uploading paragony: $VAULT_PARAGONY/ -> $RCLONE_REMOTE/paragony/"
    local output
    output=$(rclone copy "$VAULT_PARAGONY/" "$RCLONE_REMOTE/paragony/" \
        --update \
        --stats-one-line \
        --stats 0 \
        --log-file="$SYNC_LOG" \
        --log-level INFO \
        $DRY_RUN \
        -v 2>&1) || true
    PARAGONY_UPLOADED=$(count_transferred "$output")
    log "INFO" "Paragony: $PARAGONY_UPLOADED file(s) uploaded"
}

sync_summaries_to_drive() {
    if [ ! -d "$VAULT_SUMMARIES" ]; then
        log "WARN" "Summaries directory not found: $VAULT_SUMMARIES"
        return
    fi
    log "INFO" "Uploading summaries: $VAULT_SUMMARIES/ -> $RCLONE_REMOTE/summaries/"
    local output
    output=$(rclone copy "$VAULT_SUMMARIES/" "$RCLONE_REMOTE/summaries/" \
        --update \
        --stats-one-line \
        --stats 0 \
        --log-file="$SYNC_LOG" \
        --log-level INFO \
        $DRY_RUN \
        -v 2>&1) || true
    SUMMARIES_UPLOADED=$(count_transferred "$output")
    log "INFO" "Summaries: $SUMMARIES_UPLOADED file(s) uploaded"
}

sync_bookmarks_to_drive() {
    if [ ! -d "$VAULT_BOOKMARKS" ]; then
        log "WARN" "Bookmarks directory not found: $VAULT_BOOKMARKS"
        return
    fi
    log "INFO" "Uploading bookmarks: $VAULT_BOOKMARKS/ -> $RCLONE_REMOTE/bookmarks/"
    local output
    output=$(rclone copy "$VAULT_BOOKMARKS/" "$RCLONE_REMOTE/bookmarks/" \
        --update \
        --stats-one-line \
        --stats 0 \
        --log-file="$SYNC_LOG" \
        --log-level INFO \
        $DRY_RUN \
        -v 2>&1) || true
    BOOKMARKS_UPLOADED=$(count_transferred "$output")
    log "INFO" "Bookmarks: $BOOKMARKS_UPLOADED file(s) uploaded"
}

# ─── Main ────────────────────────────────────────────────────────────────────

START_TIME=$(date +%s)
log "INFO" "=== Sync started (mode=$MODE${DRY_RUN:+, dry-run}) ==="

trap 'log "ERROR" "Sync failed with exit code $?"; SYNC_ERROR="unexpected error"; write_status "false" "$(($(date +%s) - START_TIME))"' ERR

# Download inbox from Drive
if [ "$MODE" = "full" ] || [ "$MODE" = "inbox" ]; then
    sync_inbox_from_drive
fi

# Upload vault content to Drive
if [ "$MODE" = "full" ] || [ "$MODE" = "upload" ]; then
    sync_paragony_to_drive
    sync_summaries_to_drive
    sync_bookmarks_to_drive
fi

DURATION=$(($(date +%s) - START_TIME))
log "INFO" "=== Sync completed in ${DURATION}s ==="

write_status "true" "$DURATION"
