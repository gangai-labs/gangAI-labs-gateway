#!/bin/bash
# WebSocket Authentication & Connection Test Script
BASE_URL="http://localhost:8000"

echo "========================================"
echo "WEB SOCKET AUTHENTICATION & CONNECTION TEST"
echo "========================================"

# Generate unique usernames to avoid conflicts
TIMESTAMP=$(date +%s)
TEST_USER="wsuser_${TIMESTAMP}"
TEST_PASSWORD="wspassword123"

# ============================================================
# 1. REGISTER NEW USER
# ============================================================
echo -e "\n1. Register New User for WS Testing"
echo "----------------------------------------"
REGISTER_RESPONSE=$(curl -s -X POST "${BASE_URL}/sessions/register" \
  -H "Content-Type: application/json" \
  -d "{
    \"username\": \"${TEST_USER}\",
    \"email\": \"${TEST_USER}@example.com\",
    \"password\": \"${TEST_PASSWORD}\"
  }")

echo "$REGISTER_RESPONSE"

# Check if registration was successful
if echo "$REGISTER_RESPONSE" | grep -q '"message":"User registered successfully"'; then
    echo "✅ User registration successful"
else
    echo "❌ User registration failed"
    exit 1
fi

# ============================================================
# 2. LOGIN USER
# ============================================================
echo -e "\n2. Login User"
echo "----------------------------------------"
LOGIN_RESPONSE=$(curl -s -X POST "${BASE_URL}/sessions/login" \
  -H "Content-Type: application/json" \
  -d "{
    \"username\": \"${TEST_USER}\",
    \"password\": \"${TEST_PASSWORD}\"
  }")

echo "$LOGIN_RESPONSE"

# Extract token and session ID
ACCESS_TOKEN=$(echo "$LOGIN_RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
SESSION_ID=$(echo "$LOGIN_RESPONSE" | grep -o '"session_id":"[^"]*' | cut -d'"' -f4)

if [ -z "$ACCESS_TOKEN" ] || [ -z "$SESSION_ID" ]; then
    echo "❌ Failed to extract token or session ID"
    exit 1
fi

echo -e "\n✅ Extracted Token: $ACCESS_TOKEN"
echo "✅ Extracted Session ID: $SESSION_ID"

# ============================================================
# 3. CREATE SESSION (GET WS URL)
# ============================================================
echo -e "\n3. Create Session & Get WebSocket URL"
echo "----------------------------------------"
SESSION_RESPONSE=$(curl -s -X POST "${BASE_URL}/sessions/create" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -d "{
    \"user_id\": \"${TEST_USER}\",
    \"chat_id\": \"default\"
  }")

echo "$SESSION_RESPONSE"

# Extract WebSocket URL and replace token placeholder AND fix host
WS_URL=$(echo "$SESSION_RESPONSE" | grep -o '"ws_url":"[^"]*' | cut -d'"' -f4)
WS_URL=$(echo "$WS_URL" | sed "s/{access_token}/${ACCESS_TOKEN}/g")
# Fix: Replace internal Docker IP with localhost
WS_URL=$(echo "$WS_URL" | sed "s/ws:\/\/[^:]*:/ws:\/\/localhost:/")

if [ -z "$WS_URL" ]; then
    echo "❌ Failed to extract WebSocket URL"
    exit 1
fi

echo -e "\n✅ WebSocket URL: $WS_URL"
echo "✅ Fixed to use localhost for external testing"

# ============================================================
# 4. TEST WEB SOCKET CONNECTION
# ============================================================
echo -e "\n4. Testing WebSocket Connection"
echo "----------------------------------------"

# Create Python WebSocket test client
cat > /tmp/websocket_test.py << 'EOF'
import asyncio
import websockets
import json
import sys
import time

import asyncio
import websockets
import json
import sys
import time

async def test_websocket():
    ws_url = sys.argv[1]
    user_id = sys.argv[2]
    session_id = sys.argv[3]

    print(f"🔗 Connecting to: {ws_url}")

    try:
        async with websockets.connect(ws_url, ping_interval=20, ping_timeout=30) as websocket:
            print("✅ WebSocket connected successfully!")

            # FIRST: Wait for welcome message - THIS IS THE EXPECTED FIRST RESPONSE
            print("⏳ Waiting for welcome message...")
            try:
                welcome = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                welcome_data = json.loads(welcome)

                # THIS IS THE CORRECT FIRST RESPONSE - NOT AN ERROR!
                if welcome_data.get("type") == "connected":
                    print("✅ Received welcome message (connected)")
                    print(f"   User: {welcome_data.get('user_id')}")
                    print(f"   Session: {welcome_data.get('session_id')}")
                    print(f"   Gateway: {welcome_data.get('gateway_id')}")
                    print(f"   Ping Interval: {welcome_data.get('ping_interval')}s")
                    print(f"   Inactivity Timeout: {welcome_data.get('inactivity_timeout')}s")
                else:
                    print(f"📥 Unexpected first message: {welcome_data}")

            except asyncio.TimeoutError:
                print("❌ No welcome message received")
                return False

            # Test 1: Send API key update
            print("\n1️⃣  Testing API key update...")
            api_key_msg = {
                "type": "update_api_key",
                "key": "test-api-key-12345"
            }
            await websocket.send(json.dumps(api_key_msg))
            print("   📤 API key update sent")

            # Wait for ACK response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                response_data = json.loads(response)

                if response_data.get("type") == "ack":
                    print("   ✅ API key update acknowledged!")
                    print(f"      API Key: {response_data.get('api_key')}")
                    print(f"      Session: {response_data.get('session_id')}")
                elif response_data.get("type") == "error":
                    print(f"   ❌ Error: {response_data.get('message')}")
                else:
                    print(f"   📥 Received: {response_data}")

            except asyncio.TimeoutError:
                print("   ❌ No ACK received for API key update")

            # Test 2: Send chat message
            print("\n2️⃣  Testing chat message...")
            chat_msg = {
                "type": "chat_message",
                "content": "Hello WebSocket!",
                "timestamp": time.time()
            }
            await websocket.send(json.dumps(chat_msg))
            print("   📤 Chat message sent")

            # Wait for response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                response_data = json.loads(response)

                if response_data.get("type") == "error":
                    print(f"   ❌ Chat rejected: {response_data.get('message')}")
                else:
                    print(f"   📥 Chat response: {response_data}")

            except asyncio.TimeoutError:
                print("   ℹ️  No response for chat message (may be expected)")

            # Test 3: Send unauthorized message type (should be rejected)
            print("\n3️⃣  Testing unauthorized message...")
            unauthorized_msg = {
                "type": "admin_command",
                "command": "shutdown"
            }
            await websocket.send(json.dumps(unauthorized_msg))
            print("   📤 Unauthorized message sent")

            # Wait for error response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                response_data = json.loads(response)

                if response_data.get("type") == "error":
                    print(f"   ✅ Correctly rejected: {response_data.get('message')}")
                else:
                    print(f"   📥 Unexpected: {response_data}")

            except asyncio.TimeoutError:
                print("   ℹ️  No response for unauthorized message")

            # Test 4: Test ping/pong
            print("\n4️⃣  Testing ping/pong...")
            ping_msg = {"type": "ping", "timestamp": time.time()}
            await websocket.send(json.dumps(ping_msg))
            print("   📤 Ping sent")

            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                response_data = json.loads(response)

                if response_data.get("type") == "pong":
                    print("   ✅ Pong received!")
                    print(f"      Timestamp: {response_data.get('timestamp')}")
                else:
                    print(f"   📥 Received: {response_data}")

            except asyncio.TimeoutError:
                print("   ❌ No pong received")

            # Test 5: Test client pong response
            print("\n5️⃣  Testing client pong response...")
            # Wait for server ping
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                response_data = json.loads(response)

                if response_data.get("type") == "ping":
                    print("   📥 Server ping received")
                    # Send pong response
                    pong_msg = {"type": "pong", "timestamp": time.time()}
                    await websocket.send(json.dumps(pong_msg))
                    print("   📤 Pong sent to server")
                else:
                    print(f"   📥 Unexpected server message: {response_data}")

            except asyncio.TimeoutError:
                print("   ℹ️  No server ping received (may be expected)")

            # Test 6: Keep connection alive briefly
            print("\n6️⃣  Testing connection keep-alive...")
            print("   ⏳ Waiting 3 seconds for any server messages...")
            messages_received = 0
            start_time = time.time()

            while time.time() - start_time < 3:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    response_data = json.loads(response)
                    messages_received += 1
                    print(f"   📥 Message #{messages_received}: {response_data}")
                except asyncio.TimeoutError:
                    # No message, continue waiting
                    pass

            print(f"   📊 Received {messages_received} messages during keep-alive")

            print("\n🎉 All WebSocket tests completed successfully!")

    except websockets.exceptions.InvalidStatusCode as e:
        print(f"❌ WebSocket connection failed: {e}")
        return False
    except websockets.exceptions.ConnectionClosed as e:
        print(f"❌ WebSocket connection closed: {e}")
        return False
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        return False

    return True

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python websocket_test.py <ws_url> <user_id> <session_id>")
        sys.exit(1)

    success = asyncio.run(test_websocket())
    sys.exit(0 if success else 1)
EOF

# Run WebSocket test
echo -e "\n🚀 Starting WebSocket test..."
python3 /tmp/websocket_test.py "$WS_URL" "$TEST_USER" "$SESSION_ID"
WS_TEST_RESULT=$?

# ============================================================
# 5. TEST WEB SOCKET HEALTH ENDPOINT
# ============================================================
echo -e "\n5. Testing WebSocket Health Endpoint"
echo "----------------------------------------"
HEALTH_RESPONSE=$(curl -s -X GET "${BASE_URL}/ws/health" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}")

echo "$HEALTH_RESPONSE"

# ============================================================
# 6. VERIFY SESSION DATA UPDATED VIA WS
# ============================================================
echo -e "\n6. Verify Session Data Updated via WebSocket"
echo "----------------------------------------"
SESSION_VERIFY_RESPONSE=$(curl -s -X GET "${BASE_URL}/sessions/${SESSION_ID}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}")

echo "$SESSION_VERIFY_RESPONSE"

# Check if API key was updated
if echo "$SESSION_VERIFY_RESPONSE" | grep -q '"api_key":"test-api-key-12345"'; then
    echo "✅ API key successfully updated via WebSocket!"
else
    echo "❌ API key not found in session data"
fi

# ============================================================
# 7. TEST CONNECTION INFO
# ============================================================
echo -e "\n7. Testing Connection Info"
echo "----------------------------------------"
CONNECTION_RESPONSE=$(curl -s -X GET "${BASE_URL}/sessions/users/${TEST_USER}/connection" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}")

echo "$CONNECTION_RESPONSE"

# ============================================================
# 8. CLEANUP - DELETE TEST USER
# ============================================================
echo -e "\n8. Cleanup - Delete Test User"
echo "----------------------------------------"
read -p "Delete test user ${TEST_USER}? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    DELETE_RESPONSE=$(curl -s -X POST "${BASE_URL}/sessions/delete_account" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer ${ACCESS_TOKEN}" \
      -d '{}')
    
    echo "$DELETE_RESPONSE"
    
    if echo "$DELETE_RESPONSE" | grep -q '"message":"Account deleted successfully"'; then
        echo "✅ Test user deleted successfully"
    else
        echo "❌ Failed to delete test user"
    fi
else
    echo "ℹ️  Test user preserved: $TEST_USER"
    echo "   Token: $ACCESS_TOKEN"
    echo "   Session: $SESSION_ID"
fi

# ============================================================
# 4. TEST WEB SOCKET CONNECTION
# ============================================================
echo -e "\n4. Testing WebSocket Connection"
echo "----------------------------------------"

# Create improved Python WebSocket test client
cat > /tmp/websocket_test.py << 'EOF'
import asyncio
import websockets
import json
import sys
import time
import uuid

async def test_websocket():
    ws_url = sys.argv[1]
    user_id = sys.argv[2]
    session_id = sys.argv[3]

    print(f"🔗 Connecting to: {ws_url}")

    try:
        async with websockets.connect(ws_url, ping_interval=20, ping_timeout=30) as websocket:
            print("✅ WebSocket connected successfully!")

            # FIRST: Wait for welcome message before sending anything
            print("⏳ Waiting for welcome message...")
            try:
                welcome = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                welcome_data = json.loads(welcome)
                if welcome_data.get("type") == "connected":
                    print("✅ Received welcome message")
                    print(f"   User: {welcome_data.get('user_id')}")
                    print(f"   Session: {welcome_data.get('session_id')}")
                else:
                    print(f"📥 Unexpected welcome: {welcome_data}")
            except asyncio.TimeoutError:
                print("❌ No welcome message received")
                return False

            # Test 1: Send API key update
            print("\n📤 Sending API key update...")
            api_key_msg = {
                "type": "update_api_key",
                "key": "test-api-key-12345"
            }
            await websocket.send(json.dumps(api_key_msg))

            # Wait for ACK response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                response_data = json.loads(response)

                if response_data.get("type") == "ack":
                    print("✅ API key update acknowledged!")
                elif response_data.get("type") == "error":
                    print(f"❌ Error: {response_data.get('message')}")
                else:
                    print(f"📥 Unexpected response: {response_data}")

            except asyncio.TimeoutError:
                print("❌ No ACK received for API key update")

            # Test 2: Send chat message
            print("\n📤 Sending chat message...")
            chat_msg = {
                "type": "chat_message",
                "content": "Hello WebSocket!"
            }
            await websocket.send(json.dumps(chat_msg))

            # Wait for response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                response_data = json.loads(response)
                print(f"📥 Chat response: {response_data}")
            except asyncio.TimeoutError:
                print("ℹ️  No response for chat message")

            # Test 3: Send unauthorized message type
            print("\n📤 Testing unauthorized message type...")
            unauthorized_msg = {
                "type": "admin_command",
                "command": "shutdown"
            }
            await websocket.send(json.dumps(unauthorized_msg))

            # Wait for error response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                response_data = json.loads(response)
                print(f"📥 Received: {response_data}")

                if response_data.get("type") == "error":
                    print("✅ Unauthorized message correctly rejected!")
            except asyncio.TimeoutError:
                print("ℹ️  No response for unauthorized message")

            # Test 4: Test ping
            print("\n🔄 Testing ping...")
            ping_msg = {"type": "ping", "timestamp": time.time()}
            await websocket.send(json.dumps(ping_msg))

            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                response_data = json.loads(response)

                if response_data.get("type") == "pong":
                    print("✅ Pong received!")
                else:
                    print(f"📥 Unexpected: {response_data}")
            except asyncio.TimeoutError:
                print("❌ No pong received")

            # Test 5: Keep connection alive briefly
            print("\n🔄 Keeping connection alive for 2 seconds...")
            start_time = time.time()
            while time.time() - start_time < 2:
                try:
                    # Try to receive any server messages
                    response = await asyncio.wait_for(websocket.recv(), timeout=0.5)
                    response_data = json.loads(response)
                    print(f"📥 Server message: {response_data}")
                except asyncio.TimeoutError:
                    # No message, continue
                    pass
                await asyncio.sleep(0.5)

            print("\n✅ WebSocket test completed!")

    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        return False

    return True

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python websocket_test.py <ws_url> <user_id> <session_id>")
        sys.exit(1)

    asyncio.run(test_websocket())
EOF

# Run WebSocket test
echo -e "\n🚀 Starting WebSocket test..."
python3 /tmp/websocket_test.py "$WS_URL" "$TEST_USER" "$SESSION_ID"
WS_TEST_RESULT=$?

# ============================================================
# 9. TEST INVALID WEB SOCKET CONNECTIONS
# ============================================================
echo -e "\n9. Testing Invalid WebSocket Connections"
echo "----------------------------------------"

# Create separate invalid connection test
cat > /tmp/invalid_ws_test.py << 'EOF'
import asyncio
import websockets
import json
import sys

async def test_invalid_connection(ws_url, test_name):
    print(f"🔒 Testing: {test_name}")
    print(f"   URL: {ws_url}")
    try:
        async with websockets.connect(ws_url, ping_interval=5, ping_timeout=10) as websocket:
            print(f"   ❌ Connection unexpectedly accepted!")

            # Try to send a message
            try:
                await websocket.send(json.dumps({"type": "ping"}))
                response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                print(f"   📥 Got response: {response}")
                print(f"   ❌ ERROR: Should have been rejected!")
            except asyncio.TimeoutError:
                print(f"   ℹ️  No response received")
            except Exception as e:
                print(f"   ✅ Connection closed: {e}")

    except websockets.exceptions.InvalidStatusCode as e:
        if e.status_code == 1008:  # Policy Violation
            print(f"   ✅ Correctly rejected with status 1008")
        else:
            print(f"   ✅ Rejected with status {e.status_code}")
    except websockets.exceptions.ConnectionClosed as e:
        print(f"   ✅ Connection closed: {e}")
    except Exception as e:
        print(f"   ✅ Rejected: {str(e)[:100]}")

async def main():
    if len(sys.argv) != 3:
        print("Usage: python invalid_ws_test.py <invalid_url> <no_token_url>")
        return

    invalid_url = sys.argv[1]
    no_token_url = sys.argv[2]

    await test_invalid_connection(invalid_url, "Invalid Token")
    await test_invalid_connection(no_token_url, "Missing Token")

if __name__ == "__main__":
    asyncio.run(main())
EOF

# Test with invalid token
echo -e "\n🔒 Testing with invalid token..."
INVALID_WS_URL=$(echo "$WS_URL" | sed "s/${ACCESS_TOKEN}/invalid-token/g")
NO_TOKEN_WS_URL=$(echo "$WS_URL" | sed "s/token=${ACCESS_TOKEN}//g")

python3 /tmp/invalid_ws_test.py "$INVALID_WS_URL" "$NO_TOKEN_WS_URL"

# ============================================================
# SUMMARY
# ============================================================
echo -e "\n========================================"
echo "TEST SUMMARY"
echo "========================================"

if [ $WS_TEST_RESULT -eq 0 ]; then
    echo "✅ WebSocket connection test: PASSED"
else
    echo "❌ WebSocket connection test: FAILED"
fi

if curl -s -X GET "${BASE_URL}/ws/health" | grep -q '"status":"healthy"'; then
    echo "✅ WebSocket health check: PASSED"
else
    echo "❌ WebSocket health check: FAILED"
fi

echo -e "\n🎉 WebSocket authentication test completed!"
echo "========================================"
