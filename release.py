#!/usr/bin/env python3
"""Build a local Xiaohongshu offline ZIP and a separate release form (Python 3.9+)."""
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
AUDIT = ROOT / ".codex/skills/minitool-zip-builder/scripts/audit_artifact.py"
MIB = 1024 * 1024
SUFFIXES = set(".html .css .js .png .jpg .jpeg .gif .webp .svg .woff .woff2 .json".split())
PERMISSIONS = ["相册照片与视频", "设备摄像头", "设备麦克风", "设备位置", "用户头像和昵称"]
ABILITIES = ["AI 对话能力", "排行榜"]
SCENES = "生活方式 休闲玩法 图像创作 学习知识 实用工具 娱乐测试 其他".split()
FIELDS = set("name intro version scene permissions abilities mode price paid_content tip tip_message icon cover".split())
MISSING = "待填写"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_text(path):
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"{path.name} 不是 UTF-8 编码，请转码后重新构建") from None


def static_ref(base, raw, files, image=False):
    ref = raw.strip()
    if not ref or ref.startswith("#"):
        return
    if image and (ref.lower().startswith("data:image/") or ref.lower().startswith("blob:")):
        return
    url = urlsplit(ref)
    path = unquote(url.path)
    require(not url.scheme and not url.netloc and not path.startswith("/") and "\\" not in path,
            f"{base.name} 引用了非包内路径 {ref[:100]}")
    if path:
        require((base.parent / path).resolve() in files, f"{base.name} 资源缺失或越界 {path[:100]}")


def css_refs(text, path, files):
    for match in re.finditer(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", text, re.I | re.S):
        static_ref(path, match[2], files, image=True)
    for match in re.finditer(r"""@import\s*['"]([^'"]+)['"]""", text, re.I):
        static_ref(path, match[1], files)


class Entry(HTMLParser):
    def __init__(self, path, files):
        super().__init__()
        self.path, self.files = path, files
        self.in_style = False

    def handle_starttag(self, tag, pairs):
        attrs = {key: value or "" for key, value in pairs}
        require(tag not in {"base", "iframe", "object", "embed"}, f"入口不支持 <{tag}>")
        require(not any(k.startswith("on") for k in attrs), "入口含行内事件，改用外置 JS")
        require(attrs.get("target", "").lower() != "_blank", "入口含新窗口链接")
        if tag == "script":
            typ = attrs.get("type", "").lower().strip()
            require(bool(attrs.get("src")) and typ in {"", "text/javascript", "application/javascript"},
                    "入口使用了内联脚本、数据脚本或模块脚本，请依开发规范调整")
        if tag == "meta":
            require(attrs.get("http-equiv", "").lower() not in {"content-security-policy", "refresh"},
                    "入口含自定义 CSP 或刷新跳转")
        for key in ("src", "href", "poster"):
            if key in attrs:
                static_ref(self.path, attrs[key], self.files, image=(tag == "img" or key == "poster"))
        if "style" in attrs:
            css_refs(attrs["style"], self.path, self.files)
        if tag == "style":
            self.in_style = True

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            css_refs(data, self.path, self.files)


def check_tree(source):
    require(source.is_dir() and (source / "index.html").is_file(), "构建目录根部必须有 index.html")
    files, names, warnings = set(), set(), []
    for p in source.rglob("*"):
        if p.name == ".DS_Store":  # Finder recreates it on every visit; leave it out of the package
            continue
        rel = p.relative_to(source)
        require(not p.is_symlink(), f"构建目录含软链接 {rel}")
        require(not any(x.startswith(".") or x in {"__MACOSX", "node_modules"} for x in rel.parts),
                f"请从构建目录移除 {rel}")
        if p.is_dir():
            continue
        require(stat.S_ISREG(p.stat().st_mode) and p.suffix.lower() in SUFFIXES, f"不支持的文件 {rel}")
        require(not re.match(r"(vite|webpack|rollup|babel)\.config\.", p.name), f"构建目录含配置 {rel}")
        require(p.suffix.lower() != ".html" or rel.as_posix() == "index.html", f"额外 HTML 入口 {rel}")
        require(not any(c in str(rel) for c in ("\\", ":")) and not any(ord(c) < 32 for c in str(rel)), f"异常路径 {rel}")
        key = unicodedata.normalize("NFC", rel.as_posix()).casefold()
        require(key not in names, f"路径大小写或字符归一化冲突 {rel}")
        names.add(key)
        files.add(p)
    require(sum(p.stat().st_size for p in files) <= 30 * MIB, "解压后合计超过 30 MiB")
    entry = source / "index.html"
    parser = Entry(entry, files)
    parser.feed(read_text(entry))
    parser.close()
    for p in sorted(files):
        if p.suffix.lower() not in {".html", ".css", ".js", ".json", ".svg"}:
            continue
        body = read_text(p)
        if p.suffix.lower() == ".css":
            css_refs(body, p, files)
        for match in re.finditer(r"data:[^,\s]{0,200};base64,([A-Za-z0-9+/]+)(={0,2})", body, re.I):
            size = (len(match[1]) * 6) // 8
            require(size <= MIB, f"{p.name} 包含超过 1 MiB 的 Base64，请使用独立资源")
            if size > 100 * 1024:
                warnings.append(f"WARN: {p.name} 的 Base64 超过 100 KiB，建议使用包内文件")
    return sorted(files), warnings


def image_info(path):
    with path.open("rb") as f:
        header = f.read(24)
        if header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR":
            require(path.suffix.lower() == ".png", "PNG 文件扩展名不匹配")
            return struct.unpack(">II", header[16:24])
        require(header[:2] == b"\xff\xd8" and path.suffix.lower() in {".jpg", ".jpeg"}, "需要 PNG 或 JPEG 图片")
        f.seek(2)
        while f.read(1) == b"\xff":
            tag = f.read(1)
            while tag == b"\xff":
                tag = f.read(1)
            if tag in (b"", b"\xda", b"\xd9"):
                break
            length = int.from_bytes(f.read(2), "big")
            require(length >= 2, "JPEG 段损坏")
            if tag[0] in (192, 193, 194, 195, 197, 198, 199, 201, 202, 203, 205, 206, 207):
                _, height, width = struct.unpack(">BHH", f.read(5))
                return width, height
            f.seek(length - 2, 1)
    raise ValueError("无法读取图片尺寸")


def utf16_length(value):
    return len(value.encode("utf-16-le")) // 2


def prepare_form(config, stage):
    data = json.loads(config.read_text(encoding="utf-8")) if config else {}
    require(isinstance(data, dict) and set(data) <= FIELDS, "release.json 存在未知字段或不是对象")
    def field(key, limit=None):
        v = data.get(key)
        if v is None:
            return MISSING
        require(isinstance(v, str) and v.strip() and not any(ord(c) < 32 for c in v), f"{key} 需要非空单行文字")
        length = utf16_length(v)
        require(not limit or length <= limit, f"{key} 长度 {length}，上限 {limit}")
        return v

    name, intro, version = field("name", 14), field("intro", 14), field("version")
    if version != MISSING:
        require(re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}", version), "版本号须为三段数字")
    selections = {}
    for key, choices in (("permissions", PERMISSIONS), ("abilities", ABILITIES)):
        v = data.get(key)
        require(v is None or isinstance(v, list) and all(x in choices for x in v), f"{key} 有未知选项")
        selections[key] = v
    perms, abilities = selections["permissions"], selections["abilities"]
    if abilities and "排行榜" in abilities:
        require(perms and "用户头像和昵称" in perms, "排行榜需要「用户头像和昵称」权限")
    scene, mode = field("scene"), field("mode")
    require(scene in [MISSING] + SCENES and mode in {MISSING, "免费", "付费"}, "场景标签或付费模式无效")
    price, content = data.get("price"), field("paid_content")
    require(mode == "付费" or data.get("paid_content") is None, "paid_content 只属于付费工具，其他情况请留 null")
    if price is not None:
        from decimal import Decimal
        require(mode == "付费" and re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", str(price)) and Decimal(str(price)) > 0,
                "定价须属于付费工具且为正数（元，最多两位小数）")
    tip, message = data.get("tip"), field("tip_message", 15)
    require(tip is None or type(tip) is bool, "tip 必须是 true、false 或 null")
    art = {}
    for key, ratio, limit in (("icon", (1, 1), 5), ("cover", (3, 4), 10)):
        art[key] = "待提供"
        if data.get(key) is None:
            continue
        require(isinstance(data[key], str) and data[key].strip(), f"{key} 路径无效")
        source = (config.parent / data[key]).resolve()
        require(source.is_file() and 0 < source.stat().st_size <= limit * MIB, f"{key} 缺失或超过 {limit} MiB")
        try:
            width, height = image_info(source)
        except (ValueError, struct.error) as exc:
            raise ValueError(f"{key} 图片无效：{exc}") from None
        require(width > 0 and height > 0 and width * ratio[1] == height * ratio[0], f"{key} 尺寸 {width}×{height}，需 {ratio[0]}:{ratio[1]}")
        target = stage / (key + source.suffix.lower())
        shutil.copyfile(source, target)
        art[key] = f"{target.name}（{width}×{height}，{target.stat().st_size:,} 字节）"
    def selection(values, empty):
        return MISSING if values is None else "、".join(values) or empty
    return [("代码包", "game.zip"), ("让 Agent 帮我管理", "手动交付时无需勾选"), ("版本号", version),
            ("所需权限", selection(perms, "不需要权限")), ("高级能力", selection(abilities, "不勾选")),
            ("小工具名称", name), ("简介", intro), ("图标", art["icon"]), ("封面", art["cover"]),
            ("场景标签", scene), ("付费设置", mode),
            ("价格", "待定价" if mode == "付费" and price is None else str(price) + " 元" if price is not None else "—"),
            ("付费内容", content if mode == "付费" else "—"),
            ("赞赏设置", MISSING if tip is None else ("开启" if tip else "关闭")),
            ("赞赏留言", message if tip else "—"), ("发布安全规范", "作者阅读并确认")]


def audit(path):
    result = subprocess.run([sys.executable, str(AUDIT), str(path)], capture_output=True, text=True)
    report = (result.stdout + result.stderr).strip()
    require(result.returncode == 0, report or "官方审计失败")
    return report


def build(src, out, config):
    source, output = src.resolve(), out.absolute()
    require(not output.exists() and not output.is_symlink(), "交付目录已存在，请使用新路径")
    require(not output.resolve().is_relative_to(source), "交付目录必须在游戏构建目录之外")
    files, warnings = check_tree(source)
    before = audit(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        stage = Path(temp) / "release"
        stage.mkdir()
        rows = prepare_form(config, stage)
        pack = stage / "game.zip"
        # Clamp pre-1980 mtimes (reproducible builds, unpacked archives) instead of aborting.
        with ZipFile(pack, "x", ZIP_DEFLATED, strict_timestamps=False) as z:
            for f in files:
                z.write(f, f.relative_to(source).as_posix())
        with ZipFile(pack) as z:
            require(z.testzip() is None and "index.html" in z.namelist(), "ZIP 结构或 CRC 异常")
        after = audit(pack)
        digest = hashlib.sha256(pack.read_bytes()).hexdigest()
        summary = (f"文件数 {len(files)}，ZIP {pack.stat().st_size:,} 字节\nSHA-256 {digest}\n"
                   + "".join(line + "\n" for line in warnings) +
                   f"官方目录审计\n{before}\n官方 ZIP 审计\n{after}\n"
                   "已检查根入口、常见静态 HTML/CSS 引用、图片表单规格（如提供）与 ZIP 完整性。\n"
                   "动态资源、业务逻辑和 SDK 调用需结合源码核对。创服模拟器、Android、iOS 待实测，核对首屏标题和按钮是否避开状态栏与右上角胶囊。\n")
        (stage / "校验摘要.txt").write_text(summary, encoding="utf-8")
        lines = ["# 小红书发布填写单", "", "| 后台字段 | 填写内容 |", "| --- | --- |"]
        for label, value in rows:
            lines.append("| " + label + " | " + value.replace("|", "\\|") + " |")
        (stage / "发布填写单.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.rename(stage, output)
    print(summary + str(output / "game.zip") + "\n" + str(output / "发布填写单.md"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--form", type=Path)
    args = parser.parse_args()
    try:
        build(args.dist, args.output, args.form)
    except (OSError, ValueError, struct.error) as exc:
        sys.exit(f"校验失败：{exc}")
