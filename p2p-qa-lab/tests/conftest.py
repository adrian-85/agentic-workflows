import os, socket, subprocess, sys, time
import pytest


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def p2p_api(request):
    """Function-scoped: boots a throwaway mock API subprocess and yields its base URL."""
    import httpx

    # Allow @pytest.mark.parametrize("p2p_api", ["<profile>"], indirect=True)
    if hasattr(request, "param") and request.param:
        bug_profile = request.param
    else:
        bug_profile = "clean"
    port = _free_port()
    env = dict(os.environ, P2P_BUG_PROFILE=bug_profile)
    if request.keywords.get("require_auth"):
        env["P2P_REQUIRE_AUTH"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "p2p_qa.mock_api", "--host", "127.0.0.1", "--port", str(port)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            if httpx.get(base + "/vendors").status_code in (200, 401):
                break
        except Exception:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("mock API failed to start")
    yield base
    proc.terminate()
    proc.wait(timeout=5)