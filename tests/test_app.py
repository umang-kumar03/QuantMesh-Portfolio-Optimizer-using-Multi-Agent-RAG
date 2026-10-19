from streamlit.testing.v1 import AppTest


def test_dashboard_and_save_research(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTMESH_DB", str(tmp_path / "research.db"))
    app = AppTest.from_file("app.py", default_timeout=30).run()
    assert not app.exception
    assert len(app.metric) == 4
    assert len(app.tabs) == 5
    app.button(key="save-research").click().run()
    assert not app.exception
    assert any("saved" in message.value.lower() for message in app.success)
    app.sidebar.selectbox[0].select("Maximum Sharpe").run()
    assert not app.exception


def test_infeasible_configuration_shows_error():
    app = AppTest.from_file("app.py", default_timeout=30).run()
    app.sidebar.slider[1].set_value(10).run()
    assert not app.exception
    assert any("infeasible" in message.value for message in app.error)


def test_live_history_without_key_displays_sample_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    monkeypatch.setenv("QUANTMESH_CACHE_DB", str(tmp_path / "market.db"))
    monkeypatch.setenv("QUANTMESH_DB", str(tmp_path / "research.db"))
    app = AppTest.from_file("app.py", default_timeout=30).run()
    app.sidebar.radio[0].set_value("Alpha Vantage").run()
    assert not app.exception
    load = next(button for button in app.button if button.label == "Load market history")
    load.click().run()
    assert not app.exception
    assert len(app.metric) == 4
    assert any("SYNTHETIC" in message.value for message in app.warning)
    app.button(key="save-research").click().run()
    from quantmesh.storage import list_runs
    saved = list_runs(str(tmp_path / "research.db"))[0]["payload"]
    assert saved["data_source"] == "Synthetic sample fallback"
    assert saved["market_provenance"]["synthetic"]


def test_optional_ai_missing_key_preserves_analytics(tmp_path, monkeypatch):
    monkeypatch.delenv("QUANTMESH_LLM_API_KEY", raising=False)
    monkeypatch.setenv("QUANTMESH_DB", str(tmp_path / "research.db"))
    app = AppTest.from_file("app.py", default_timeout=30).run()
    consent = next(c for c in app.checkbox if c.label.startswith("I agree"))
    consent.check().run()
    next(b for b in app.button if b.label == "Generate AI explanation").click().run()
    assert not app.exception
    assert len(app.metric) == 4
    assert any("QUANTMESH_LLM_API_KEY" in e.value for e in app.error)
