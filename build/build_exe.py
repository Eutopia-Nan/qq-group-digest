"""
打包脚本：PyInstaller 文件夹模式 → dist/qq-group-digest/ → dist/qq-group-digest-v<版本>-windows.zip

只在打包的电脑上需要 pywebview 和 PyInstaller，用户拿到的 exe 不需要安装任何东西：
    python -m venv .venv
    .venv\\Scripts\\python -m pip install pywebview pyinstaller
    .venv\\Scripts\\python build\\build_exe.py

防止把个人数据打进发布包：
- 只打包 git 已跟踪的文件（ui/、docs/、examples/ 里没提交的文件一律不带）
- 旧的输出目录里出现上次打包之外的文件（比如有人在里面试用后留下的 config.json）时停止，不删除
- 生成压缩包前再扫描一遍，发现配置、进度、报告或聊天记录就停止
许可证说明根据 PyInstaller 实际打包的模块自动生成，缺少许可证正文时停止。
"""

import ast
import importlib.metadata as metadata
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORK = ROOT / "build" / "pyinstaller"
STAGE = WORK / "stage"
MANIFEST = WORK / "last-build-files.txt"   # 上次打包产生的文件清单，用来判断输出目录里有没有别人放进去的文件
LICENSE_OVERRIDES = ROOT / "build" / "licenses"
NAME = "qq-group-digest"
APP_DIR = DIST / NAME

# 跟 exe 放在一起、给用户看的文件（必须是 git 已跟踪的文件）
EXTRA_FILES = ["config.example.json", "README.md", "README.zh-CN.md", "LICENSE"]
EXTRA_DIRS = ["examples", "docs"]

# 界面窗口用不到的模块。setuptools / packaging 只是被依赖分析顺带拉进来的，排除后包更小，也少一批许可证
EXCLUDES = ["tkinter", "unittest", "pydoc_data", "test", "lib2to3", "idlelib",
            "setuptools", "pkg_resources", "packaging"]

# 个人数据：出现在发布包里就停止
PERSONAL_NAMES = {"config.json", "state.json", "state.lock"}
PERSONAL_DIRS = {"reports", "raw", "QQ聊天记录导出"}
ALLOWED_DATA = {"examples/study.csv"}


class BuildError(Exception):
    pass


def version():
    sys.path.insert(0, str(ROOT))
    import app
    return app.VERSION


# ---------------------------------------------------------------- 文件来源和个人数据检查

def tracked(*paths):
    """git 已跟踪的文件（相对 ROOT 的路径）。"""
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--", *paths], cwd=ROOT,
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise BuildError(f"需要在 git 仓库里打包，以便只打包已提交的文件：{e}") from None
    files = [p for p in out.decode("utf-8").split("\0") if p]
    missing = [p for p in files if not (ROOT / p).is_file()]
    if missing:
        raise BuildError(f"这些已跟踪的文件在磁盘上不存在：{missing}")
    return files


def personal_files(folder):
    """folder 里看起来像个人数据的文件或文件夹（相对路径）。"""
    found = []
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if rel in ALLOWED_DATA:
            continue
        if path.is_dir():
            if path.name in PERSONAL_DIRS:
                found.append(rel + "/")
        elif (path.name in PERSONAL_NAMES or path.suffix.lower() in (".csv", ".part")
              or (path.suffix.lower() in (".md", ".txt") and any(part in PERSONAL_DIRS for part in path.parts))):
            found.append(rel)
    return found


def check_old_output():
    """PyInstaller 会删除旧的输出目录：先确认里面只有上次打包产生的文件。"""
    if not APP_DIR.exists():
        return
    current = {p.relative_to(APP_DIR).as_posix() for p in APP_DIR.rglob("*") if p.is_file()}
    known = set(MANIFEST.read_text(encoding="utf-8").splitlines()) if MANIFEST.exists() else set()
    unknown = sorted(current - known)
    if unknown:
        shown = "\n".join(f"  - {p}" for p in unknown[:20]) + ("\n  ..." if len(unknown) > 20 else "")
        raise BuildError(f"{APP_DIR} 里有不是上次打包产生的文件，为避免删掉你的数据，已停止：\n{shown}\n"
                         "请把需要的文件移走，再删除这个文件夹后重新打包。")


def stage_ui():
    """只把已提交的界面文件放进暂存目录，再交给 PyInstaller。"""
    shutil.rmtree(STAGE, ignore_errors=True)
    for rel in tracked("ui"):
        target = STAGE / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    return STAGE / "ui"


def run_pyinstaller(ui_dir):
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
        "--add-data", f"{ui_dir}{os.pathsep}ui",
        *[arg for module in EXCLUDES for arg in ("--exclude-module", module)],
    ])


def copy_extras():
    for rel in tracked(*EXTRA_FILES, *EXTRA_DIRS):
        target = APP_DIR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)


# ---------------------------------------------------------------- 第三方许可证

def _toc_entries(obj):
    """PyInstaller 的 .toc 文件是嵌套的元组/列表，找出 (名字, ...) 这一层。"""
    if isinstance(obj, list) and obj and isinstance(obj[0], tuple) and obj[0] and isinstance(obj[0][0], str):
        return obj
    if isinstance(obj, (list, tuple)):
        for item in obj:
            found = _toc_entries(item)
            if found:
                return found
    return []


def bundled_distributions():
    """PyInstaller 实际打包进去的第三方包（按 PYZ 和 COLLECT 清单反查）。"""
    names = set()
    for toc in ("PYZ-00.toc", "COLLECT-00.toc"):
        path = WORK / NAME / toc
        if not path.exists():
            raise BuildError(f"找不到 PyInstaller 的清单 {path}，无法确认打包了哪些第三方组件。")
        for entry in _toc_entries(ast.literal_eval(path.read_text(encoding="utf-8"))):
            names.add(entry[0].replace("\\", "/").split("/")[0].split(".")[0])
    mapping = metadata.packages_distributions()
    return sorted({dist for name in names for dist in mapping.get(name, [])}, key=str.lower)


def license_text(dist_name):
    override = LICENSE_OVERRIDES / f"{dist_name}.txt"
    if override.exists():
        return override.read_text(encoding="utf-8").strip()
    dist = metadata.distribution(dist_name)
    files = [f for f in (dist.files or []) if Path(str(f)).name.upper().startswith(("LICENSE", "COPYING", "NOTICE"))]
    texts = [Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace").strip() for f in files]
    if not texts:
        raise BuildError(f"{dist_name} {dist.version} 没有附带许可证正文。请核对上游许可证后放到 "
                         f"build/licenses/{dist_name}.txt 再打包。")
    licence = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
    header = f"{dist_name} {dist.version}" + (f"  ({licence.splitlines()[0]})" if licence else "")
    return header + "\n\n" + "\n\n".join(texts)


def write_notices():
    parts = ["本程序（exe 版）打包了以下第三方组件，它们各自遵循自己的许可证。\n"
             "This build bundles the following third-party components under their own licenses."]
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.exists():
        raise BuildError(f"找不到 Python 的许可证文件 {python_license}。")
    parts.append(f"Python {sys.version.split()[0]}\n\n" + python_license.read_text(encoding="utf-8", errors="replace").strip())
    dists = bundled_distributions()
    parts.extend(license_text(name) for name in dists)
    parts.append("PyInstaller bootloader\n\n"
                 "The exe launcher is produced by PyInstaller (GPL-2.0-or-later with the bootloader exception, "
                 "which permits distributing the resulting program under any license). https://pyinstaller.org")
    parts.append("Microsoft Edge WebView2\n\n"
                 "The window uses the Microsoft Edge WebView2 Runtime installed on Windows. pywebview ships the "
                 "WebView2 SDK assemblies (Microsoft.Web.WebView2.Core.dll, Microsoft.Web.WebView2.WinForms.dll, "
                 "WebView2Loader.dll), which are distributed under the Microsoft WebView2 SDK license: "
                 "https://www.nuget.org/packages/Microsoft.Web.WebView2")
    (APP_DIR / "THIRD-PARTY-NOTICES.txt").write_text(("\n\n" + "=" * 72 + "\n\n").join(parts) + "\n", encoding="utf-8")
    return dists


# ---------------------------------------------------------------- 压缩包

def make_zip(ver):
    archive = DIST / f"{NAME}-v{ver}-windows.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(APP_DIR.rglob("*")):
            if path.is_file():
                zf.write(path, Path(NAME) / path.relative_to(APP_DIR))
    return archive


def build():
    ver = version()
    check_old_output()
    ui_dir = stage_ui()
    run_pyinstaller(ui_dir)
    copy_extras()
    dists = write_notices()
    found = personal_files(APP_DIR)
    if found:
        raise BuildError("发布包里出现了疑似个人数据，已停止，没有生成压缩包：\n" + "\n".join(f"  - {p}" for p in found))
    MANIFEST.write_text("\n".join(sorted(p.relative_to(APP_DIR).as_posix()
                                         for p in APP_DIR.rglob("*") if p.is_file())), encoding="utf-8")
    archive = make_zip(ver)
    print(f"\n完成：{APP_DIR}\n压缩包：{archive}（{archive.stat().st_size / 1024 / 1024:.1f} MB）\n"
          f"打包的第三方组件：{', '.join(dists)}")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if os.name != "nt":
        print("exe 只能在 Windows 上打包。", file=sys.stderr)
        return 1
    try:
        import PyInstaller  # noqa: F401
        import webview  # noqa: F401
    except ImportError as e:
        print(f"缺少打包工具：{e.name}。请先运行：python -m pip install pywebview pyinstaller", file=sys.stderr)
        return 1
    try:
        build()
    except BuildError as e:
        print(f"\n[打包停止] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
