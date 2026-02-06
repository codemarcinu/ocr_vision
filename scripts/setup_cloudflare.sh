#!/bin/bash
# Cloudflare Security Setup Script for brain.marubo.ovh
# Usage: ./scripts/setup_cloudflare.sh <API_TOKEN>

set -euo pipefail

API_TOKEN="${1:-}"
DOMAIN="marubo.ovh"
API="https://api.cloudflare.com/client/v4"

if [ -z "$API_TOKEN" ]; then
    echo "Użycie: $0 <CLOUDFLARE_API_TOKEN>"
    echo ""
    echo "Utwórz token na: https://dash.cloudflare.com/profile/api-tokens"
    echo "Uprawnienia: Zone Settings (Edit) + Zone WAF (Edit)"
    exit 1
fi

# Helper function
cf_api() {
    local method="$1" endpoint="$2" data="${3:-}"
    if [ -n "$data" ]; then
        curl -s -X "$method" "$API$endpoint" \
            -H "Authorization: Bearer $API_TOKEN" \
            -H "Content-Type: application/json" \
            -d "$data"
    else
        curl -s -X "$method" "$API$endpoint" \
            -H "Authorization: Bearer $API_TOKEN" \
            -H "Content-Type: application/json"
    fi
}

check_result() {
    local result="$1" name="$2"
    if echo "$result" | python3 -c "import sys,json; r=json.load(sys.stdin); sys.exit(0 if r.get('success') else 1)" 2>/dev/null; then
        echo "  ✅ $name"
    else
        local errors
        errors=$(echo "$result" | python3 -c "import sys,json; r=json.load(sys.stdin); print('; '.join(e.get('message','?') for e in r.get('errors',[])))" 2>/dev/null || echo "Unknown error")
        echo "  ❌ $name: $errors"
    fi
}

echo "🔧 Cloudflare Security Setup for $DOMAIN"
echo "==========================================="
echo ""

# 1. Verify token and get Zone ID
echo "[1/6] Weryfikacja tokena i pobieranie Zone ID..."
ZONE_RESPONSE=$(cf_api GET "/zones?name=$DOMAIN")
ZONE_ID=$(echo "$ZONE_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['result'][0]['id'])" 2>/dev/null)

if [ -z "$ZONE_ID" ]; then
    echo "  ❌ Nie znaleziono Zone ID dla $DOMAIN. Sprawdź token i domenę."
    exit 1
fi
echo "  ✅ Zone ID: $ZONE_ID"
echo ""

# 2. SSL/TLS Settings
echo "[2/6] Konfiguracja SSL/TLS..."

result=$(cf_api PATCH "/zones/$ZONE_ID/settings/ssl" '{"value":"full"}')
check_result "$result" "SSL Mode: Full (Strict)"

result=$(cf_api PATCH "/zones/$ZONE_ID/settings/always_use_https" '{"value":"on"}')
check_result "$result" "Always Use HTTPS: On"

result=$(cf_api PATCH "/zones/$ZONE_ID/settings/min_tls_version" '{"value":"1.2"}')
check_result "$result" "Minimum TLS Version: 1.2"

result=$(cf_api PATCH "/zones/$ZONE_ID/settings/automatic_https_rewrites" '{"value":"on"}')
check_result "$result" "Automatic HTTPS Rewrites: On"

echo ""

# 3. Security Settings
echo "[3/6] Konfiguracja Security Settings..."

result=$(cf_api PATCH "/zones/$ZONE_ID/settings/security_level" '{"value":"high"}')
check_result "$result" "Security Level: High"

result=$(cf_api PATCH "/zones/$ZONE_ID/settings/browser_check" '{"value":"on"}')
check_result "$result" "Browser Integrity Check: On"

result=$(cf_api PATCH "/zones/$ZONE_ID/settings/challenge_ttl" '{"value":1800}')
check_result "$result" "Challenge Passage: 30 minutes"

echo ""

# 4. Security Rules (WAF Custom Rules)
echo "[4/6] Tworzenie Security Rules..."

# Get existing rulesets
RULESET_RESPONSE=$(cf_api GET "/zones/$ZONE_ID/rulesets?phase=http_request_firewall_custom")
RULESET_ID=$(echo "$RULESET_RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('result', [])
print(results[0]['id'] if results else '')
" 2>/dev/null)

# Build rules payload
RULES_PAYLOAD=$(cat <<'RULES_EOF'
{
  "rules": [
    {
      "expression": "(http.request.uri.path contains \"/docs\") or (http.request.uri.path contains \"/redoc\") or (http.request.uri.path contains \"/openapi.json\") or (http.request.uri.path contains \"/.env\") or (http.request.uri.path contains \"/alembic\")",
      "action": "block",
      "description": "Block sensitive paths"
    },
    {
      "expression": "(http.user_agent contains \"sqlmap\") or (http.user_agent contains \"nikto\") or (http.user_agent contains \"nmap\") or (http.user_agent contains \"masscan\") or (http.user_agent contains \"zgrab\") or (http.user_agent contains \"nuclei\") or (http.user_agent contains \"dirbuster\") or (http.user_agent contains \"gobuster\")",
      "action": "block",
      "description": "Block bad bots and scanners"
    },
    {
      "expression": "(ip.geoip.country ne \"PL\")",
      "action": "managed_challenge",
      "description": "Challenge non-PL traffic"
    },
    {
      "expression": "(http.request.uri.path contains \"/login\" and http.request.method eq \"POST\")",
      "action": "managed_challenge",
      "description": "Protect login endpoint"
    }
  ]
}
RULES_EOF
)

if [ -n "$RULESET_ID" ]; then
    # Update existing ruleset
    result=$(cf_api PUT "/zones/$ZONE_ID/rulesets/$RULESET_ID" "$RULES_PAYLOAD")
else
    # Create new ruleset
    RULES_PAYLOAD_WITH_META=$(cat <<'META_EOF'
{
  "name": "Security rules",
  "kind": "zone",
  "phase": "http_request_firewall_custom",
  "rules": [
    {
      "expression": "(http.request.uri.path contains \"/docs\") or (http.request.uri.path contains \"/redoc\") or (http.request.uri.path contains \"/openapi.json\") or (http.request.uri.path contains \"/.env\") or (http.request.uri.path contains \"/alembic\")",
      "action": "block",
      "description": "Block sensitive paths"
    },
    {
      "expression": "(http.user_agent contains \"sqlmap\") or (http.user_agent contains \"nikto\") or (http.user_agent contains \"nmap\") or (http.user_agent contains \"masscan\") or (http.user_agent contains \"zgrab\") or (http.user_agent contains \"nuclei\") or (http.user_agent contains \"dirbuster\") or (http.user_agent contains \"gobuster\")",
      "action": "block",
      "description": "Block bad bots and scanners"
    },
    {
      "expression": "(ip.geoip.country ne \"PL\")",
      "action": "managed_challenge",
      "description": "Challenge non-PL traffic"
    },
    {
      "expression": "(http.request.uri.path contains \"/login\" and http.request.method eq \"POST\")",
      "action": "managed_challenge",
      "description": "Protect login endpoint"
    }
  ]
}
META_EOF
)
    result=$(cf_api POST "/zones/$ZONE_ID/rulesets" "$RULES_PAYLOAD_WITH_META")
fi
check_result "$result" "4 Custom Security Rules"

echo ""

# 5. Rate Limiting Rule
echo "[5/6] Tworzenie Rate Limiting Rule..."

# Get rate limiting ruleset
RL_RESPONSE=$(cf_api GET "/zones/$ZONE_ID/rulesets?phase=http_ratelimit")
RL_RULESET_ID=$(echo "$RL_RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('result', [])
print(results[0]['id'] if results else '')
" 2>/dev/null)

RL_PAYLOAD=$(cat <<'RL_EOF'
{
  "rules": [
    {
      "expression": "(http.request.uri.path contains \"/process-receipt\") or (http.request.uri.path contains \"/ask\") or (http.request.uri.path contains \"/message\") or (http.request.uri.path contains \"/summarize\")",
      "action": "block",
      "action_parameters": {
        "response": {
          "status_code": 429,
          "content": "{\"error\": \"Too many requests\"}",
          "content_type": "application/json"
        }
      },
      "ratelimit": {
        "characteristics": ["ip.src"],
        "period": 60,
        "requests_per_period": 20,
        "mitigation_timeout": 60
      },
      "description": "API rate limit (20 req/min)"
    }
  ]
}
RL_EOF
)

if [ -n "$RL_RULESET_ID" ]; then
    result=$(cf_api PUT "/zones/$ZONE_ID/rulesets/$RL_RULESET_ID" "$RL_PAYLOAD")
else
    RL_PAYLOAD_WITH_META=$(cat <<'RL_META_EOF'
{
  "name": "Rate limiting rules",
  "kind": "zone",
  "phase": "http_ratelimit",
  "rules": [
    {
      "expression": "(http.request.uri.path contains \"/process-receipt\") or (http.request.uri.path contains \"/ask\") or (http.request.uri.path contains \"/message\") or (http.request.uri.path contains \"/summarize\")",
      "action": "block",
      "action_parameters": {
        "response": {
          "status_code": 429,
          "content": "{\"error\": \"Too many requests\"}",
          "content_type": "application/json"
        }
      },
      "ratelimit": {
        "characteristics": ["ip.src"],
        "period": 60,
        "requests_per_period": 20,
        "mitigation_timeout": 60
      },
      "description": "API rate limit (20 req/min)"
    }
  ]
}
RL_META_EOF
)
    result=$(cf_api POST "/zones/$ZONE_ID/rulesets" "$RL_PAYLOAD_WITH_META")
fi
check_result "$result" "Rate Limiting Rule (20 req/min)"

echo ""

# 6. Summary
echo "[6/6] Podsumowanie"
echo "==========================================="
echo ""
echo "Konfiguracja zakończona! Sprawdź wyniki powyżej."
echo ""
echo "Weryfikacja w dashboard:"
echo "  https://dash.cloudflare.com/$ZONE_ID/security/security-rules"
echo "  https://dash.cloudflare.com/$ZONE_ID/ssl-tls"
echo ""
echo "Test z zewnątrz:"
echo "  curl -s -o /dev/null -w '%{http_code}' https://brain.marubo.ovh/health     # 200"
echo "  curl -s -o /dev/null -w '%{http_code}' https://brain.marubo.ovh/docs       # 403 (blocked)"
echo "  curl -s -o /dev/null -w '%{http_code}' https://brain.marubo.ovh/receipts   # 401 (no token)"
