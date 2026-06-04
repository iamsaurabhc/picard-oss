from app.services.settings_store import merge_cors_origins, merged_settings_dict


def test_merge_cors_origins_adds_missing_desktop_ports():
    user = ["http://localhost:3000", "http://127.0.0.1:3000", "tauri://localhost"]
    defaults = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:13130",
        "http://127.0.0.1:13130",
        "tauri://localhost",
    ]
    merged = merge_cors_origins(user, defaults)
    assert "http://127.0.0.1:13130" in merged
    assert merged.index("http://localhost:3000") < merged.index("http://127.0.0.1:13130")


def test_merged_settings_dict_unions_cors_origins(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    cfg = data_dir / "config"
    cfg.mkdir(parents=True)
    (cfg / "settings.json").write_text(
        '{"cors_origins": ["http://localhost:3000", "http://127.0.0.1:3000"]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("PICARD_DATA_DIR", str(data_dir))
    merged = merged_settings_dict(data_dir)
    assert "http://127.0.0.1:13130" in merged["cors_origins"]
