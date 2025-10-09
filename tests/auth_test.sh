#!/bin/bash
# Authentication cURL Examples for SessionHandler API
# Base URL - adjust as needed
BASE_URL="http://localhost:8000"

echo "================================"
echo "AUTHENTICATION CURL EXAMPLES"
echo "================================"

# ============================================================
# CREATE ADMIN USER (if not exists)
# ============================================================
echo -e "\n0. Register Admin User"
echo "-------------------"
curl -X POST "${BASE_URL}/sessions/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "email": "admin@example.com", 
    "password": "admin"
  }'

# ============================================================
# 1. REGISTER NEW USER (PUBLIC - No Auth Required)
# ============================================================
echo -e "\n1. Register New User"
echo "-------------------"
curl -X POST "${BASE_URL}/sessions/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com",
    "password": "securepassword123"
  }'

# Expected Response:
# {
#   "message": "User registered successfully",
#   "username": "testuser"
# }


# ============================================================
# 2. LOGIN (PUBLIC - No Auth Required)
# ============================================================
echo -e "\n\n2. Login User"
echo "-------------------"
LOGIN_RESPONSE=$(curl -s -X POST "${BASE_URL}/sessions/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "password": "securepassword123"
  }')

echo "$LOGIN_RESPONSE"

# Extract token for subsequent requests
ACCESS_TOKEN=$(echo "$LOGIN_RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
SESSION_ID=$(echo "$LOGIN_RESPONSE" | grep -o '"session_id":"[^"]*' | cut -d'"' -f4)

echo -e "\nExtracted Token: $ACCESS_TOKEN"
echo "Extracted Session ID: $SESSION_ID"

# Expected Response:
# {
#   "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
#   "token_type": "bearer",
#   "expires_in": 1800,
#   "user": {
#     "username": "testuser",
#     "role": "user"
#   },
#   "session_id": "uuid-here"
# }


# ============================================================
# 3. CREATE SESSION (AUTHENTICATED - Requires Token)
# ============================================================
echo -e "\n\n3. Create/Get Session (Authenticated)"
echo "-------------------"
curl -X POST "${BASE_URL}/sessions/create" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -d '{
    "user_id": "testuser",
    "chat_id": "default"
  }'

# Expected Response:
# {
#   "session_id": "uuid",
#   "user_id": "testuser",
#   "chat_id": "default",
#   "data": {"conversation": [], "api_key": null},
#   "ws_url": "ws://localhost:8000/ws/connect?session_id=uuid&token={access_token}"
# }


# ============================================================
# 4. GET SESSION (OWNER OR ADMIN)
# ============================================================
echo -e "\n\n4. Get Session Details (Owner or Admin)"
echo "-------------------"
curl -X GET "${BASE_URL}/sessions/${SESSION_ID}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"

# Expected Response:
# {
#   "session_id": "uuid",
#   "user_id": "testuser",
#   "chat_id": "default",
#   "data": {...},
#   "ws_url": ""
# }


# ============================================================
# 5. UPDATE SESSION (OWNER ONLY)
# ============================================================
echo -e "\n\n5. Update Session (Owner Only)"
echo "-------------------"
curl -X POST "${BASE_URL}/sessions/update/${SESSION_ID}" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -d '{
    "chat_id": "default",
    "data": {
      "api_key": "new-api-key-123"
    }
  }'

# Expected Response:
# {
#   "session_id": "uuid",
#   "user_id": "testuser",
#   "chat_id": "default",
#   "data": {"data": null},
#   "ws_url": "ws://..."
# }


# ============================================================
# 6. LOGOUT (AUTHENTICATED)
# ============================================================
echo -e "\n\n6. Logout (Authenticated)"
echo "-------------------"
curl -X POST "${BASE_URL}/sessions/logout" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"

# Expected Response:
# {
#   "message": "Logged out successfully"
# }


# ============================================================
# 7. DELETE ACCOUNT (AUTHENTICATED)
# ============================================================
echo -e "\n\n7. Delete Account (Authenticated)"
echo "-------------------"
echo "⚠️  WARNING: This will delete the account!"
# Uncomment to actually delete:
# curl -X POST "${BASE_URL}/sessions/delete_account" \
#   -H "Authorization: Bearer ${ACCESS_TOKEN}"

# Expected Response:
# {
#   "message": "Account deleted successfully"
# }


# ============================================================
# 8. TEST UNAUTHORIZED ACCESS (Should Fail - 401)
# ============================================================
echo -e "\n\n8. Test Unauthorized Access (No Token)"
echo "-------------------"
curl -X GET "${BASE_URL}/sessions/${SESSION_ID}"

# Expected Response:
# {
#   "detail": "Not authenticated"
# }


# ============================================================
# 9. TEST INVALID TOKEN (Should Fail - 401)
# ============================================================
echo -e "\n\n9. Test Invalid Token"
echo "-------------------"
curl -X GET "${BASE_URL}/sessions/${SESSION_ID}" \
  -H "Authorization: Bearer invalid-token-here"

# Expected Response:
# {
#   "detail": "Could not validate credentials"
# }


# ============================================================
# 10. TEST SESSION ACCESS BY DIFFERENT USER (Should Fail - 403)
# ============================================================
echo -e "\n\n10. Test Accessing Another User's Session"
echo "-------------------"

# First, register and login as a second user
SECOND_USER_RESPONSE=$(curl -s -X POST "${BASE_URL}/sessions/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "otheruser",
    "password": "password123"
  }')

SECOND_TOKEN=$(echo "$SECOND_USER_RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

# Try to access first user's session with second user's token
curl -X GET "${BASE_URL}/sessions/${SESSION_ID}" \
  -H "Authorization: Bearer ${SECOND_TOKEN}"

# Expected Response:
# {
#   "detail": "Session access denied"
# }


# ============================================================
# ADMIN EXAMPLES (Requires admin role)
# ============================================================

echo -e "\n\n================================"
echo "ADMIN AUTHENTICATION EXAMPLES"
echo "================================"

# Login as admin
echo -e "\n11. Admin Login"
echo "-------------------"
ADMIN_RESPONSE=$(curl -s -X POST "${BASE_URL}/sessions/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin"
  }')

echo "$ADMIN_RESPONSE"
ADMIN_TOKEN=$(echo "$ADMIN_RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

echo -e "\nAdmin Token: $ADMIN_TOKEN"


# ============================================================
# 12. LIST ALL SESSIONS (ADMIN ONLY)
# ============================================================
echo -e "\n\n12. List All Sessions (Admin Only)"
echo "-------------------"
curl -X GET "${BASE_URL}/sessions/admin/all-sessions" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"

# Expected Response:
# {
#   "sessions": [
#     {
#       "session_id": "uuid",
#       "user_id": "testuser",
#       "chat_id": "default",
#       "last_access": 1234567890.123,
#       "created_at": 1234567890.123
#     }
#   ],
#   "count": 1
# }


# ============================================================
# 13. LIST ALL USERS (ADMIN ONLY)
# ============================================================
echo -e "\n\n13. List All Users (Admin Only)"
echo "-------------------"
curl -X GET "${BASE_URL}/sessions/admin/users" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"

# Expected Response:
# {
#   "users": [
#     {
#       "username": "testuser",
#       "email": "test@example.com",
#       "role": "user",
#       "last_login": 1234567890.123
#     }
#   ],
#   "count": 1
# }


# ============================================================
# 14. DELETE ANY SESSION (ADMIN ONLY)
# ============================================================
echo -e "\n\n14. Delete Any Session (Admin Only)"
echo "-------------------"
curl -X DELETE "${BASE_URL}/sessions/admin/sessions/${SESSION_ID}" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"

# Expected Response:
# {
#   "message": "Session uuid deleted"
# }


# ============================================================
# 15. DELETE ANY USER (ADMIN ONLY)
# ============================================================
echo -e "\n\n15. Delete Any User (Admin Only)"
echo "-------------------"
echo "⚠️  WARNING: This will delete the user!"
# Uncomment to actually delete:
# curl -X DELETE "${BASE_URL}/sessions/admin/users/testuser" \
#   -H "Authorization: Bearer ${ADMIN_TOKEN}"

# Expected Response:
# {
#   "message": "User testuser deleted successfully"
# }


# ============================================================
# 16. TEST REGULAR USER ACCESSING ADMIN ENDPOINT (Should Fail - 403)
# ============================================================
echo -e "\n\n16. Test Regular User Accessing Admin Endpoint"
echo "-------------------"
curl -X GET "${BASE_URL}/sessions/admin/all-sessions" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"

# Expected Response:
# {
#   "detail": "Access denied. Required roles: admin"
# }


# ============================================================
# 17. GET USER'S OWN SESSIONS
# ============================================================
echo -e "\n\n17. Get User's Own Sessions"
echo "-------------------"
curl -X GET "${BASE_URL}/sessions/users/testuser/sessions" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"

# Expected Response:
# {
#   "sessions": [
#     {
#       "session_id": "uuid",
#       "chat_id": "default",
#       "last_access": 1234567890.123,
#       "created_at": 1234567890.123
#     }
#   ],
#   "count": 1
# }


# ============================================================
# 18. GET USER'S CONNECTION INFO
# ============================================================
echo -e "\n\n18. Get User's Connection Info"
echo "-------------------"
curl -X GET "${BASE_URL}/sessions/users/testuser/connection" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"

# Expected Response:
# {
#   "session_id": "uuid",
#   "gateway_id": "localhost:8000",
#   "ws_connected": false,
#   "last_seen": 1234567890.123
# }


echo -e "\n\n================================"
echo "✅ Authentication Tests Complete!"
echo "================================"
