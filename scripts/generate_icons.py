#!/usr/bin/env python3
"""从 Combo 品牌源图生成 Tauri 应用图标。"""
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("需要安装 Pillow: pip install Pillow")
    sys.exit(1)


ICON_SAFE_MARGIN_RATIO = 0.055
ICON_CORNER_RADIUS_RATIO = 0.20


def create_icon(source_path: Path, size: int, output_path: Path):
    """生成带透明外沿和纯白圆角底板的跨平台图标。"""
    margin = max(1, round(size * ICON_SAFE_MARGIN_RATIO))
    tile_size = size - margin * 2
    radius = max(1, round(tile_size * ICON_CORNER_RADIUS_RATIO))

    with Image.open(source_path) as source:
        foreground = source.convert("RGBA").resize(
            (tile_size, tile_size),
            Image.Resampling.LANCZOS,
        )

    tile = Image.new("RGBA", (tile_size, tile_size), (255, 255, 255, 255))
    tile.alpha_composite(foreground)
    mask = Image.new("L", (tile_size, tile_size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, tile_size - 1, tile_size - 1),
        radius=radius,
        fill=255,
    )
    tile.putalpha(mask)

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    image.alpha_composite(tile, (margin, margin))
    image.save(output_path, format='PNG')
    print(f"✓ 生成图标: {output_path} ({size}x{size})")


def create_icns(png_1024: Path, output_icns: Path):
    """创建 macOS .icns 文件（需要 iconutil）"""
    import subprocess
    import tempfile
    import shutil

    with tempfile.TemporaryDirectory() as tmpdir:
        iconset = Path(tmpdir) / "icon.iconset"
        iconset.mkdir()

        # 生成各种尺寸
        sizes = [16, 32, 64, 128, 256, 512, 1024]
        for size in sizes:
            img = Image.open(png_1024)
            img = img.resize((size, size), Image.Resampling.LANCZOS)
            img.save(iconset / f"icon_{size}x{size}.png")

            # @2x 版本
            if size <= 512:
                img_2x = Image.open(png_1024)
                img_2x = img_2x.resize((size * 2, size * 2), Image.Resampling.LANCZOS)
                img_2x.save(iconset / f"icon_{size}x{size}@2x.png")

        # 使用 iconutil 转换
        try:
            subprocess.run(
                ["iconutil", "-c", "icns", "-o", str(output_icns), str(iconset)],
                check=True
            )
            print(f"✓ 生成 macOS 图标: {output_icns}")
        except subprocess.CalledProcessError:
            print(f"⚠ 无法生成 .icns（需要 macOS iconutil）")
        except FileNotFoundError:
            print(f"⚠ iconutil 未找到，跳过 .icns 生成")


def create_ico(source_path: Path, output_ico: Path):
    """创建 Windows .ico 文件"""
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    with Image.open(source_path) as source:
        image = source.convert("RGBA")
        image.save(output_ico, format="ICO", sizes=sizes)
    print(f"✓ 生成 Windows 图标: {output_ico}")


def main():
    project_root = Path(__file__).parent.parent
    icons_dir = project_root / "src-tauri" / "icons"
    source_path = project_root / "web_frontend" / "frontend" / "src" / "assets" / "fast-agent-factory-icon.png"
    icons_dir.mkdir(parents=True, exist_ok=True)
    if not source_path.is_file():
        print(f"品牌源图不存在: {source_path}")
        sys.exit(1)

    print("=" * 60)
    print("Combo 图标生成工具")
    print("=" * 60)

    create_icon(source_path, 32, icons_dir / "32x32.png")
    create_icon(source_path, 128, icons_dir / "128x128.png")
    create_icon(source_path, 256, icons_dir / "128x128@2x.png")
    create_icon(source_path, 256, icons_dir / "256x256.png")
    create_icon(source_path, 1024, icons_dir / "icon-1024.png")
    create_icon(source_path, 1024, icons_dir / "icon.png")

    # 2. 生成 macOS .icns
    create_icns(icons_dir / "icon-1024.png", icons_dir / "icon.icns")

    # 3. 生成 Windows .ico
    create_ico(icons_dir / "icon-1024.png", icons_dir / "icon.ico")

    print("=" * 60)
    print("✓ 图标生成完成")
    print(f"目标目录: {icons_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
