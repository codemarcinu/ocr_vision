#!/bin/bash
# Comprehensive test suite for Mobile PWA auth, endpoints, and static assets
# Usage: bash scripts/test_mobile_pwa.sh

set -uo pipefail

BASE="http://localhost:8000"
PASS=0
FAIL=0
TOTAL=0
COOKIE_JAR=$(mktemp)
trap "rm -f $COOKIE_JAR" EXIT

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

check() {
  local description="$1"
  local expected="$2"
  local actual="$3"

  TOTAL=$((TOTAL + 1))
  if [ "$actual" = "$expected" ]; then
    PASS=$((PASS + 1))
    echo -e "  ${GREEN}✓${NC} $description (${actual})"
  else
    FAIL=$((FAIL + 1))
    echo -e "  ${RED}✗${NC} $description — expected ${expected}, got ${actual}"
  fi
}

AUTH_TOKEN=$(docker exec pantry-api env | grep AUTH_TOKEN | cut -d= -f2)

# ============================================================================
echo -e "\n${YELLOW}=== 1. PUBLIC PATHS (no auth required) ===${NC}"
# ============================================================================

check "/health" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/health)"
check "/metrics" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/metrics)"
check "/login" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/login)"
check "/static/css/mobile.css" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/static/css/mobile.css)"
check "/static/js/mobile.js" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/static/js/mobile.js)"
check "/static/js/htmx.min.js" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/static/js/htmx.min.js)"
check "/static/js/marked.min.js" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/static/js/marked.min.js)"
check "/static/js/purify.min.js" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/static/js/purify.min.js)"
check "/static/js/offline-queue.js" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/static/js/offline-queue.js)"
check "/static/manifest.json" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/static/manifest.json)"
check "/static/icons/icon-192.png" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/static/icons/icon-192.png)"
check "/static/icons/icon-512.png" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/static/icons/icon-512.png)"
check "/sw.js" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/sw.js)"
check "/offline.html" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/offline.html)"
check "/api/push/vapid-key" "200" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/api/push/vapid-key)"
check "/favicon.ico (public, 404 OK)" "404" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/favicon.ico)"

# ============================================================================
echo -e "\n${YELLOW}=== 2. UNAUTHENTICATED — web UI paths redirect to /login ===${NC}"
# ============================================================================

check "/m/ → 303" "303" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/m/)"
check "/m  → 303 (no trailing slash)" "303" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/m)"
check "/m/notatki → 303" "303" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/m/notatki)"
check "/m/paragony → 303" "303" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/m/paragony)"
check "/m/wiedza → 303" "303" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/m/wiedza)"
check "/app/ → 303" "303" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/app/)"
check "/app  → 303 (no trailing slash)" "303" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/app)"
check "/app/czat/ → 303" "303" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/app/czat/)"
check "/ → 303" "303" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/)"

# ============================================================================
echo -e "\n${YELLOW}=== 3. UNAUTHENTICATED — API paths return 401 ===${NC}"
# ============================================================================

check "POST /chat/message → 401" "401" "$(curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/chat/message -H 'Content-Type: application/json' -d '{"message":"test"}')"
check "GET /chat/sessions → 401" "401" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/chat/sessions)"
check "GET /chat/suggestions → 401" "401" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/chat/suggestions)"
check "GET /receipts → 401" "401" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/receipts)"
check "GET /notes → 401" "401" "$(curl -s -o /dev/null -w '%{http_code}' $BASE/notes)"

# ============================================================================
echo -e "\n${YELLOW}=== 4. LOGIN & SESSION ===${NC}"
# ============================================================================

curl -s -c "$COOKIE_JAR" -o /dev/null \
  -X POST "$BASE/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "token=$AUTH_TOKEN"

TOTAL=$((TOTAL + 1))
if grep -q "session_token" "$COOKIE_JAR" 2>/dev/null; then
  PASS=$((PASS + 1))
  echo -e "  ${GREEN}✓${NC} POST /login sets session_token cookie"
else
  FAIL=$((FAIL + 1))
  echo -e "  ${RED}✗${NC} POST /login did NOT set session_token cookie"
fi

# ============================================================================
echo -e "\n${YELLOW}=== 5. WITH SESSION COOKIE — mobile pages ===${NC}"
# ============================================================================

check "/m/ + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR $BASE/m/)"
check "/m + cookie (follow redirect)" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR -L $BASE/m)"
check "/m/notatki + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR $BASE/m/notatki)"
check "/m/paragony + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR $BASE/m/paragony)"
check "/m/wiedza + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR $BASE/m/wiedza)"

# ============================================================================
echo -e "\n${YELLOW}=== 6. WITH SESSION COOKIE — API calls from mobile JS ===${NC}"
# ============================================================================

check "GET /chat/sessions + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR "$BASE/chat/sessions?limit=20")"
check "GET /chat/suggestions + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR $BASE/chat/suggestions)"
check "POST /chat/message + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR -X POST $BASE/chat/message -H 'Content-Type: application/json' -d '{"message":"test"}')"
check "GET /api/push/vapid-key" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR $BASE/api/push/vapid-key)"

# ============================================================================
echo -e "\n${YELLOW}=== 7. WITH BEARER TOKEN — API clients ===${NC}"
# ============================================================================

check "GET /chat/sessions + Bearer" "200" "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $AUTH_TOKEN" $BASE/chat/sessions)"
check "GET /chat/suggestions + Bearer" "200" "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $AUTH_TOKEN" $BASE/chat/suggestions)"
check "POST /chat/message + Bearer" "200" "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $AUTH_TOKEN" -H 'Content-Type: application/json' -d '{"message":"test bearer"}' -X POST $BASE/chat/message)"
check "GET /receipts + Bearer" "200" "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $AUTH_TOKEN" $BASE/receipts)"
check "GET /notes/ + Bearer" "200" "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $AUTH_TOKEN" $BASE/notes/)"

# ============================================================================
echo -e "\n${YELLOW}=== 8. DESKTOP WEB UI — with cookie ===${NC}"
# ============================================================================

check "/app/ + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR $BASE/app/)"
check "/app/czat/ + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR $BASE/app/czat/)"
check "/app/paragony/ + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR $BASE/app/paragony/)"
check "/app/notatki/ + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR $BASE/app/notatki/)"
check "/app/zakladki/ + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR $BASE/app/zakladki/)"
check "/app/spizarnia/ + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR $BASE/app/spizarnia/)"
check "/app/analityka/ + cookie" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b $COOKIE_JAR $BASE/app/analityka/)"

# ============================================================================
echo -e "\n${YELLOW}=== 9. SERVICE WORKER & PWA ===${NC}"
# ============================================================================

TOTAL=$((TOTAL + 1))
SW_VERSION=$(curl -s "$BASE/sw.js" | grep -oP "CACHE_VERSION = 'v\K[0-9]+")
if [ "$SW_VERSION" = "3" ]; then
  PASS=$((PASS + 1))
  echo -e "  ${GREEN}✓${NC} Service Worker version is v3"
else
  FAIL=$((FAIL + 1))
  echo -e "  ${RED}✗${NC} Service Worker version is v${SW_VERSION} (expected v3)"
fi

TOTAL=$((TOTAL + 1))
MANIFEST_OK=$(curl -s "$BASE/static/manifest.json" | python3 -c "
import sys, json
try:
    m = json.load(sys.stdin)
    assert 'name' in m, 'missing name'
    assert 'start_url' in m, 'missing start_url'
    assert 'icons' in m, 'missing icons'
    print('ok')
except Exception as e:
    print(f'fail: {e}')
")
if [ "$MANIFEST_OK" = "ok" ]; then
  PASS=$((PASS + 1))
  echo -e "  ${GREEN}✓${NC} manifest.json valid (name, start_url, icons)"
else
  FAIL=$((FAIL + 1))
  echo -e "  ${RED}✗${NC} manifest.json: $MANIFEST_OK"
fi

# ============================================================================
echo -e "\n${YELLOW}=== 10. REGRESSION — RSS feed fetch ===${NC}"
# ============================================================================

check "GET /rss/feeds + Bearer" "200" "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $AUTH_TOKEN" $BASE/rss/feeds)"

# ============================================================================
echo -e "\n${YELLOW}=== 11. REGRESSION — RAG startup ===${NC}"
# ============================================================================

TOTAL=$((TOTAL + 1))
RAG_LOGS=$(docker logs pantry-api 2>&1)
if echo "$RAG_LOGS" | grep -Eq "app\.main.*RAG:.*embeddings found|app\.main.*RAG:.*starting background reindex"; then
  PASS=$((PASS + 1))
  echo -e "  ${GREEN}✓${NC} RAG startup OK"
else
  FAIL=$((FAIL + 1))
  echo -e "  ${RED}✗${NC} RAG startup failed"
fi

TOTAL=$((TOTAL + 1))
if ! docker logs pantry-api 2>&1 | grep -q "RAG startup check failed"; then
  PASS=$((PASS + 1))
  echo -e "  ${GREEN}✓${NC} No RAG startup crash"
else
  FAIL=$((FAIL + 1))
  echo -e "  ${RED}✗${NC} RAG startup crash found in logs"
fi

# ============================================================================
echo -e "\n${YELLOW}=== 12. NO 401 SPAM ===${NC}"
# ============================================================================

TOTAL=$((TOTAL + 1))
METRICS_401=$(docker logs --since 30s pantry-api 2>&1 | grep "GET /metrics" | grep -c "401" || true)
if [ "$METRICS_401" -eq 0 ]; then
  PASS=$((PASS + 1))
  echo -e "  ${GREEN}✓${NC} No /metrics 401 spam"
else
  FAIL=$((FAIL + 1))
  echo -e "  ${RED}✗${NC} Found $METRICS_401 /metrics 401 entries"
fi

# ============================================================================
# SUMMARY
# ============================================================================

echo -e "\n${YELLOW}======================================${NC}"
if [ "$FAIL" -eq 0 ]; then
  echo -e "${GREEN}ALL $TOTAL TESTS PASSED ✓${NC}"
else
  echo -e "${RED}FAILED: $FAIL / $TOTAL${NC}  (${GREEN}passed: $PASS${NC})"
fi
echo -e "${YELLOW}======================================${NC}"

exit $FAIL
