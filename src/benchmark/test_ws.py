# complete_websocket_test.py
import asyncio
import aiohttp
import websockets
import json

class WebSocketTester:
    def __init__(self):
        self.base_url = "http://localhost:8000"
        self.ws_url = "ws://localhost:8000/ws/connect"
        
    async def register_and_login(self):
        async with aiohttp.ClientSession() as session:
            # Register
            register_data = {
                "username": "websocket_test_user",
                "email": "ws_test@test.com",
                "password": "testpassword123"
            }
            
            try:
                async with session.post(f"{self.base_url}/sessions/register", json=register_data) as resp:
                    if resp.status in [200, 400]:  # 400 might mean user exists
                        print("✓ Registration attempt completed")
            except Exception as e:
                print(f"Registration error: {e}")
            
            # Login
            login_data = {
                "username": "websocket_test_user",
                "password": "testpassword123"
            }
            
            async with session.post(f"{self.base_url}/sessions/login", json=login_data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    token = result.get("access_token")
                    session_id = result.get("session_id")
                    print("✓ Login successful")
                    return token, session_id
                else:
                    print(f"✗ Login failed: {resp.status}")
                    return None, None
    
    async def test_websocket_connection(self, token, session_id):
        if not token or not session_id:
            print("✗ Missing token or session_id")
            return False
            
        uri = f"{self.ws_url}?session_id={session_id}&token={token}"
        
        try:
            print(f"Connecting to WebSocket...")
            async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as websocket:
                print("✓ WebSocket connection established!")
                
                # Test message
                test_msg = {
                    "type": "update_api_key",
                    "key": "test_key_" + str(hash(str(asyncio.get_event_loop().time())))
                }
                
                await websocket.send(json.dumps(test_msg))
                print("✓ Test message sent")
                
                # Wait for ACK
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    response_data = json.loads(response)
                    print(f"✓ Received response: {response_data}")
                    
                    if response_data.get("type") == "ack":
                        print("✓ WebSocket communication successful!")
                        return True
                    else:

                        print(f"✗ Unexpected response type: {response_data}")
                        return False
                        
                except asyncio.TimeoutError:
                    print("✗ No response received within timeout")
                    return False
                    
        except websockets.exceptions.InvalidStatusCode as e:
            print(f"✗ WebSocket connection rejected: {e.status_code}")
            return False
        except Exception as e:
            print(f"✗ WebSocket connection failed: {type(e).__name__}: {e}")
            return False
    
    async def run_full_test(self):
        print("🔧 Starting WebSocket authentication test...")
        print("=" * 50)
        
        # Step 1: Get authentication
        print("1. Authenticating...")
        token, session_id = await self.register_and_login()
        
        if not token:
            print("✗ Authentication failed - cannot proceed")
            return False
            
        print(f"   Token: {token[:20]}...")
        print(f"   Session ID: {session_id}")
        
        # Step 2: Test WebSocket
        print("\n2. Testing WebSocket connection...")
        success = await self.test_websocket_connection(token, session_id)
        
        # Step 3: Results
        print("\n" + "=" * 50)
        if success:
            print("🎉 SUCCESS: WebSocket connection working properly!")
        else:
            print("❌ FAILED: WebSocket connection issues detected")
            
        return success

# Run the test
async def main():
    tester = WebSocketTester()
    await tester.run_full_test()

if __name__ == "__main__":
    asyncio.run(main())
