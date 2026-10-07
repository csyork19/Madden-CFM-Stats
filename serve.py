#!/usr/bin/env python3
"""Serve the league pages and rebuild the stats from the export on every load.

    python3 serve.py [export-folder] [port]

Then open http://localhost:8000/ . Each time a page loads, league-data.js is
regenerated from whatever week folders are in the export right now, so adding
stats/reg/3, 4, ... only needs a browser refresh.
"""
import http.server
import os
import sys

from build_league_data import build, find_export, to_js

HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
PORT = int(args.pop()) if args and args[-1].isdigit() else 8000
EXPORT = find_export(args[0] if args else None)
if not EXPORT:
    sys.exit(__doc__ + '\nNo export folder found (needs teams.csv and a stats/ folder).')


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/':
            self.send_response(302)
            self.send_header('Location', '/broadcast.html')
            self.end_headers()
            return
        if path == '/league-data.js':
            try:
                data = build(EXPORT)
                body = to_js(data).encode('utf-8')
                print('rebuilt from export: weeks %s' % data['weeks'])
            except Exception as e:  # show the problem in the page instead of a blank screen
                body = ('window.LEAGUE_DATA = null; console.error(%r);' % ('build failed: %s' % e)).encode('utf-8')
                print('build failed: %s' % e)
            self.send_response(200)
            self.send_header('Content-Type', 'text/javascript; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


if __name__ == '__main__':
    print('export folder: %s' % EXPORT)
    print('open http://localhost:%d/  (Ctrl+C to stop)' % PORT)
    http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
