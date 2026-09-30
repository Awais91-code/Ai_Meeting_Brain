"""HTTP bootstrap: allowlist of public instructions/certificate only, no app proxy."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

FOLDER = Path(__file__).resolve().parent / 'data/network'
PUBLIC_FILES = {'/':('index.html','text/html; charset=utf-8'),
                '/meeting-brain-wifi.crt':('meeting-brain-wifi.crt','application/x-x509-ca-cert')}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        entry = PUBLIC_FILES.get(urlsplit(self.path).path)
        if not entry:
            self.send_error(404);return
        data = (FOLDER/'public'/entry[0]).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type',entry[1])
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        if entry[0].endswith('.crt'):
            self.send_header('Content-Disposition','attachment; filename="meeting-brain-wifi.crt"')
        self.end_headers();self.wfile.write(data)


if __name__=='__main__':
    config=json.loads((FOLDER/'config.json').read_text(encoding='utf-8'))
    ThreadingHTTPServer((config['address'],8101),Handler).serve_forever()
