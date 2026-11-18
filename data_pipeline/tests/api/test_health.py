def test_health_needs_no_database(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok", "version": "test"}


def test_unknown_route_is_json_404(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert r.get_json()["error"] == "Not Found"
