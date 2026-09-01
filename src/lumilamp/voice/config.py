"""Load private voice credentials from a local environment file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AsrConfig:
    app_id: str
    access_token: str = field(repr=False)
    resource_id: str


@dataclass(frozen=True, kw_only=True)
class VoiceConfig:
    asr: AsrConfig
    tts_api_key: str = field(repr=False)
    tts_resource_id: str
    ark_api_key: str = field(repr=False)
    ark_model_id: str
    kws_model_dir: Path
    wake_cache_dir: Path
    esp32_serial_by_id: Path | None = None

    @property
    def app_id(self) -> str:
        return self.asr.app_id

    @property
    def access_token(self) -> str:
        return self.asr.access_token

    @property
    def asr_resource_id(self) -> str:
        return self.asr.resource_id


def _load_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()
    return values


def _require_values(values: dict[str, str], required: tuple[str, ...]) -> None:
    for key in required:
        if not values.get(key):
            raise ValueError(f"missing required voice setting: {key}")


def load_asr_config(path: Path) -> AsrConfig:
    values = _load_values(path)
    required = (
        "DOUBAO_APP_ID",
        "DOUBAO_ACCESS_TOKEN",
        "DOUBAO_ASR_RESOURCE_ID",
    )
    _require_values(values, required)
    return AsrConfig(
        app_id=values["DOUBAO_APP_ID"],
        access_token=values["DOUBAO_ACCESS_TOKEN"],
        resource_id=values["DOUBAO_ASR_RESOURCE_ID"],
    )


def load_voice_config(path: Path) -> VoiceConfig:
    values = _load_values(path)

    required = (
        "DOUBAO_APP_ID",
        "DOUBAO_ACCESS_TOKEN",
        "DOUBAO_ASR_RESOURCE_ID",
        "DOUBAO_TTS_API_KEY",
        "DOUBAO_TTS_RESOURCE_ID",
        "ARK_API_KEY",
        "ARK_MODEL_ID",
        "LUMILAMP_KWS_MODEL_DIR",
        "LUMILAMP_WAKE_CACHE_DIR",
    )
    _require_values(values, required)

    serial_value = values.get("LUMILAMP_ESP32_SERIAL_BY_ID", "").strip()
    serial_path = Path(serial_value) if serial_value else None
    if serial_path is not None and (
        not serial_path.is_absolute() or "/dev/serial/by-id" not in str(serial_path.parent)
    ):
        raise ValueError("ESP32 serial path must be under /dev/serial/by-id")

    return VoiceConfig(
        asr=AsrConfig(
            app_id=values["DOUBAO_APP_ID"],
            access_token=values["DOUBAO_ACCESS_TOKEN"],
            resource_id=values["DOUBAO_ASR_RESOURCE_ID"],
        ),
        tts_api_key=values["DOUBAO_TTS_API_KEY"],
        tts_resource_id=values["DOUBAO_TTS_RESOURCE_ID"],
        ark_api_key=values["ARK_API_KEY"],
        ark_model_id=values["ARK_MODEL_ID"],
        kws_model_dir=Path(values["LUMILAMP_KWS_MODEL_DIR"]),
        wake_cache_dir=Path(values["LUMILAMP_WAKE_CACHE_DIR"]),
        esp32_serial_by_id=serial_path,
    )
