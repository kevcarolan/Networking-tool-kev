"""Run the web app:  python -m app   (listens on NETOPS_HOST:NETOPS_PORT, by default
127.0.0.1:8710). The installed service is started by systemd instead (deploy/netops.service)."""

import uvicorn

from app.core.config import get_settings


def main() -> None:
    s = get_settings()
    uvicorn.run("app.main:create_app", factory=True, host=s.host, port=s.port,
                server_header=False)


if __name__ == "__main__":
    main()
