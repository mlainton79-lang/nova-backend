#!/bin/bash
BASE="https://web-production-be42b.up.railway.app"
TOKEN="nova-dev-token"
H="Authorization: Bearer $TOKEN"

echo "=== TONY STATUS CHECK ==="
echo ""

check() {
    local name=$1
    local url=$2
    result=$(curl -s -o /dev/null -w "%{http_code}" "$url" -H "$H" 2>/dev/null)
    if [ "$result" = "200" ]; then
        echo "✅ $name"
    else
        echo "❌ $name (HTTP $result)"
    fi
}

check "Server health" "$BASE/api/v1/health"
check "Chat stream" "$BASE/api/v1/health"
check "Gmail" "$BASE/api/v1/gmail/accounts"
check "Cases" "$BASE/api/v1/cases"
check "Goals" "$BASE/api/v1/goals"
check "Alerts" "$BASE/api/v1/alerts"
check "Calendar" "$BASE/api/v1/calendar/test"
check "Vision" "$BASE/api/v1/vision/test"
check "Capabilities" "$BASE/api/v1/capabilities/active"
check "Agent" "$BASE/api/v1/agent/runs"

echo ""
echo "=== CASE STATUS ==="
curl -s "$BASE/api/v1/cases" -H "$H" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    for c in d.get('cases',[]):
        status='✅' if c['status']=='ready' else '⏳'
        print(f\"  {status} {c['name']}: {c['status']} ({c['total_emails']} emails, {c['total_chunks']} chunks)\")
except: print('  Could not parse cases')
" 2>/dev/null

echo ""
echo "=== GOALS ==="
curl -s "$BASE/api/v1/goals" -H "$H" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    for g in d.get('goals',[]):
        marker='🔴' if g['priority']=='urgent' else '🟡' if g['priority']=='high' else '🟢'
        print(f\"  {marker} {g['title']}\")
except: print('  Could not parse goals')
" 2>/dev/null

echo ""
echo "=== ALERTS ==="
curl -s "$BASE/api/v1/alerts" -H "$H" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    count=d.get('count',0)
    urgent=d.get('urgent',0)
    print(f'  {count} unread alerts, {urgent} urgent')
except: print('  Could not parse alerts')
" 2>/dev/null

echo ""
echo "========================="
