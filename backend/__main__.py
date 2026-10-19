import argparse

import uvicorn

from .app import create_app

parser = argparse.ArgumentParser(description="AIRA local device service")
parser.add_argument("--port", type=int, default=8765)
arguments = parser.parse_args()
app = create_app()
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=arguments.port, access_log=False, proxy_headers=False))
app.state.shutdown_callback = lambda: setattr(server, "should_exit", True)
server.run()
