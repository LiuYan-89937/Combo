#!/usr/bin/env python3
"""从 Combo 品牌源图生成 Tauri 应用图标。"""
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("需要安装 Pillow: pip install Pillow")
    sys.exit(1)


MASTER_ICON_SIZE = 1254
ICON_TILE_RATIO = 0.82
MASCOT_TO_TILE_RATIO = 0.72
MASCOT_BACKGROUND_CUTOFF = 245
TILE_CORNER_RATIO = 0.22


def extract_black_mascot(source_path: Path) -> Image.Image:
    """从浅色品牌母版中提取黑色 Combo 角色，保留抗锯齿透明边缘。"""
    with Image.open(source_path) as source:
        grayscale = source.convert("L")

    alpha = grayscale.point(
        lambda value: 0
        if value >= MASCOT_BACKGROUND_CUTOFF
        else round(255 * (MASCOT_BACKGROUND_CUTOFF - value) / MASCOT_BACKGROUND_CUTOFF)
    )
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError(f"品牌母版中没有可提取的黑色角色: {source_path}")

    alpha = alpha.crop(bounds)
    mascot = Image.new("RGBA", alpha.size, (0, 0, 0, 255))
    mascot.putalpha(alpha)
    return mascot


def create_master_icon(source_path: Path, output_path: Path) -> None:
    """生成透明外沿、白色圆角底和黑色 Combo 角色的应用图标母版。"""
    canvas = Image.new("RGBA", (MASTER_ICON_SIZE, MASTER_ICON_SIZE), (0, 0, 0, 0))
    tile_size = round(MASTER_ICON_SIZE * ICON_TILE_RATIO)
    tile_offset = (MASTER_ICON_SIZE - tile_size) // 2
    tile = Image.new("RGBA", (tile_size, tile_size), (255, 255, 255, 255))

    from PIL import ImageDraw

    rounded_tile = Image.new("L", tile.size, 0)
    ImageDraw.Draw(rounded_tile).rounded_rectangle(
        (0, 0, tile_size - 1, tile_size - 1),
        radius=round(tile_size * TILE_CORNER_RATIO),
        fill=255,
    )
    tile.putalpha(rounded_tile)
    canvas.alpha_composite(tile, (tile_offset, tile_offset))

    mascot = extract_black_mascot(source_path)
    mascot_limit = round(tile_size * MASCOT_TO_TILE_RATIO)
    mascot.thumbnail((mascot_limit, mascot_limit), Image.Resampling.LANCZOS)
    mascot_position = (
        (MASTER_ICON_SIZE - mascot.width) // 2,
        (MASTER_ICON_SIZE - mascot.height) // 2,
    )
    canvas.alpha_composite(mascot, mascot_position)
    canvas.save(output_path, format="PNG")
    print(f"✓ 生成品牌母版: {output_path} ({MASTER_ICON_SIZE}x{MASTER_ICON_SIZE})")


def create_icon(source_path: Path, size: int, output_path: Path):
    """将应用图标母版缩放为平台资源。"""
    with Image.open(source_path) as source:
        image = source.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
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
    brand_dir = project_root / "web_frontend" / "frontend" / "public" / "brand" / "combo"
    mascot_source_path = brand_dir / "logo-light.png"
    source_path = brand_dir / "app-icon.png"
    icons_dir.mkdir(parents=True, exist_ok=True)
    if not mascot_source_path.is_file():
        print(f"品牌源图不存在: {mascot_source_path}")
        sys.exit(1)

    print("=" * 60)
    print("Combo 图标生成工具")
    print("=" * 60)

    create_master_icon(mascot_source_path, source_path)
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
