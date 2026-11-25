"""Run the Python edition's browser end-to-end test (Playwright + Chromium) against the PHP edition.

    ..\\elf-archive\\.venv\\Scripts\\python.exe tests\\e2e_against_php.py [screenshot_dir]

Needs the Python edition next to this folder (../elf-archive, with its virtual environment and Playwright installed).
The test builds its throwaway database with the Python services (the two editions share the schema); every browser
step then talks to a PHP built-in server instead of Flask. Test passwords are hashed with Werkzeug's pbkdf2, which the
PHP edition verifies (its default, scrypt, cannot be checked by PHP's standard library). All data is FICTIONAL."""
import atexit
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

PHPROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(os.path.dirname(PHPROOT), "elf-archive")
PHP = os.path.join(PHPROOT, "tools", "php", "php.exe") if os.name == "nt" and os.path.exists(
    os.path.join(PHPROOT, "tools", "php", "php.exe")) else "php"
sys.path.insert(0, ARCHIVE)
os.chdir(ARCHIVE)

from werkzeug import security as wsec  # noqa: E402

import tests.helpers as helpers  # noqa: E402

helpers.generate_password_hash = lambda pw: wsec.generate_password_hash(pw, method="pbkdf2:sha256:1000")
import tests.e2e_browser as e2e  # noqa: E402


class PhpServer:
    """Stands in for werkzeug's make_server: the same settings the test gives Flask, served by PHP."""

    def __init__(self, cfg):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.server_port = s.getsockname()[1]
        s.close()
        env = dict(os.environ, ELF_ENV="testing", ELF_DATABASE_PATH=cfg["DATABASE_PATH"], ELF_SECRET_KEY=cfg["SECRET_KEY"],
                   ELF_MEDIA_ROOT=cfg["MEDIA_ROOT"], ELF_BASE_URL=f"http://127.0.0.1:{self.server_port}", ELF_AUTO_MIGRATE="0")
        self.log_path = os.path.join(os.path.dirname(cfg["DATABASE_PATH"]), "php-server.log")
        log = open(self.log_path, "w")
        self.proc = subprocess.Popen([PHP, "-S", f"127.0.0.1:{self.server_port}", "-t", "public", "public/index.php"],
                                     cwd=PHPROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        atexit.register(self.proc.kill)                  # also when the test fails part-way
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.server_port}/robots.txt", timeout=2)
                break
            except OSError:
                time.sleep(0.1)
        self.done = threading.Event()
        print("PHP server on port", self.server_port, "- log:", self.log_path)

    def serve_forever(self):
        self.done.wait()

    def shutdown(self):
        self.proc.terminate()
        self.done.set()


e2e.create_app = lambda cfg: cfg
e2e.make_server = lambda host, port, app, threaded=True: PhpServer(app)

if __name__ == "__main__":
    e2e.SHOTS = sys.argv[1] if len(sys.argv) > 1 else None
    e2e.main()
