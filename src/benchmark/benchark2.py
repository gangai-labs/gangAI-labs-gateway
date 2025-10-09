import asyncio
import aiohttp
import websockets
import json
import random
import string
import statistics
import time
from typing import List
from dataclasses import dataclass, field
from urllib.parse import urlencode

BASE_URL = "http://localhost:8000"
WS_BASE = "ws://localhost:8000"
PASSWORD = "password"
CONCURRENT_LIMIT = 10000
TEST_DURATION = 60
MESSAGE_INTERVAL = 1.0
MAX_RECONNECT_ATTEMPTS = 2
RECONNECT_DELAY = 1.0
API_KEY_LENGTH = 50
LATENCY_THRESHOLD = 1.0
FAILURE_RATE_THRESHOLD = 20

@dataclass
class UserCredentials:
    username: str
    token: str
    session_id: str

@dataclass
class TestStats:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    latencies: List[float] = field(default_factory=list)

    @property
    def avg_latency(self) -> float:
        return statistics.mean(self.latencies) if self.latencies else 0.0

    @property
    def success_rate(self) -> float:
        return (self.successful_requests / self.total_requests * 100) if self.total_requests else 0.0

    def add_success(self, latency: float):
        self.total_requests += 1
        self.successful_requests += 1
        if len(self.latencies) < 10_00:
            self.latencies.append(latency)

    def add_failure(self):
        self.total_requests += 1
        self.failed_requests += 1

class RampLoadTester:
    def __init__(self, num_users: int):
        self.num_users = num_users
        self.user_credentials: List[UserCredentials] = []
        self.ws_message_stats = TestStats()
        self.active_ws_connections = 0
        self._stop_event = asyncio.Event()

    async def register_user(self, session: aiohttp.ClientSession, username: str, email: str) -> bool:
        data = {"username": username, "email": email, "password": PASSWORD}
        try:
            async with session.post(f"{BASE_URL}/sessions/register", json=data, timeout=30) as resp:
                return resp.status == 200
        except:
            return False

    async def login_user(self, session: aiohttp.ClientSession, username: str) -> UserCredentials | None:
        data = {"username": username, "password": PASSWORD}
        try:
            async with session.post(f"{BASE_URL}/sessions/login", json=data, timeout=30) as resp:
                if resp.status == 200:
                    r = await resp.json()
                    return UserCredentials(username, r["access_token"], r["session_id"])
        except:
            return None

    async def send_ws_message(self, ws, username: str) -> bool:
        start = time.time()
        try:
            key = ''.join(random.choices(string.ascii_letters + string.digits, k=API_KEY_LENGTH))
            message = {"type": "update_api_key", "key": key}
            await asyncio.wait_for(ws.send(json.dumps(message)), timeout=30)
            await asyncio.wait_for(ws.recv(), timeout=30)
            latency = time.time() - start
            self.ws_message_stats.add_success(latency)
            return True
        except:
            self.ws_message_stats.add_failure()
            return False

    async def ws_session(self, creds: UserCredentials):
        params = urlencode({"session_id": creds.session_id, "token": creds.token})
        uri = f"{WS_BASE}/ws/connect?{params}"
        headers = [("Authorization", f"Bearer {creds.token}")]
        attempts = 0
        while attempts < MAX_RECONNECT_ATTEMPTS:
            try:
                async with websockets.connect(uri, additional_headers=headers, ping_interval=30, ping_timeout=30) as ws:
                    self.active_ws_connections += 1
                    end_time = time.time() + TEST_DURATION
                    while time.time() < end_time:
                        await self.send_ws_message(ws, creds.username)
                        await asyncio.sleep(MESSAGE_INTERVAL)
                    break
            except:
                attempts += 1
                await asyncio.sleep(RECONNECT_DELAY)
            finally:
                self.active_ws_connections = max(0, self.active_ws_connections - 1)

    async def live_stats_printer(self):
        while not self._stop_event.is_set():
            await asyncio.sleep(2)  # print every 2s
            avg_latency = self.ws_message_stats.avg_latency
            success_rate = self.ws_message_stats.success_rate
            print(f"Live: active users: {self.active_ws_connections} | avg WS latency: {avg_latency:.3f}s | success rate: {success_rate:.1f}%")

    async def run_batch(self):
        connector = aiohttp.TCPConnector(limit=CONCURRENT_LIMIT)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # registration
            usernames = [f"user{i}" for i in range(1, self.num_users + 1)]
            emails = [f"user{i}@example.com" for i in range(1, self.num_users + 1)]
            await asyncio.gather(*[self.register_user(session, u, e) for u, e in zip(usernames, emails)])

            # login
            results = await asyncio.gather(*[self.login_user(session, u) for u in usernames])
            self.user_credentials = [r for r in results if r]
            if not self.user_credentials:
                print("No logged users. Aborting WS phase.")
                return

            # websocket + live stats
            sem = asyncio.Semaphore(CONCURRENT_LIMIT)
            async def sem_ws(creds):
                async with sem:
                    await self.ws_session(creds)

            stats_task = asyncio.create_task(self.live_stats_printer())
            ws_tasks = [asyncio.create_task(sem_ws(creds)) for creds in self.user_credentials]
            await asyncio.gather(*ws_tasks)
            self._stop_event.set()
            await stats_task

async def main_ramp():
    num_users = 5000
    while True:
        print(f"\n=== STARTING BATCH: {num_users} users ===")
        tester = RampLoadTester(num_users)
        await tester.run_batch()
        avg_latency = tester.ws_message_stats.avg_latency
        fail_rate = 100 - tester.ws_message_stats.success_rate
        print(f"Batch {num_users} done. WS avg latency: {avg_latency:.3f}s | fail rate: {fail_rate:.1f}%")
        if avg_latency >= LATENCY_THRESHOLD or fail_rate >= FAILURE_RATE_THRESHOLD:
            print("STOPPING RAMP: latency/failure threshold reached")
            break
        num_users *= 2
        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main_ramp())

