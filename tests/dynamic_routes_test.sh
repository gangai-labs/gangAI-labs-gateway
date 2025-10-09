#!/bin/bash
# Fix Admin Roles and Test Dynamic Routes
BASE_URL="http://localhost:8000"

echo "========================================"
echo "FIX ADMIN ROLES & TEST DYNAMIC ROUTES"
echo "========================================"

# ============================================================
# 1. FIX ADMIN ROLE IN REDIS
# ============================================================
echo -e "\n1. Fixing Admin Role in Redis"
echo "----------------------------------------"
redis-cli HSET users:admin role "admin"
echo "✅ Admin role updated to 'admin'"

# ============================================================
# 2. LOGIN AS ADMIN (Now with proper role)
# ============================================================
echo -e "\n2. Login as Admin (With Fixed Role)"
echo "----------------------------------------"
ADMIN_RESPONSE=$(curl -s -X POST "${BASE_URL}/sessions/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin"
  }')

echo "$ADMIN_RESPONSE"

ADMIN_TOKEN=$(echo "$ADMIN_RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
echo "Admin Token: $ADMIN_TOKEN"

# ============================================================
# 3. TEST ADMIN ENDPOINTS
# ============================================================
echo -e "\n3. Test Admin Endpoints"
echo "----------------------------------------"

# Test list APIs
echo "- List APIs:"
curl -s -X GET "${BASE_URL}/api/list" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"

# Test register API
echo -e "\n- Register API:"
curl -s -X POST "${BASE_URL}/api/register" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -d '{
    "name": "test_api",
    "base_url": "https://httpbin.org",
    "path": "get",
    "method": "GET",
    "require_auth": false,
    "ws_supported": false
  }'

# Test proxy route
echo -e "\n- Test Proxy Route:"
curl -s -X GET "${BASE_URL}/api/proxy/test_api"

# Test unregister
echo -e "\n- Unregister API:"
curl -s -X DELETE "${BASE_URL}/api/unregister?name=test_api" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"

# ============================================================
# 4. CREATE MULTIPLE ADMINS (Optional)
# ============================================================
echo -e "\n4. Create Additional Admin Users"
echo "----------------------------------------"

# Register superuser (will be admin based on username)
SUPERUSER_RESPONSE=$(curl -s -X POST "${BASE_URL}/sessions/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "superuser",
    "email": "superuser@example.com",
    "password": "superpass123"
  }')

echo "$SUPERUSER_RESPONSE"

# Manually set superuser as admin
redis-cli HSET users:superuser role "admin"
echo "✅ Superuser promoted to admin"

# ============================================================
# 5. VERIFY MULTIPLE ADMINS
# ============================================================
echo -e "\n5. Verify Multiple Admins"
echo "----------------------------------------"

# Login as superuser
SUPER_RESPONSE=$(curl -s -X POST "${BASE_URL}/sessions/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "superuser",
    "password": "superpass123"
  }')

SUPER_TOKEN=$(echo "$SUPER_RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

# Test superuser admin access
echo "- Superuser List APIs:"
curl -s -X GET "${BASE_URL}/api/list" \
  -H "Authorization: Bearer ${SUPER_TOKEN}"

echo -e "\n========================================"
echo "✅ Admin Roles Fixed & Tested!"
echo "========================================"
