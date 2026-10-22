"""Launch installed LÖVE games with their runtime and host GPU preference."""

import shutil
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
GAME_DISTRIBUTIONS_ROOT = ROOT_DIR.parent.parent / "CS50 2D"
LOVE_RUNTIME_DLLS = (
    "love.dll",
    "lua51.dll",
    "mpg123.dll",
    "msvcp120.dll",
    "msvcr120.dll",
    "OpenAL32.dll",
    "SDL2.dll",
)


class GameManager:
    def __init__(self, gpu_manager):
        self.gpu_manager = gpu_manager
        self.active_games = {}

    def list_games(self, games_directory):
        games_path = Path(games_directory)
        games = []
        for executable in sorted(
            (
                path
                for path in games_path.iterdir()
                if path.is_file() and path.suffix.casefold() == ".exe"
            ),
            key=lambda path: path.name.casefold(),
        ):
            active = self.active_games.get(executable.stem.casefold())
            process = active.get("process") if active else None
            if process and process.poll() is not None:
                self.active_games.pop(executable.stem.casefold(), None)
                active = None
            games.append(
                {
                    "name": executable.stem,
                    "executable": executable.name,
                    "status": "RUNNING" if active else "INSTALLED",
                }
            )
        return games

    def launch(self, game_name, games_directory, args=None):
        games_path = Path(games_directory).resolve()
        if not games_path.is_dir():
            raise FileNotFoundError(f"Games directory does not exist: {games_path}")

        requested_path = Path(game_name)
        if requested_path.is_absolute():
            candidate = requested_path.resolve()
        elif requested_path.parts and requested_path.parts[0].casefold() == games_path.name.casefold():
            candidate = (games_path.parent / requested_path).resolve()
        else:
            candidate = (games_path / requested_path).resolve()
        try:
            candidate.relative_to(games_path)
        except ValueError:
            raise ValueError("Game path must stay inside the installed Games directory") from None

        requested_name = candidate.stem.casefold() if candidate.suffix else game_name.casefold()
        if requested_name.endswith(".exe"):
            requested_name = requested_name[:-4]
        if candidate.suffix.casefold() == ".exe":
            executable = candidate if candidate.is_file() else None
        elif candidate.suffix:
            executable = None
        else:
            executable = next(
                (
                    path
                    for path in games_path.iterdir()
                    if path.is_file()
                    and path.suffix.casefold() == ".exe"
                    and path.stem.casefold() == requested_name
                ),
                None,
            )
        if executable is None:
            raise FileNotFoundError(f"Installed game was not found: {game_name}")

        self._ensure_love_runtime(executable)
        gpu_preference = self.gpu_manager.set_high_performance_preference(executable)
        process = self.gpu_manager.launch_command(
            str(executable),
            args=args,
            cwd=games_path,
        )
        self.active_games[executable.stem.casefold()] = {
            "name": executable.stem,
            "process": process,
            "pid": process.pid,
            "gpu_preference": gpu_preference,
        }
        return (
            f"[GAME LAUNCHED] {executable.stem} (PID {process.pid}). "
            f"{gpu_preference}"
        )

    @staticmethod
    def _ensure_love_runtime(executable):
        missing = [
            name for name in LOVE_RUNTIME_DLLS
            if not (executable.parent / name).is_file()
        ]
        if not missing:
            return

        distribution = GAME_DISTRIBUTIONS_ROOT / executable.stem / "dist"
        if not distribution.is_dir():
            raise FileNotFoundError(
                f"LÖVE runtime is incomplete for {executable.name}; missing "
                f"{', '.join(missing)}. Matching runtime distribution was not found at "
                f"{distribution}."
            )

        unavailable = [name for name in missing if not (distribution / name).is_file()]
        if unavailable:
            raise FileNotFoundError(
                f"LÖVE runtime distribution for {executable.name} is missing: "
                f"{', '.join(unavailable)}."
            )
        for name in missing:
            shutil.copy2(distribution / name, executable.parent / name)
