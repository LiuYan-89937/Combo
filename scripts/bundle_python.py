#!/usr/bin/env python3
"""
下载并打包 python-build-standalone 到 Tauri 资源目录
用于生产环境的 Python 运行时
"""
import os
import sys
import platform
import shutil
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


def install_dependencies(python_dir: Path, requirements_file: Path):
    """使用打包的 Python 安装项目依赖"""
    python_exe = _find_python_executable(python_dir)
    if not python_exe:
        print("✗ 无法找到 Python 可执行文件，跳过依赖安装")
        return

    if not requirements_file.exists():
        print(f"⚠ requirements.txt 不存在: {requirements_file}")
        return

    print(f"\n安装依赖到打包的 Python...")
    import subprocess

    try:
        # 升级 pip
        subprocess.run([str(python_exe), "-m", "pip", "install", "--upgrade", "pip"], check=True)

        # 安装依赖
        subprocess.run(
            [str(python_exe), "-m", "pip", "install", "-r", str(requirements_file)],
            check=True
        )
        print("✓ 依赖安装完成")
    except subprocess.CalledProcessError as e:
        print(f"✗ 依赖安装失败: {e}")


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

    # 3. 安装项目依赖（可选，可以在运行时首次启动时安装）
    requirements_file = project_root / "requirements.txt"
    if requirements_file.exists():
        install_choice = input("\n是否安装项目依赖到打包的 Python？(y/N): ").strip().lower()
        if install_choice == "y":
            install_dependencies(python_bundle_dir, requirements_file)

    print("\n" + "=" * 60)
    print("✓ Python 打包完成")
    print(f"目标目录: {python_bundle_dir}")
    print("=" * 60)
    print("\n现在可以运行: cd src-tauri && cargo tauri build")


if __name__ == "__main__":
    main()
