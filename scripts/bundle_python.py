#!/usr/bin/env python3
"""
下载并打包 python-build-standalone 到 Tauri 资源目录
用于生产环境的 Python 运行时
"""
import os
import platform
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Optional
from urllib.request import urlretrieve

# python-build-standalone 版本配置
PYTHON_VERSION = "3.11"
PBS_VERSION = "20240726"  # 最新稳定版本

# 平台映射
PLATFORM_MAP = {
    "Darwin": {
        "x86_64": f"cpython-{PYTHON_VERSION}.9+{PBS_VERSION}-x86_64-apple-darwin-install_only.tar.gz",
        "arm64": f"cpython-{PYTHON_VERSION}.9+{PBS_VERSION}-aarch64-apple-darwin-install_only.tar.gz",
    },
    "Linux": {
        "x86_64": f"cpython-{PYTHON_VERSION}.9+{PBS_VERSION}-x86_64-unknown-linux-gnu-install_only.tar.gz",
    },
    "Windows": {
        "AMD64": f"cpython-{PYTHON_VERSION}.9+{PBS_VERSION}-x86_64-pc-windows-msvc-shared-install_only.tar.gz",
    },
}

BASE_URL = "https://github.com/indygreg/python-build-standalone/releases/download"


def get_platform_info():
    """获取当前平台信息"""
    system = platform.system()
    machine = platform.machine()

    if system == "Darwin" and machine == "arm64":
        return "Darwin", "arm64"
    elif system == "Darwin":
        return "Darwin", "x86_64"
    elif system == "Linux":
        return "Linux", "x86_64"
    elif system == "Windows":
        return "Windows", "AMD64"
    else:
        raise RuntimeError(f"不支持的平台: {system} {machine}")


def download_python(output_dir: Path):
    """下载对应平台的 python-build-standalone"""
    system, arch = get_platform_info()
    filename = PLATFORM_MAP[system][arch]
    url = f"{BASE_URL}/{PBS_VERSION}/{filename}"

    output_file = output_dir / filename

    if output_file.exists():
        print(f"✓ Python 包已存在: {output_file}")
        return output_file

    print(f"下载 {filename}...")
    print(f"URL: {url}")

    try:
        urlretrieve(url, output_file, reporthook=_download_progress)
        print(f"\n✓ 下载完成: {output_file}")
        return output_file
    except Exception as e:
        print(f"\n✗ 下载失败: {e}")
        sys.exit(1)


def _download_progress(block_num, block_size, total_size):
    """显示下载进度"""
    downloaded = block_num * block_size
    if total_size > 0:
        percent = min(downloaded * 100 / total_size, 100)
        mb_downloaded = downloaded / (1024 * 1024)
        mb_total = total_size / (1024 * 1024)
        print(f"\r进度: {percent:.1f}% ({mb_downloaded:.1f}/{mb_total:.1f} MB)", end="")


def extract_python(archive_path: Path, target_dir: Path):
    """解压 Python 归档到目标目录"""
    print(f"\n解压到 {target_dir}...")

    # 清理旧目录
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    # 解压
    if archive_path.suffix == ".gz":
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(target_dir)
    elif archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path, "r") as zip_ref:
            zip_ref.extractall(target_dir)
    else:
        raise RuntimeError(f"不支持的归档格式: {archive_path.suffix}")

    # 归档内容通常在 python/ 子目录
    extracted_python = target_dir / "python"
    if extracted_python.exists():
        # 将内容移到父目录
        for item in extracted_python.iterdir():
            shutil.move(str(item), target_dir / item.name)
        extracted_python.rmdir()

    print(f"✓ 解压完成")

    # 验证 Python 可执行文件
    python_exe = _find_python_executable(target_dir)
    if python_exe:
        print(f"✓ Python 可执行文件: {python_exe}")
    else:
        print("⚠ 警告: 未找到 Python 可执行文件")

    # 转换符号链接为实际文件（Tauri 不支持打包符号链接）
    _convert_symlinks_to_files(target_dir)


def _find_python_executable(python_dir: Path) -> Optional[Path]:
    """查找 Python 可执行文件"""
    candidates = [
        python_dir / "bin" / "python3",
        python_dir / "bin" / "python",
        python_dir / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _convert_symlinks_to_files(python_dir: Path):
    """将符号链接转换为实际文件（Tauri 不支持打包符号链接）"""
    import os

    print(f"\n转换符号链接...")
    converted = 0

    for root, dirs, files in os.walk(python_dir):
        root_path = Path(root)
        for name in files + dirs:
            item = root_path / name
            if item.is_symlink():
                try:
                    target = item.readlink()
                    # 解析相对路径
                    if not target.is_absolute():
                        target = (item.parent / target).resolve()

                    # 删除符号链接
                    item.unlink()

                    # 复制实际文件或目录
                    if target.is_dir():
                        shutil.copytree(target, item)
                    else:
                        shutil.copy2(target, item)

                    converted += 1
                except Exception as e:
                    print(f"⚠ 无法转换 {item}: {e}")

    print(f"✓ 转换了 {converted} 个符号链接")


def install_dependencies(python_dir: Path, project_root: Path):
    """使用打包的 Python 安装项目依赖"""
    python_exe = _find_python_executable(python_dir)
    if not python_exe:
        print("✗ 无法找到 Python 可执行文件，跳过依赖安装")
        return

    print(f"\n安装依赖到打包的 Python...")
    import subprocess

    try:
        # 升级 pip
        print("升级 pip...")
        subprocess.run([str(python_exe), "-m", "pip", "install", "--upgrade", "pip"], check=True)

        # 安装项目及其依赖（包括 web 可选依赖）
        print("安装项目依赖...")
        subprocess.run(
            [str(python_exe), "-m", "pip", "install", "-e", f"{project_root}[web]"],
            check=True
        )
        browser_dir = python_dir / "playwright-browsers"
        browser_environment = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(browser_dir)}
        print("安装 Chromium 浏览器运行时...")
        subprocess.run(
            [str(python_exe), "-m", "playwright", "install", "chromium"],
            check=True,
            env=browser_environment,
        )
        print("✓ 依赖安装完成")
    except subprocess.CalledProcessError as e:
        print(f"✗ 依赖安装失败: {e}")
        sys.exit(1)


def main():
    # 项目根目录
    project_root = Path(__file__).parent.parent

    # 下载目录
    download_dir = project_root / "build" / "python-downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    # Tauri 资源目录
    resources_dir = project_root / "src-tauri" / "resources"
    python_bundle_dir = resources_dir / "python"
    resources_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("FastAgentFactory Python 打包工具")
    print("=" * 60)

    # 1. 下载 python-build-standalone
    archive_path = download_python(download_dir)

    # 2. 解压到资源目录
    extract_python(archive_path, python_bundle_dir)

    # 3. 安装项目依赖
    print("\n准备安装项目依赖...")
    install_dependencies(python_bundle_dir, project_root)

    # 依赖与 Chromium 安装后可能新增符号链接，统一转换为可打包文件。
    _convert_symlinks_to_files(python_bundle_dir)

    print("\n" + "=" * 60)
    print("✓ Python 打包完成")
    print(f"目标目录: {python_bundle_dir}")
    print("=" * 60)
    print("\n现在可以运行: cd src-tauri && cargo tauri build")


if __name__ == "__main__":
    main()
