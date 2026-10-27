import json

import pytest

from scripts.check_runtime import verify_weights


def test_missing_model_shard_is_detected_before_startup(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"layer": "model-00001.safetensors"}}))
    with pytest.raises(RuntimeError, match="неполные"):
        verify_weights(tmp_path)
    (tmp_path / "model-00001.safetensors").write_bytes(b"synthetic-test-shard")
    verify_weights(tmp_path)
