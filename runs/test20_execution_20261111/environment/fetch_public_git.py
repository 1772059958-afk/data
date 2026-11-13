"""Fetch one public baseline via verified requests HTTPS and a loopback Git bridge.

This avoids the host Git trust-store mismatch without disabling TLS or changing
global/system trust. The bridge accepts only one fixed public GitHub repo path.
No credentials are read or forwarded. Output is an audit of status/counts only.
"""
from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import requests


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--repo', required=True)
    p.add_argument('--commit', required=True)
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--audit', type=Path, required=True)
    args = p.parse_args()
    if shutil.disk_usage('C:/').free < 4 * 1024**3:
        raise SystemExit('C drive is below the 4 GiB preparation reserve')
    if args.audit.exists():
        raise SystemExit('refusing to overwrite prior audit')
    remote = 'https://github.com/' + args.repo + '.git'
    request_audit = []
    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def forward(self):
            if self.path.split('?')[0] not in ('/info/refs', '/git-upload-pack'):
                self.send_error(403)
                return
            length = int(self.headers.get('Content-Length', '0'))
            if length > 16 * 1024**2:
                self.send_error(413)
                return
            headers = {k: self.headers[k] for k in
                       ('Git-Protocol', 'Content-Type', 'Content-Encoding', 'User-Agent', 'Accept')
                       if k in self.headers}
            started = time.monotonic()
            try:
                response = requests.request(self.command, remote + self.path,
                    data=self.rfile.read(length) if length else None,
                    headers=headers, timeout=90)
                body = response.content
                request_audit.append({'method': self.command, 'path': self.path,
                    'status': response.status_code, 'received_bytes': len(body),
                    'elapsed_seconds': round(time.monotonic() - started, 3)})
                self.send_response(response.status_code)
                self.send_header('Content-Type', response.headers.get('Content-Type', 'application/octet-stream'))
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                request_audit.append({'method': self.command, 'path': self.path,
                    'error_type': type(exc).__name__, 'error': str(exc)[:500]})
                self.send_error(502)
        do_GET = forward
        do_POST = forward
    server = HTTPServer(('127.0.0.1', 0), Bridge)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    target = args.directory.resolve()
    target.mkdir(parents=True, exist_ok=True)
    commands = []
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    try:
        if not (target / '.git').exists():
            result = subprocess.run(['git', 'init', str(target)], capture_output=True, text=True, timeout=30)
            commands.append({'command': 'git init', 'exit_code': result.returncode,
                             'stdout': result.stdout, 'stderr': result.stderr})
            result.check_returncode()
        origin = f'http://127.0.0.1:{server.server_port}'
        steps = [(['git', '-C', str(target), '-c', 'credential.helper=', 'fetch', '--depth', '1', origin, args.commit], 'git fetch public baseline over verified HTTPS bridge'),
                 (['git', '-C', str(target), 'checkout', '--detach', 'FETCH_HEAD'], 'git checkout baseline'),
                 (['git', '-C', str(target), 'rev-parse', 'HEAD'], 'git rev-parse HEAD'),
                 (['git', '-C', str(target), 'status', '--porcelain'], 'git status --porcelain')]
        for command, label in steps:
            started = time.monotonic()
            result = subprocess.run(command, capture_output=True, text=True, timeout=180, env=env)
            commands.append({'command': label, 'exit_code': result.returncode,
                             'stdout': result.stdout, 'stderr': result.stderr,
                             'elapsed_seconds': round(time.monotonic()-started, 3)})
            if result.returncode:
                break
        good = (len(commands) >= 4 and commands[-1]['command'] == 'git status --porcelain'
                and commands[-1]['exit_code'] == 0 and not commands[-1]['stdout'].strip()
                and commands[-2]['stdout'].strip() == args.commit)
    finally:
        server.shutdown()
        server.server_close()
    audit = {'public_repo': remote, 'base_commit': args.commit, 'directory': str(target),
             'verified_https': True, 'tls_verify_disabled': False, 'ca_bundle': requests.certs.where(),
             'requests': request_audit, 'commands': commands, 'source_identity_verified': good,
             'C_free_bytes': shutil.disk_usage('C:/').free}
    with args.audit.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps({'repo': args.repo, 'commit': args.commit, 'source_identity_verified': good,
                      'downloaded_bytes': sum(r.get('received_bytes', 0) for r in request_audit),
                      'C_free_bytes': audit['C_free_bytes']}))
    return 0 if good else 1


if __name__ == '__main__':
    raise SystemExit(main())
