"""Run the API, single Worker and frontend together; stop children on exit."""
import os
import argparse
import signal
import subprocess
import sys
import time
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-port', type=int, default=8000)
    parser.add_argument('--web-port', type=int, default=5173)
    parser.add_argument('--temporary-data', action='store_true')
    args = parser.parse_args()
    env = os.environ.copy()
    temporary = tempfile.TemporaryDirectory(prefix='pdf2markdown-e2e-') if args.temporary_data else None
    if temporary:
        env['DATA_DIR'] = temporary.name
        env['MINERU_MODE'] = 'mock'
    env['API_PROXY_TARGET'] = f'http://127.0.0.1:{args.api_port}'
    local_node = ROOT / ".tools/node_modules/node/bin"
    if local_node.exists():
        env["PATH"] = str(local_node) + os.pathsep + env.get("PATH", "")
    processes = []

    def stop(signum=None, frame=None):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for command, directory in [
            ([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(args.api_port)], ROOT),
            ([sys.executable, "-m", "backend.app.worker"], ROOT),
            (["npm", "run", "dev", "--", "--port", str(args.web_port)], ROOT / "frontend"),
        ]:
            processes.append(subprocess.Popen(command, cwd=directory, env=env, start_new_session=True))
        print(f"\n本机预览：http://127.0.0.1:{args.web_port} · M1 Mock 模式\n", flush=True)
        while True:
            for process in processes:
                if process.poll() is not None:
                    raise RuntimeError(f"子服务意外退出，退出码 {process.returncode}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        # uv and the test runner may both forward termination; finish cleanup once.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        if temporary:
            temporary.cleanup()


if __name__ == "__main__":
    main()
