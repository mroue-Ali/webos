from tests.conftest import APP_ID, CONTAINER_STATS, SYSTEM_DF, Env, write_proc
from webos.metrics import parse_container_stats, read_net_dev, summarize_df


def test_server_stats(authed: Env) -> None:
    # One interval later: 800 jiffies passed, 600 of them idle; eth0 moved 5000/2500 bytes.
    write_proc(authed.proc, cpu="200 0 200 1400 0 0 0 0", eth0=(6000, 4500))
    authed.clock.advance(5)
    authed.app.state.ctx.metrics.sampler.sample()

    response = authed.client.get("/api/server")
    assert response.status_code == 200
    data = response.json()

    assert data["host"] == {
        "hostname": "vps",
        "os": "Ubuntu 24.04 LTS",
        "kernel": "6.8.0",
        "cpus": 4,
        "docker_version": "28.1.1",
        "uptime_seconds": 3600.5,
    }
    assert data["cpu"] == {"percent": 25.0, "load": [0.5, 0.4, 0.3]}
    assert data["memory"] == {
        "total": 8_192_000_000,
        "used": 2_048_000_000,
        "available": 6_144_000_000,
        "swap_total": 4_096_000_000,
        "swap_used": 1_024_000_000,
    }
    assert data["disk"]["total"] > 0
    assert data["network"] == [
        {"name": "eth0", "rx_bytes": 6000, "tx_bytes": 4500, "rx_rate": 1000.0, "tx_rate": 500.0}
    ]
    assert data["docker_disk"] == {
        "images": 5000,
        "images_reclaimable": 2000,
        "containers": 15,
        "volumes": 700,
        "build_cache": 500,
        "build_cache_reclaimable": 400,
    }
    history = data["history"]
    assert history["cpu"][-1] == 25.0 and history["rx"][-1] == 1000.0
    assert len(history["ts"]) == len(history["memory"]) == 2

    usage = {c["id"]: c for c in data["containers"]}
    assert len(usage) == 3  # running containers only
    assert usage[APP_ID]["cpu_percent"] == 10.0
    assert usage[APP_ID]["memory_used"] == 200_000_000


def test_server_stats_require_login(env: Env) -> None:
    assert env.client.get("/api/server").status_code == 401


def test_first_sample_has_no_rates_yet(authed: Env) -> None:
    data = authed.client.get("/api/server").json()
    assert data["cpu"]["percent"] is None
    assert data["network"][0]["rx_rate"] is None


def test_parse_container_stats() -> None:
    assert parse_container_stats(CONTAINER_STATS) == (10.0, 200_000_000, 8_000_000_000, 1234, 5678)
    assert parse_container_stats({}) == (0.0, 0, 0, 0, 0)


def test_summarize_df() -> None:
    disk = summarize_df(SYSTEM_DF)
    assert (disk.images, disk.images_reclaimable, disk.volumes) == (5000, 2000, 700)


def test_virtual_interfaces_are_skipped(authed: Env) -> None:
    assert read_net_dev(authed.proc / "net_dev") == {"eth0": (1000, 2000)}
    assert read_net_dev(authed.proc / "missing") is None
