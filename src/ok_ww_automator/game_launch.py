"""Launch arguments shared by automation and the desktop launcher."""

from .config import normalize_game_resource_quality


def game_launch_arguments(quality: str = "hd") -> list[str]:
    quality = normalize_game_resource_quality(quality)
    return ["Client", f"-krqlv={quality}", "-SkipSplash"]
