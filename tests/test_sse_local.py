import asyncio
import contextlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from octeract import sse


class SSEHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silence default request logging

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for i in range(3):
            chunk = f"data: {json.dumps({'tick': i})}\n\n".encode()
            self.wfile.write(chunk)
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")


async def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), SSEHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    @sse(f"http://127.0.0.1:{port}/events")
    async def watch(): ...

    events = []
    async for event in watch.stream():
        events.append(event)

    print("Received:", events)
    assert events == [{"tick": 0}, {"tick": 1}, {"tick": 2}]
    print("SSE streaming OK")

    server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
