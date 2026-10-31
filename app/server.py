from http.server import BaseHTTPRequestHandler, HTTPServer
import json


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            body = b"Hello from Testpress!"
            content_type = "text/plain"
        elif self.path == "/health":
            body = json.dumps({"status": "ok"}).encode()
            content_type = "application/json"
        else:
            body = b"Not Found"
            content_type = "text/plain"
            self.send_response(404)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body)


server = HTTPServer(("0.0.0.0", 8080), RequestHandler)
print("Server listening on port 8080", flush=True)
server.serve_forever()
