import os
from pathlib import Path

_dll_handles = []


def configure_cuda_dlls() -> None:
    venv = os.environ.get("VIRTUAL_ENV")

    if not venv:
        return

    nvidia_root = Path(venv) / "Lib" / "site-packages" / "nvidia"

    if not nvidia_root.exists():
        return

    dll_directories = sorted(
        {dll.parent for dll in nvidia_root.rglob("*.dll")}
    )

    for directory in dll_directories:
        _dll_handles.append(
            os.add_dll_directory(str(directory))
        )