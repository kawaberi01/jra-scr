import subprocess
import sys


def test_analysis_store_import_does_not_eagerly_load_service():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import jra_srb.analysis_store; "
            "assert 'jra_srb.service' not in sys.modules",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_package_level_jra_service_remains_available():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from jra_srb import JraService; "
            "from jra_srb.service import JraService as Service; "
            "assert JraService is Service",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
