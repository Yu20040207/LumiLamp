from __future__ import annotations

from pathlib import Path
import tomllib
import unittest


class PyprojectMetadataTests(unittest.TestCase):
    def test_kws_tools_extra_declares_only_text2token_dependencies(self) -> None:
        project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]

        self.assertEqual(
            project.get("optional-dependencies", {}).get("kws-tools"),
            [
                "click>=8,<9",
                "sentencepiece>=0.2,<1",
                "pypinyin>=0.55,<1",
            ],
        )
