#!/usr/bin/env python3
"""
生成 Tauri 应用图标
使用 PIL/Pillow 创建简单的品牌图标
"""
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("需要安装 Pillow: pip install Pillow")
    sys.exit(1)


def create_icon(size: int, output_path: Path):
    """创建应用图标"""
    # 创建背景（RGBA 模式，Tauri 要求）
    img = Image.new('RGBA', (size, size), color=(26, 26, 46, 255))
    draw = ImageDraw.Draw(img)

    # 绘制圆角矩形背景
    margin = size // 8
    draw.rounded_rectangle(
        [(margin, margin), (size - margin, size - margin)],
        radius=size // 10,
        fill=(15, 52, 96, 255),
        outline=(22, 33, 62, 255),
        width=size // 40
    )

    # 绘制简化的 "FA" 文字标识
    try:
        # 尝试使用系统字体
        font_size = size // 2
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except:
        # 回退到默认字体
        font = ImageFont.load_default()

    text = "FA"
    # 获取文字边界框
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # 居中绘制文字
    x = (size - text_width) // 2
    y = (size - text_height) // 2 - size // 20

    draw.text((x, y), text, fill=(233, 69, 96, 255), font=font)

    # 保存
    img.save(output_path, format='PNG')
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


def create_ico(png_256: Path, output_ico: Path):
    """创建 Windows .ico 文件"""
    img = Image.open(png_256)

    # 生成多尺寸 ico
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    images = []
    for size in sizes:
        resized = img.resize(size, Image.Resampling.LANCZOS)
        images.append(resized)

    # 保存为 ico（第一个图片是主图）
    images[0].save(
        output_ico,
        format='ICO',
        sizes=[img.size for img in images],
        append_images=images[1:]
    )
    print(f"✓ 生成 Windows 图标: {output_ico}")


def main():
    # 图标输出目录
    project_root = Path(__file__).parent.parent
    icons_dir = project_root / "src-tauri" / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("FastAgentFactory 图标生成工具")
    print("=" * 60)

    # 1. 生成各种尺寸的 PNG
    create_icon(32, icons_dir / "32x32.png")
    create_icon(128, icons_dir / "128x128.png")
    create_icon(256, icons_dir / "128x128@2x.png")
    create_icon(1024, icons_dir / "icon-1024.png")

    # 2. 生成 macOS .icns
    create_icns(icons_dir / "icon-1024.png", icons_dir / "icon.icns")

    # 3. 生成 Windows .ico
    create_ico(icons_dir / "128x128@2x.png", icons_dir / "icon.ico")

    print("=" * 60)
    print("✓ 图标生成完成")
    print(f"目标目录: {icons_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
