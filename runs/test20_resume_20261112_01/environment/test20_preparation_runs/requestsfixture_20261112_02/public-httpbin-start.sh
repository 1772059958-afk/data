export HTTPBIN_URL=http://127.0.0.1:8765/
if ! /opt/public-httpbin/bin/python -c "import socket;s=socket.create_connection(('127.0.0.1',8765),0.2);s.close()" >/dev/null 2>&1; then
 (
  flock -w 10 9 || exit 1
  if ! /opt/public-httpbin/bin/python -c "import socket;s=socket.create_connection(('127.0.0.1',8765),0.2);s.close()" >/dev/null 2>&1; then
   nohup /opt/public-httpbin/bin/gunicorn --bind 127.0.0.1:8765 --workers 1 --threads 2 httpbin:app </dev/null >/tmp/public-httpbin.log 2>&1 9>&- &
  fi
  /opt/public-httpbin/bin/python -c "import socket,time;exec('for i in range(40):\n try:\n  s=socket.create_connection((\"127.0.0.1\",8765),0.2);s.close();break\n except OSError:time.sleep(.1)\nelse:raise RuntimeError(\"public HTTPbin startup failed\")')"
 ) 9>/tmp/public-httpbin.lock || return 1
fi
