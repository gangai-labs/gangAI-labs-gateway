import asyncio
import aiohttp
import websockets
import json
import random
import string
import statistics
import time
from typing import List, Optional
from dataclasses import dataclass, field
from urllib.parse import urlencode

# Configuration
BASE_URL = "http://localhost:8000"
WS_BASE = "ws://localhost:8000"
NUM_USERS = 100
PASSWORD = "password"
TEST_DURATION = 60
MESSAGE_INTERVAL = 0
NUM_MESSAGES_PER_USER = 1000
NUM_TEST_USERS = 100  # Number of users for comparison tests


@dataclass
class UserCredentials:
    username: str
    token: str
    session_id: str


@dataclass
class PhaseStats:
    name: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    latencies: List[float] = field(default_factory=list)
    start_time: float = 0
    end_time: float = 0

    @property
    def total_duration(self) -> float:
        return self.end_time - self.start_time if self.end_time > self.start_time else 0

    @property
    def avg_latency(self) -> float:
        return statistics.mean(self.latencies) if self.latencies else 0.0

    @property
    def success_rate(self) -> float:
        return (self.successful_requests / self.total_requests * 100) if self.total_requests > 0 else 0.0

    @property
    def throughput(self) -> float:
        return self.successful_requests / self.total_duration if self.total_duration > 0 else 0.0

    def add_success(self, latency: float):
        self.total_requests += 1
        self.successful_requests += 1
        if len(self.latencies) < 100_000:
            self.latencies.append(latency)

    def add_failure(self):
        self.total_requests += 1
        self.failed_requests += 1


class CompleteBenchmark:
    def __init__(self):
        self.reg_stats = PhaseStats("Registration")
        self.login_stats = PhaseStats("Login")
        self.ws_connect_stats = PhaseStats("WebSocket Connect")
        self.ws_message_stats = PhaseStats("WebSocket Messages")
        self.http_update_stats = PhaseStats("HTTP Updates")
        self.user_credentials: List[UserCredentials] = []
        self._stop_event = asyncio.Event()

    async def register_user(self, session: aiohttp.ClientSession, username: str) -> bool:
        data = {"username": username, "email": f"{username}@test.com", "password": PASSWORD}
        start = time.time()
        try:
            async with session.post(f"{BASE_URL}/sessions/register", json=data, timeout=30) as resp:
                latency = time.time() - start
                if resp.status == 200:
                    self.reg_stats.add_success(latency)
                    return True
                else:
                    self.reg_stats.add_failure()
                    return False
        except Exception as e:
            self.reg_stats.add_failure()
            return False

    async def login_user(self, session: aiohttp.ClientSession, username: str) -> Optional[UserCredentials]:
        data = {"username": username, "password": PASSWORD}
        start = time.time()
        try:
            async with session.post(f"{BASE_URL}/sessions/login", json=data, timeout=30) as resp:
                latency = time.time() - start
                if resp.status == 200:
                    result = await resp.json()
                    token = result.get("access_token")
                    session_id = result.get("session_id")
                    if token and session_id:
                        self.login_stats.add_success(latency)
                        return UserCredentials(username, token, session_id)
                self.login_stats.add_failure()
                return None
        except Exception as e:
            self.login_stats.add_failure()
            return None

    async def http_update_session(self, session: aiohttp.ClientSession, creds: UserCredentials,
                                  update_data: dict) -> bool:
        """Send update via HTTP POST"""
        headers = {"Authorization": f"Bearer {creds.token}"}
        data = {"data": update_data, "chat_id": "default"}
        start = time.time()
        try:
            async with session.post(f"{BASE_URL}/sessions/update/{creds.session_id}",
                                    headers=headers, json=data, timeout=30) as resp:
                latency = time.time() - start
                if resp.status == 200:
                    self.http_update_stats.add_success(latency)
                    return True
                else:
                    self.http_update_stats.add_failure()
                    return False
        except Exception as e:
            self.http_update_stats.add_failure()
            return False

    async def websocket_message(self, websocket, message: dict) -> bool:
        start = time.time()
        try:
            await asyncio.wait_for(websocket.send(json.dumps(message)), timeout=30)
            resp = await asyncio.wait_for(websocket.recv(), timeout=30)
            latency = time.time() - start
            self.ws_message_stats.add_success(latency)
            return True
        except Exception as e:
            self.ws_message_stats.add_failure()
            return False

    async def websocket_session(self, creds: UserCredentials, num_messages: int):
        params = urlencode({"session_id": creds.session_id, "token": creds.token})
        uri = f"{WS_BASE}/ws/connect?{params}"

        connect_start = time.time()
        try:
            async with websockets.connect(uri, ping_interval=60, open_timeout=30) as ws:
                connect_latency = time.time() - connect_start
                self.ws_connect_stats.add_success(connect_latency)

                # Send specified number of messages
                for i in range(num_messages):
                    if self._stop_event.is_set():
                        break
                    message = {"type": "update_api_key",
                               "key": ''.join(random.choices(string.ascii_letters, k=50))}
                    await self.websocket_message(ws, message)
                    await asyncio.sleep(MESSAGE_INTERVAL)

        except Exception as e:
            self.ws_connect_stats.add_failure()

    async def http_update_session_batch(self, session: aiohttp.ClientSession,
                                        creds: UserCredentials, num_updates: int):
        """Send multiple updates via HTTP"""
        for i in range(num_updates):
            if self._stop_event.is_set():
                break
            update_data = {"api_key": ''.join(random.choices(string.ascii_letters, k=50))}
            await self.http_update_session(session, creds, update_data)
            await asyncio.sleep(MESSAGE_INTERVAL)

    async def run_registration_phase(self, session: aiohttp.ClientSession):
        print(f"📝 PHASE 1: Registering {NUM_USERS} users...")
        self.reg_stats.start_time = time.time()

        usernames = [f"testuser{i}" for i in range(1, NUM_USERS + 1)]
        tasks = [self.register_user(session, u) for u in usernames]
        await asyncio.gather(*tasks)

        self.reg_stats.end_time = time.time()
        print(f"✓ Registration: {self.reg_stats.successful_requests}/{NUM_USERS} successful "
              f"in {self.reg_stats.total_duration:.2f}s "
              f"(avg {self.reg_stats.avg_latency * 1000:.1f}ms per user)\n")

    async def run_login_phase(self, session: aiohttp.ClientSession):
        print(f"🔐 PHASE 2: Logging in {NUM_USERS} users...")
        self.login_stats.start_time = time.time()

        usernames = [f"testuser{i}" for i in range(1, NUM_USERS + 1)]
        tasks = [self.login_user(session, u) for u in usernames]
        results = await asyncio.gather(*tasks)
        self.user_credentials = [r for r in results if r is not None]

        self.login_stats.end_time = time.time()
        print(f"✓ Login: {len(self.user_credentials)}/{NUM_USERS} successful "
              f"in {self.login_stats.total_duration:.2f}s "
              f"(avg {self.login_stats.avg_latency * 1000:.1f}ms per user)\n")

    async def run_http_updates_phase(self, session: aiohttp.ClientSession):
        """Test HTTP update performance"""
        if not self.user_credentials:
            print("❌ No users logged in, skipping HTTP updates phase")
            return

        print(f"🌐 PHASE 3: HTTP Updates ({NUM_MESSAGES_PER_USER} updates per user)...")
        self.http_update_stats.start_time = time.time()

        # Use consistent number of users for fair comparison
        test_users = self.user_credentials[:NUM_TEST_USERS]

        tasks = [self.http_update_session_batch(session, creds, NUM_MESSAGES_PER_USER)
                 for creds in test_users]
        await asyncio.gather(*tasks)

        self.http_update_stats.end_time = time.time()
        total_expected = len(test_users) * NUM_MESSAGES_PER_USER
        print(f"✓ HTTP Updates: {self.http_update_stats.successful_requests}/{total_expected} successful "
              f"in {self.http_update_stats.total_duration:.2f}s "
              f"(avg {self.http_update_stats.avg_latency * 1000:.1f}ms per update)\n")

    async def run_websocket_phase(self):
        """Test WebSocket performance"""
        if not self.user_credentials:
            print("❌ No users logged in, skipping WebSocket phase")
            return

        print(f"⚡ PHASE 4: WebSocket Messages ({NUM_MESSAGES_PER_USER} messages per user)...")
        self.ws_connect_stats.start_time = time.time()
        self.ws_message_stats.start_time = time.time()

        # Use consistent number of users for fair comparison
        test_users = self.user_credentials[:NUM_TEST_USERS]
        tasks = [self.websocket_session(creds, NUM_MESSAGES_PER_USER) for creds in test_users]
        await asyncio.gather(*tasks)

        self.ws_connect_stats.end_time = time.time()
        self.ws_message_stats.end_time = time.time()

        total_expected_messages = len(test_users) * NUM_MESSAGES_PER_USER
        print(f"✓ WebSocket: {self.ws_message_stats.successful_requests}/{total_expected_messages} messages "
              f"in {self.ws_message_stats.total_duration:.2f}s "
              f"(avg {self.ws_message_stats.avg_latency * 1000:.1f}ms per message)\n")

    def print_comparison(self):
        print("\n" + "=" * 70)
        print(f"COMPLETE BENCHMARK RESULTS with NUM_USERS:{NUM_USERS}")
        print("=" * 70)

        # Registration stats
        print(f"\n📊 REGISTRATION ({NUM_USERS} users):")
        print(f"   Total time: {self.reg_stats.total_duration:.2f}s")
        print(f"   Success rate: {self.reg_stats.success_rate:.1f}%")
        print(f"   Avg latency: {self.reg_stats.avg_latency * 1000:.1f}ms")
        print(f"   Throughput: {self.reg_stats.throughput:.1f} users/sec")

        # Login stats
        print(f"\n🔐 LOGIN ({NUM_USERS} users):")
        print(f"   Total time: {self.login_stats.total_duration:.2f}s")
        print(f"   Success rate: {self.login_stats.success_rate:.1f}%")
        print(f"   Avg latency: {self.login_stats.avg_latency * 1000:.1f}ms")
        print(f"   Throughput: {self.login_stats.throughput:.1f} users/sec")

        # HTTP vs WebSocket comparison
        total_updates_http = self.http_update_stats.successful_requests
        total_updates_ws = self.ws_message_stats.successful_requests

        print(
            f"\n🌐 HTTP UPDATES ({NUM_TEST_USERS} users × {NUM_MESSAGES_PER_USER} updates = {NUM_TEST_USERS * NUM_MESSAGES_PER_USER} total):")
        print(f"   Total time: {self.http_update_stats.total_duration:.2f}s")
        print(f"   Success rate: {self.http_update_stats.success_rate:.1f}%")
        print(f"   Avg latency: {self.http_update_stats.avg_latency * 1000:.1f}ms")
        print(f"   Throughput: {self.http_update_stats.throughput:.1f} req/sec")

        print(
            f"\n⚡ WEBSOCKET MESSAGES ({NUM_TEST_USERS} users × {NUM_MESSAGES_PER_USER} messages = {NUM_TEST_USERS * NUM_MESSAGES_PER_USER} total):")
        print(f"   Connection time: {self.ws_connect_stats.total_duration:.2f}s")
        print(f"   Messaging time: {self.ws_message_stats.total_duration:.2f}s")
        print(f"   Success rate: {self.ws_message_stats.success_rate:.1f}%")
        print(f"   Avg latency: {self.ws_message_stats.avg_latency * 1000:.1f}ms")
        print(f"   Messaging throughput: {self.ws_message_stats.throughput:.1f} msg/sec")

        print("\n" + "=" * 70)
        print("📈 DIRECT COMPARISON (HTTP vs WebSocket - MESSAGING ONLY):")
        print("=" * 70)

        if self.http_update_stats.successful_requests > 0 and self.ws_message_stats.successful_requests > 0:
            # Compare only the messaging time, not connection setup
            http_messaging_time = self.http_update_stats.total_duration
            ws_messaging_time = self.ws_message_stats.total_duration

            print(f"\nHTTP Messaging Time: {http_messaging_time:.2f}s")
            print(f"WebSocket Messaging Time: {ws_messaging_time:.2f}s")
            print(f"WebSocket Connection Time: {self.ws_connect_stats.total_duration:.2f}s (one-time cost)")

            if ws_messaging_time > 0 and http_messaging_time > 0:
                # Compare messaging performance only
                if ws_messaging_time < http_messaging_time:
                    speedup = http_messaging_time / ws_messaging_time
                    print(f"\n🚀 WebSocket MESSAGING is {speedup:.2f}x FASTER than HTTP")
                else:
                    slowdown = http_messaging_time / ws_messaging_time
                    print(f"\n⚠️  HTTP MESSAGING is {slowdown:.2f}x FASTER than WebSocket")

                http_throughput = self.http_update_stats.throughput
                ws_throughput = self.ws_message_stats.throughput

                print(f"\nHTTP Messaging Throughput: {http_throughput:.1f} req/sec")
                print(f"WebSocket Messaging Throughput: {ws_throughput:.1f} msg/sec")

                if ws_throughput > http_throughput:
                    throughput_ratio = ws_throughput / http_throughput
                    print(f"WebSocket has {throughput_ratio:.2f}x higher messaging throughput than HTTP")
                else:
                    throughput_ratio = http_throughput / ws_throughput
                    print(f"HTTP has {throughput_ratio:.2f}x higher messaging throughput than WebSocket")

                # Latency comparison
                print(f"\n📊 LATENCY COMPARISON:")
                print(f"   HTTP avg latency: {self.http_update_stats.avg_latency * 1000:.1f}ms")
                print(f"   WebSocket avg latency: {self.ws_message_stats.avg_latency * 1000:.1f}ms")

                if self.ws_message_stats.avg_latency < self.http_update_stats.avg_latency:
                    latency_improvement = (
                                                      self.http_update_stats.avg_latency - self.ws_message_stats.avg_latency) / self.http_update_stats.avg_latency * 100
                    print(f"   WebSocket has {latency_improvement:.1f}% lower latency than HTTP")
                else:
                    latency_improvement = (
                                                      self.ws_message_stats.avg_latency - self.http_update_stats.avg_latency) / self.ws_message_stats.avg_latency * 100
                    print(f"   HTTP has {latency_improvement:.1f}% lower latency than WebSocket")

            else:
                print("\n❌ Cannot calculate comparison: zero duration detected")
        else:
            print("\n❌ No successful requests for comparison")


async def main():
    print("=" * 70)
    print("COMPLETE HTTP vs WEBSOCKET BENCHMARK")
    print("=" * 70)
    print(f"Configuration: {NUM_USERS} users, {NUM_TEST_USERS} test users, {NUM_MESSAGES_PER_USER} messages each")
    print(f"Total comparisons: {NUM_TEST_USERS * NUM_MESSAGES_PER_USER} updates/messages\n")

    benchmark = CompleteBenchmark()

    connector = aiohttp.TCPConnector(limit=200)
    timeout = aiohttp.ClientTimeout(total=60)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # Run all phases
        await benchmark.run_registration_phase(session)
        await benchmark.run_login_phase(session)
        await benchmark.run_http_updates_phase(session)
        await benchmark.run_websocket_phase()

    benchmark.print_comparison()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBenchmark interrupted")
