"""Load private voice credentials from a local environment file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class VoiceConfig:
    app_id: str
    access_token: str = field(repr=False)
    asr_resource_id: str
    tts_resource_id: str
    ark_api_key: str = field(repr=False)
    ark_model_id: str


def load_voice_config(path: Path) -> VoiceConfig:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()

    required = (
        "DOUBAO_APP_ID",
        "DOUBAO_ACCESS_TOKEN",
        "DOUBAO_ASR_RESOURCE_ID",
        "DOUBAO_TTS_RESOURCE_ID",
        "ARK_API_KEY",
        "ARK_MODEL_ID",
    )
    for key in required:
        if not values.get(key):
            raise ValueError(f"missing required voice setting: {key}")

    return VoiceConfig(
        app_id=values["DOUBAO_APP_ID"],
        access_token=values["DOUBAO_ACCESS_TOKEN"],
        asr_resource_id=values["DOUBAO_ASR_RESOURCE_ID"],
        tts_resource_id=values["DOUBAO_TTS_RESOURCE_ID"],
        ark_api_key=values["ARK_API_KEY"],
        ark_model_id=values["ARK_MODEL_ID"],
    )
