"""
打包脚本：PyInstaller 文件夹模式 → dist/qq-group-digest/ → dist/qq-group-digest-v<版本>-windows.zip

只在打包的电脑上需要 pywebview 和 PyInstaller，用户拿到的 exe 不需要安装任何东西：
    python -m venv .venv
    .venv\\Scripts\\python -m pip install pywebview pyinstaller
    .venv\\Scripts\\python build\\build_exe.py
"""

import importlib.metadata as metadata
import os
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORK = ROOT / "build" / "pyinstaller"
NAME = "qq-group-digest"

# 跟 exe 放在一起、给用户看的文件
EXTRA_FILES = ["config.example.json", "README.md", "README.zh-CN.md", "LICENSE"]
EXTRA_DIRS = ["examples", "docs"]

# exe 里打包进去的第三方组件（写进 THIRD-PARTY-NOTICES.txt）
BUNDLED = ["pywebview", "pythonnet", "clr_loader", "proxy_tools", "bottle", "typing_extensions", "cffi", "pycparser"]

# 用不到的大模块，排除掉让包更小
EXCLUDES = ["tkinter", "unittest", "pydoc_data", "test", "lib2to3", "idlelib"]


def version():
    sys.path.insert(0, str(ROOT))
    import app
    return app.VERSION


def run_pyinstaller():
    import PyInstaller.__main__
    PyInstaller.__main__.run([
        str(ROOT / "desktop.py"),
        "--name", NAME,
        "--onedir",
        "--windowed",           # 不弹黑色控制台窗口
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST),
        "--workpath", str(WORK),
        "--specpath", str(WORK),
        "--add-data", f"{ROOT / 'ui'}{os.pathsep}ui",
        *[arg for module in EXCLUDES for arg in ("--exclude-module", module)],
    ])


def license_text(name):
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    files = [f for f in (dist.files or []) if Path(str(f)).name.upper().startswith(("LICENSE", "COPYING"))]
    texts = [Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace").strip() for f in files]
    header = f"{name} {dist.version}  ({dist.metadata.get('License-Expression') or dist.metadata.get('License') or ''})"
    return header.strip() + "\n\n" + ("\n\n".join(texts) if texts else "（未附带许可证文件，见该项目主页）")


def write_notices(target):
    parts = [
        "本程序（exe 版）打包了以下第三方组件，它们各自遵循自己的许可证。\n"
        "This build bundles the following third-party components under their own licenses.",
    ]
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        parts.append(f"Python {sys.version.split()[0]}\n\n" + python_license.read_text(encoding="utf-8", errors="replace").strip())
    for name in BUNDLED:
        text = license_text(name)
        if text:
            parts.append(text)
    parts.append("PyInstaller bootloader\n\n"
                 "The exe launcher is produced by PyInstaller (GPL-2.0-or-later with the bootloader exception, "
                 "which permits distributing the resulting program under any license). https://pyinstaller.org")
    parts.append("Microsoft Edge WebView2\n\n"
                 "The window uses the Microsoft Edge WebView2 Runtime installed on Windows, and pywebview ships "
                 "Microsoft's WebView2 SDK assemblies under Microsoft's license. https://aka.ms/webview2")
    target.write_text(("\n\n" + "=" * 72 + "\n\n").join(parts) + "\n", encoding="utf-8")


def copy_extras(app_dir):
    for name in EXTRA_FILES:
        shutil.copy2(ROOT / name, app_dir / name)
    for name in EXTRA_DIRS:
        shutil.copytree(ROOT / name, app_dir / name, dirs_exist_ok=True)
    write_notices(app_dir / "THIRD-PARTY-NOTICES.txt")


def make_zip(app_dir, ver):
    archive = DIST / f"{NAME}-v{ver}-windows.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(app_dir.rglob("*")):
            if path.is_file():
                zf.write(path, Path(NAME) / path.relative_to(app_dir))
    return archive


def main():
    if os.name != "nt":
        print("exe 只能在 Windows 上打包。", file=sys.stderr)
        return 1
    try:
        import PyInstaller  # noqa: F401
        import webview  # noqa: F401
    except ImportError as e:
        print(f"缺少打包工具：{e.name}。请先运行：python -m pip install pywebview pyinstaller", file=sys.stderr)
        return 1
    ver = version()
    run_pyinstaller()
    app_dir = DIST / NAME
    leftovers = [p.name for p in app_dir.iterdir() if p.name in ("config.json", "state.json", "reports", "raw")]
    if leftovers:
        print(f"打包目录里出现了个人数据：{leftovers}，已停止。", file=sys.stderr)
        return 1
    copy_extras(app_dir)
    archive = make_zip(app_dir, ver)
    size = archive.stat().st_size / 1024 / 1024
    print(f"\n完成：{app_dir}\n压缩包：{archive}（{size:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
