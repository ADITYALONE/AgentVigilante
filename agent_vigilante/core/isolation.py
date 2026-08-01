"""Docker-backed ephemeral sandbox for untrusted agent commands."""

from __future__ import annotations

import logging
import platform
import shlex
import socket
from pathlib import Path
from typing import TypedDict

import docker
from docker.errors import APIError, ContainerError, ImageNotFound, NotFound
from docker.models.containers import Container
from docker.types import Ulimit

from agent_vigilante.core.egress_proxy import DEFAULT_WHITELIST

logger = logging.getLogger(__name__)

DEFAULT_BASE_IMAGE = "agentvigilante-sandbox:local"


class CommandResult(TypedDict):
    """Structured result of a sandboxed command execution."""

    stdout: str
    stderr: str
    exit_code: int


class AgentSandbox:
    """Ephemeral Docker sandbox with resource limits and egress proxy routing.

    Containers may reach the network only through HTTP(S)_PROXY pointing at
    AgentVigilante's whitelist CONNECT proxy on the Docker host. Recursive DNS is
    blackholed; whitelist package hosts are pinned via ``extra_hosts``.
    """

    def __init__(
        self,
        workdir: str | Path,
        base_image: str = DEFAULT_BASE_IMAGE,
        proxy_port: int = 8888,
        *,
        enable_strace: bool = True,
    ) -> None:
        self.base_image = base_image
        self.workdir = Path(workdir).resolve()
        self.proxy_port = proxy_port
        self.enable_strace = enable_strace
        if not self.workdir.is_dir():
            raise FileNotFoundError(f"workdir does not exist: {self.workdir}")

        self.extra_hosts: dict[str, str] = {}
        if platform.system() == "Linux":
            self.extra_hosts["host.docker.internal"] = "host-gateway"

        try:
            self.client = docker.from_env()
            self.client.ping()
        except Exception as exc:
            raise RuntimeError(
                "Failed to connect to Docker. Is the daemon running?"
            ) from exc

        logger.info(
            "AgentSandbox ready image=%s workdir=%s proxy_port=%s strace=%s",
            self.base_image,
            self.workdir,
            self.proxy_port,
            self.enable_strace,
        )

    def _proxy_env(self) -> dict[str, str]:
        proxy_url = f"http://host.docker.internal:{self.proxy_port}"
        return {
            "HTTP_PROXY": proxy_url,
            "HTTPS_PROXY": proxy_url,
            "http_proxy": proxy_url,
            "https_proxy": proxy_url,
            "NO_PROXY": "localhost,127.0.0.1",
            "no_proxy": "localhost,127.0.0.1",
        }

    def _whitelist_extra_hosts(self) -> dict[str, str]:
        """Pin CONNECT-whitelist domains so pip/npm work without recursive DNS."""
        hosts = dict(self.extra_hosts)
        for domain in DEFAULT_WHITELIST:
            if domain in hosts:
                continue
            try:
                infos = socket.getaddrinfo(domain, None, type=socket.SOCK_STREAM)
            except socket.gaierror as exc:
                logger.warning("Could not resolve whitelist host %s: %s", domain, exc)
                continue
            ipv4 = next(
                (info[4][0] for info in infos if info[0] == socket.AF_INET),
                None,
            )
            if ipv4:
                hosts[domain] = ipv4
        return hosts

    @staticmethod
    def _safe_job_token(job_id: str) -> str:
        return "".join(c if c.isalnum() or c in "-_" else "-" for c in job_id)

    def _wrap_command(self, command: str, job_id: str | None) -> str:
        if not self.enable_strace or not job_id:
            return command
        token = self._safe_job_token(job_id)
        trace = f"/workspace/.agentvigilante/strace/{token}.trace"
        return (
            f"mkdir -p /workspace/.agentvigilante/strace && "
            f"strace -f -tt "
            f"-e trace=openat,open,connect,socket,clone,clone3,execve,"
            f"unlink,unlinkat,rename,renameat,write "
            f"-o {shlex.quote(trace)} "
            f"/bin/sh -c {shlex.quote(command)}"
        )

    def start_command(
        self,
        command: str,
        *,
        job_id: str | None = None,
        shadow_dir: Path | None = None,
    ) -> Container:
        """Start a detached container for ``command`` and return it live.

        Mounts ``shadow_dir`` (hologram) at ``/workspace`` when provided;
        otherwise falls back to the origin ``workdir`` (tests / legacy).
        """
        mount_src = Path(shadow_dir).resolve() if shadow_dir else self.workdir
        wrapped = self._wrap_command(command, job_id)
        run_kwargs: dict = {
            "image": self.base_image,
            "command": ["/bin/sh", "-c", wrapped],
            "detach": True,
            "remove": False,
            "network_disabled": False,
            "mem_limit": "128m",
            "cpu_quota": 50000,
            "pids_limit": 64,
            "cap_drop": ["ALL"],
            "cap_add": ["SYS_PTRACE"],
            "security_opt": ["no-new-privileges:true"],
            "dns": ["127.0.0.1"],
            "ulimits": [
                Ulimit(name="nproc", soft=64, hard=64),
                Ulimit(name="nofile", soft=256, hard=256),
            ],
            "user": "1000:1000",
            "working_dir": "/workspace",
            "environment": self._proxy_env(),
            "volumes": {
                str(mount_src): {
                    "bind": "/workspace",
                    "mode": "rw",
                }
            },
        }
        hosts = self._whitelist_extra_hosts()
        if hosts:
            run_kwargs["extra_hosts"] = hosts

        container = self.client.containers.run(**run_kwargs)
        logger.debug(
            "Started container id=%s job_id=%s mount=%s cmd=%r",
            container.short_id,
            job_id,
            mount_src,
            command,
        )
        return container

    def execute_command(
        self,
        command: str,
        timeout: int = 10,
        *,
        job_id: str | None = None,
        shadow_dir: Path | None = None,
    ) -> CommandResult:
        """Run ``command`` inside a restricted ephemeral container."""
        if timeout <= 0:
            raise ValueError("timeout must be a positive integer")

        container: Container | None = None
        try:
            container = self.start_command(
                command, job_id=job_id, shadow_dir=shadow_dir
            )
            try:
                wait_result = container.wait(timeout=timeout)
            except Exception as wait_exc:
                logger.warning(
                    "Command timed out after %ss; killing container %s",
                    timeout,
                    container.short_id,
                )
                self._force_cleanup(container)
                raise TimeoutError(
                    f"Command exceeded timeout of {timeout}s and was killed"
                ) from wait_exc

            exit_code = int(wait_result.get("StatusCode", 1))
            stdout = self._decode_logs(container, stdout=True, stderr=False)
            stderr = self._decode_logs(container, stdout=False, stderr=True)
            self._safe_remove(container)
            container = None

            logger.info(
                "Command finished exit_code=%s stdout_bytes=%s stderr_bytes=%s",
                exit_code,
                len(stdout),
                len(stderr),
            )
            return CommandResult(stdout=stdout, stderr=stderr, exit_code=exit_code)

        except ImageNotFound:
            logger.error("Base image not found: %s", self.base_image)
            raise
        except ContainerError as exc:
            stdout = (
                exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
            )
            stderr = (
                exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
            )
            logger.warning(
                "ContainerError exit_code=%s stderr=%r",
                exc.exit_status,
                stderr[:200],
            )
            return CommandResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=int(exc.exit_status),
            )
        except TimeoutError:
            raise
        except APIError as exc:
            if container is not None:
                self._force_cleanup(container)
            logger.exception("Docker API error during execute_command")
            raise RuntimeError(f"Docker API error: {exc}") from exc
        except Exception:
            if container is not None:
                self._force_cleanup(container)
            raise

    def kill_container(self, container_id: str) -> None:
        """Force-kill and remove a container by id."""
        try:
            container = self.client.containers.get(container_id)
        except NotFound:
            return
        self._force_cleanup(container)

    @staticmethod
    def _decode_logs(container: Container, *, stdout: bool, stderr: bool) -> str:
        raw = container.logs(stdout=stdout, stderr=stderr)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)

    def _safe_remove(self, container: Container) -> None:
        try:
            container.remove(force=True)
        except NotFound:
            pass
        except APIError as exc:
            logger.warning("Failed to remove container %s: %s", container.id, exc)

    def _force_cleanup(self, container: Container) -> None:
        try:
            container.kill()
        except (NotFound, APIError) as exc:
            logger.debug("kill during cleanup: %s", exc)
        self._safe_remove(container)
