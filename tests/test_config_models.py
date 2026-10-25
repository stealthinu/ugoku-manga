import pytest

from ugoku import config, models


def test_registry_ok():
    assert models.verify_registry(open("NOTICE.md").read()) == []


def test_registry_rejects_bad_licence(monkeypatch):
    bad = models.ModelSpec("x", "x.onnx", "https://e/x", "https://e", "0" * 64, "CC-BY-NC-4.0")
    monkeypatch.setitem(models.REGISTRY, "x", bad)
    assert any("not allowed" in e for e in models.verify_registry())


def test_config_precedence(tmp_path, monkeypatch):
    f = tmp_path / "c.toml"
    f.write_text('threads = 3\nmodel_dir = "~/m"\n[eval]\ndir = "/data/pages"\n')
    monkeypatch.delenv("UGOKU_THREADS", raising=False)
    s = config.load(f)
    assert s.threads == 3 and str(s.eval_dir) == "/data/pages"
    monkeypatch.setenv("UGOKU_THREADS", "5")
    assert config.load(f).threads == 5


def test_model_path_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("UGOKU_MODEL_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        models.model_path("ctd")
