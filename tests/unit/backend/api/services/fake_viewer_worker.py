"""Stand-in viewer worker for the warm worker tests: echoes its request."""
import json
import sys
import time


def main():
    request = json.loads(sys.stdin.buffer.read() or b'{}')
    time.sleep(request.get('sleep', 0))
    print('plugin output that is not a reply')
    sys.stdout.flush()
    sys.stdout.buffer.write(b'__FAKE__:' + json.dumps({'echo': request}).encode() + b'\n')
    sys.stdout.buffer.flush()
    return request.get('exit', 0)
