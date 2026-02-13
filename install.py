#!/usr/bin/env python3
"""
跨平台安装脚本 - 自动检测平台并安装相应依赖
"""
import os
import sys
import subprocess
import venv
from pathlib import Path


def get_platform():
    """获取当前平台"""
    if sys.platform == "darwin":
        return "macos"
    elif sys.platform == "win32":
        return "windows"
    elif sys.platform.startswith("linux"):
        return "linux"
    else:
        return "unknown"


def create_venv(venv_path: Path):
    """创建虚拟环境"""
    print(f"创建虚拟环境: {venv_path}")
    venv.create(venv_path, with_pip=True)


def get_pip_path(venv_path: Path) -> Path:
    """获取虚拟环境中的 pip 路径"""
    if sys.platform == "win32":
        return venv_path / "Scripts" / "pip.exe"
    else:
        return venv_path / "bin" / "pip"


def get_python_path(venv_path: Path) -> Path:
    """获取虚拟环境中的 Python 路径"""
    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"
    else:
        return venv_path / "bin" / "python"


def install_requirements(venv_path: Path, platform: str):
    """安装依赖"""
    pip_path = get_pip_path(venv_path)
    requirements_dir = Path(__file__).parent / "requirements"

    # 确定依赖文件
    if platform == "macos":
        req_file = requirements_dir / "macos.txt"
    elif platform == "windows":
        req_file = requirements_dir / "windows.txt"
    else:
        req_file = requirements_dir / "common.txt"

    if not req_file.exists():
        print(f"错误: 依赖文件不存在: {req_file}")
        return False

    print(f"安装依赖: {req_file}")
    result = subprocess.run(
        [str(pip_path), "install", "-r", str(req_file)],
        capture_output=False
    )

    return result.returncode == 0


def main():
    """主函数"""
    print("=" * 50)
    print("语音输入 - 跨平台安装脚本")
    print("=" * 50)

    # 检测平台
    platform = get_platform()
    print(f"\n检测到平台: {platform}")

    if platform == "unknown":
        print("错误: 不支持的平台")
        sys.exit(1)

    if platform == "linux":
        print("警告: Linux 支持尚未完善，将只安装通用依赖")

    # 项目目录
    project_dir = Path(__file__).parent
    venv_path = project_dir / ".venv"

    # 检查虚拟环境
    if not venv_path.exists():
        create_venv(venv_path)
    else:
        print(f"虚拟环境已存在: {venv_path}")

    # 升级 pip
    pip_path = get_pip_path(venv_path)
    print("\n升级 pip...")
    subprocess.run([str(pip_path), "install", "--upgrade", "pip"], capture_output=True)

    # 安装依赖
    print("\n安装依赖...")
    if install_requirements(venv_path, platform):
        print("\n安装完成！")
    else:
        print("\n安装失败！")
        sys.exit(1)

    # 显示使用说明
    python_path = get_python_path(venv_path)
    print("\n" + "=" * 50)
    print("使用说明")
    print("=" * 50)
    print(f"\n激活虚拟环境:")
    if platform == "windows":
        print(f"  .venv\\Scripts\\activate")
    else:
        print(f"  source .venv/bin/activate")

    print(f"\n运行应用:")
    print(f"  python voice_input_app.py")

    print(f"\n或直接运行:")
    print(f"  {python_path} voice_input_app.py")


if __name__ == "__main__":
    main()
