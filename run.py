"""Start FastAPI and serve the Vite production build: python run.py."""
import argparse
import os
import sys
from pathlib import Path
import importlib.util
import subprocess

if importlib.util.find_spec('uvicorn') is None:
    local_python = Path(__file__).parent / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if local_python.is_file() and Path(sys.executable).resolve() != local_python.resolve():
        raise SystemExit(subprocess.call([str(local_python), str(Path(__file__).resolve()), *sys.argv[1:]]))
    raise SystemExit('Install the project dependencies: python -m pip install -r requirements.txt')
import uvicorn

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '8000')))
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--demo', action='store_true',
                        help='Use temporary in-memory storage and ignore Supabase settings.')
    args = parser.parse_args()
    if args.demo:
        from backend.server import create_app
        from backend.settings import Settings
        settings = Settings.from_env()
        settings.supabase_url = ''
        settings.supabase_key = ''
        settings.demo = True
        uvicorn.run(create_app(settings=settings), host=args.host, port=args.port)
    else:
        uvicorn.run('backend.server:app', host=args.host, port=args.port)
