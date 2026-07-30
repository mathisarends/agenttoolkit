import subprocess
import sys
import textwrap
from pathlib import Path


def test_mcp_is_lazy_and_reports_its_missing_extra() -> None:
    script = textwrap.dedent("""
        import importlib.abc
        import sys


        class BlockMCPDependencies(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".", maxsplit=1)[0] in {
                    "httpx2",
                    "mcp",
                    "mcp_types",
                }:
                    raise ModuleNotFoundError(
                        f"blocked optional dependency: {fullname}",
                        name=fullname,
                    )
                return None


        sys.meta_path.insert(0, BlockMCPDependencies())

        import agenttoolkit

        assert "agenttoolkit.mcp" not in sys.modules

        from agenttoolkit.mcp import MCPClient

        assert MCPClient.__name__ == "MCPClient"

        try:
            from agenttoolkit.mcp import StdioMCPClient
        except ModuleNotFoundError as exc:
            assert "agenttoolkit[mcp]" in str(exc)
        else:
            raise AssertionError("import unexpectedly succeeded")
        """)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
