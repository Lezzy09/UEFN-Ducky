"""The numpy embedder matches model2vec's StaticModel.encode on the shipped model."""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("tokenizers")

from backend.search import embedder  # noqa: E402

FIXTURE = Path(__file__).with_name("fixtures") / "parity.npz"


@pytest.fixture
def model():
    embedder.reset_for_tests()
    emb = embedder.get_embedder()
    if emb is None:
        pytest.skip("no search model folder (run build/fetch_search_model.py)")
    yield emb
    embedder.reset_for_tests()


def test_parity_with_model2vec_reference(model) -> None:
    data = np.load(FIXTURE, allow_pickle=False)
    texts = [str(t) for t in data["texts"]]
    got = model.encode(texts)
    assert got.shape == data["vectors"].shape == (20, 256)
    assert float(np.abs(got - data["vectors"]).max()) <= 2e-3  # float16 matrix vs float32 reference


def test_rows_are_unit_length_or_zero(model) -> None:
    vecs = model.encode(["night sky stars", "", "   "])
    assert abs(float(np.linalg.norm(vecs[0])) - 1.0) < 1e-5
    assert not vecs[1].any() and not vecs[2].any()


def test_meaning_is_closer_for_related_text(model) -> None:
    q, near, far = model.encode(["night sky stars", "starfield material recipe", "player spawn pad"])
    assert float(q @ near) > float(q @ far)


def test_model_id_names_model_and_revision(model) -> None:
    assert model.model_id.startswith("potion-base-8M@")


def test_missing_folder_means_keyword_only(monkeypatch, tmp_path: Path) -> None:
    embedder.reset_for_tests()
    monkeypatch.setattr(embedder, "model_dir", lambda: None)
    assert embedder.get_embedder() is None
    assert embedder.unavailable_reason() == "no model folder"
    embedder.reset_for_tests()
