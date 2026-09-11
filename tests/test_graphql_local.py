import asyncio
import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from octeract import graphql


@dataclass
class User:
    id: str
    name: str


class GraphQLHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        user_id = body["variables"]["user_id"]
        payload = {"data": {"user": {"id": user_id, "name": f"User {user_id}"}}}
        response_bytes = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)


QUERY = """
query GetUser($user_id: ID!) {
  user(id: $user_id) { id name }
}
"""


async def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), GraphQLHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    @graphql(f"http://127.0.0.1:{port}/graphql", QUERY, response_model=User, unwrap="user")
    async def get_user(user_id: str) -> User: ...

    user = await get_user(user_id="42")
    print("Fetched:", user)
    assert isinstance(user, User)
    assert user.id == "42" and user.name == "User 42"
    print("GraphQL + typed coercion + unwrap OK")

    server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
