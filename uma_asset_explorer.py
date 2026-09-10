from __future__ import annotations

import argparse
from collections import OrderedDict
import gzip
import io
import json
import math
import os
import queue
import re
import struct
import sys
import threading
from dataclasses import dataclass
from functools import cached_property
from game_location import discover_folders, normalize_folder, remember_folder
try:
    import numpy as np
except ImportError:
    np = None
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "PartyDash Viewer 1.0.0"
PROBE_SIZE = 4096
PROBE_DECODE_SIZE = 512
MAX_PREVIEW_BYTES = 128 * 1024 * 1024
MAX_PACKAGE_TABLE = 8 * 1024 * 1024
MAX_PACKAGE_DEPTH = 5
MAX_DISCOVERED_PER_FILE = 25_000
MAX_VISIBLE_ROWS = 500
PREVIEW_DEBOUNCE_MS = 130
PREVIEW_CACHE_BYTES = 96 * 1024 * 1024

CATEGORY_ORDER = {
    name: index
    for index, name in enumerate(
        ("Personagens", "Backgrounds", "UI", "Sprites", "Texturas", "Paletas", "Efeitos", "Animações", "Modelos", "Áudio", "Vídeos", "Fontes", "Dados", "Pacotes", "Desconhecidos")
    )
}

BG = "#0d1117"
PANEL = "#151b23"
PANEL_2 = "#1b2330"
LINE = "#293241"
TEXT = "#e8edf4"
MUTED = "#8f9bab"
ACCENT = "#66d9a8"

FALLBACK_XOR_KEY = bytes.fromhex(
    "B9 38 4F AB 83 9E F8 8D D6 7F 33 EC E3 F3 D7 3D "
    "5D CC 46 D7 CB B8 4E 5A 4A 15 FC D9 B3 A2 9A 4B "
    "3A E2 75 91 0E 85 85 73 CD 71 C8"
)


@dataclass(frozen=True)
class Signature:
    label: str
    magic: bytes
    category: str
    extension: str


SIGNATURES = (
    Signature("JSON", b"\xef\xbb\xbf{", "Dados", ".json"),
    Signature("JSON", b"{\r\n", "Dados", ".json"),
    Signature("JSON", b"{\n", "Dados", ".json"),
    Signature("JSON", b'{"', "Dados", ".json"),
    Signature("JSON", b"[", "Dados", ".json"),
    Signature("UTF-16", b"\xff\xfe", "Dados", ".txt"),
    Signature("PNG", b"\x89PNG\r\n\x1a\n", "Texturas", ".png"),
    Signature("JPEG", b"\xff\xd8\xff", "Texturas", ".jpg"),
    Signature("DDS", b"DDS ", "Texturas", ".dds"),
    Signature("HIP", b"HIP\x00", "Sprites", ".hip"),
    Signature("HPL", b"HPAL", "Paletas", ".hpl"),
    Signature("WebM", b"\x1a\x45\xdf\xa3", "Vídeos", ".webm"),
    Signature("Ogg", b"OggS", "Áudio", ".ogg"),
    Signature("FLAC", b"fLaC", "Áudio", ".flac"),
    Signature("RIFF", b"RIFF", "Áudio", ".wav"),
    Signature("ASW", b" WSA", "Áudio", ".asw"),
    Signature("FPAC", b"FPAC", "Pacotes", ".pac"),
    Signature("ZIP", b"PK\x03\x04", "Pacotes", ".zip"),
    Signature("GZIP", b"\x1f\x8b", "Pacotes", ".gz"),
    Signature("LZ4", b"\x04\x22\x4d\x18", "Pacotes", ".lz4"),
    Signature("UnityFS", b"UnityFS", "Pacotes", ".unityfs"),
    Signature("TTF", b"\x00\x01\x00\x00", "Fontes", ".ttf"),
    Signature("OTF", b"OTTO", "Fontes", ".otf"),
)

STRUCTURED_SIGNATURE = Signature("Dados 2D", b"", "Dados", ".dat")

EXTENSION_SIGNATURES = {
    ".hip": Signature("HIP", b"", "Sprites", ".hip"),
    ".hpl": Signature("HPL", b"", "Paletas", ".hpl"),
    ".dds": Signature("DDS", b"", "Texturas", ".dds"),
    ".png": Signature("PNG", b"", "Texturas", ".png"),
    ".jpg": Signature("JPEG", b"", "Texturas", ".jpg"),
    ".jpeg": Signature("JPEG", b"", "Texturas", ".jpg"),
    ".pac": Signature("PAC", b"", "Pacotes", ".pac"),
    ".json": Signature("JSON", b"", "Dados", ".json"),
    ".txt": Signature("Texto", b"", "Dados", ".txt"),
    ".csv": Signature("CSV", b"", "Dados", ".csv"),
    ".xml": Signature("XML", b"", "Dados", ".xml"),
    ".webm": Signature("WebM", b"", "Vídeos", ".webm"),
    ".ogg": Signature("Ogg", b"", "Áudio", ".ogg"),
    ".wav": Signature("WAV", b"", "Áudio", ".wav"),
    ".mot": Signature("Motion", b"", "Animações", ".mot"),
    ".mmot": Signature("MMOT", b"", "Animações", ".mmot"),
    ".efp": Signature("Efeito", b"", "Efeitos", ".efp"),
    ".evb": Signature("Eventos EVB", b"", "Dados", ".evb"),
    ".atf": Signature("Texto ATF", b"", "Dados", ".atf"),
    ".bin": Signature("Dados binários", b"", "Dados", ".bin"),
    ".lst": Signature("Lista", b"", "Dados", ".lst"),
    ".mua": Signature("MUA", b"", "Dados", ".mua"),
    ".bdb": Signature("Banco BDB", b"", "Dados", ".bdb"),
    ".jonbin": Signature("JONBIN", b"", "Dados", ".jonbin"),
    ".abc": Signature("Dados ABC", b"", "Dados", ".abc"),
    ".fod": Signature("Dados FOD", b"", "Dados", ".fod"),
    ".mrd": Signature("Dados MRD", b"", "Dados", ".mrd"),
    ".xsb": Signature("XACT Sound Bank", b"", "Áudio", ".xsb"),
    ".xwb": Signature("XACT Wave Bank", b"", "Áudio", ".xwb"),
    ".xgs": Signature("XACT Settings", b"", "Áudio", ".xgs"),
}


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def safe_relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def locate_game_exe(folder: Path) -> Optional[Path]:
    for candidate in (folder / "Uma Party Dash.exe", folder.parent / "Uma Party Dash.exe"):
        if candidate.is_file():
            return candidate
    return None


def derive_key_candidates(exe_path: Optional[Path]) -> list[tuple[str, bytes]]:
    result = [("PartyDash", FALLBACK_XOR_KEY)]
    if exe_path is None:
        return result
    try:
        data = exe_path.read_bytes()
    except OSError:
        return result
    seen = {FALLBACK_XOR_KEY}
    start = 0
    while True:
        pos = data.find(b"asset/", start)
        if pos < 0:
            break
        start = pos + 1
        gap = 1 if pos > 0 and data[pos - 1] == 0 else 0
        begin = pos - gap - 43
        if begin < 0:
            continue
        candidate = data[begin : pos - gap]
        if len(candidate) != 43 or candidate in seen:
            continue
        if sum(byte < 32 or byte > 126 for byte in candidate) < 12:
            continue
        seen.add(candidate)
        result.append((f"EXE@0x{begin:X}", candidate))
        if len(result) >= 4:
            break
    return result


def xor_transform(data: bytes, key: bytes, start: int) -> bytes:
    key_len = len(key)
    if np is not None and len(data) >= 256:
        offset = start % key_len
        rotated = key[offset:] + key[:offset]
        mask = (rotated * ((len(data)+key_len-1)//key_len))[:len(data)]
        return np.bitwise_xor(np.frombuffer(data,dtype=np.uint8),np.frombuffer(mask,dtype=np.uint8)).tobytes()
    return bytes(value ^ key[(start + index) % key_len] for index, value in enumerate(data))


def signature_is_plausible(data: bytes, signature: Signature, offset: int) -> bool:
    remaining = data[offset:]
    label = signature.label
    if label == "DDS":
        if len(remaining) < 20:
            return False
        header_size = struct.unpack_from("<I", remaining, 4)[0]
        height, width = struct.unpack_from("<II", remaining, 12)
        return header_size == 124 and 1 <= width <= 32768 and 1 <= height <= 32768
    if label == "FPAC":
        if len(remaining) < 24:
            return False
        base_offset, total_size, files = struct.unpack_from("<III", remaining, 4)
        name_len = struct.unpack_from("<I", remaining, 20)[0]
        return 0x20 <= base_offset < 0x1000000 and base_offset <= total_size < 0x80000000 and files < 100000 and 0 < name_len <= 1024
    if label == "HIP":
        if len(remaining) < 32:
            return False
        palette_size, width, height = struct.unpack_from("<III", remaining, 12)
        return palette_size <= 65536 and 1 <= width <= 32768 and 1 <= height <= 32768 and remaining[24] in (1, 4, 16)
    if label == "HPL":
        return len(remaining) >= 32 and 0 < struct.unpack_from("<I", remaining, 12)[0] <= 65536
    if label == "JSON":
        if offset > 3:
            return False
        preview = remaining[:160]
        if preview.startswith(b"\xef\xbb\xbf"):
            preview = preview[3:]
        try:
            text = preview.decode("utf-8")
        except UnicodeDecodeError:
            return False
        stripped = text.lstrip()
        return bool(stripped) and stripped[0] in "[{" and any(mark in stripped for mark in ('"', "{", "}"))
    if label == "UTF-16":
        return offset == 0 and len(remaining) >= 4
    if label in {"ASW", "TTF", "OTF"}:
        return offset == 0
    return True


def find_signature(data: bytes, max_offset: Optional[int] = None) -> Optional[tuple[Signature, int]]:
    best = None
    for signature in SIGNATURES:
        if not signature.magic:
            continue
        offset = data.find(signature.magic)
        if offset < 0 or (max_offset is not None and offset > max_offset):
            continue
        if not signature_is_plausible(data, signature, offset):
            continue
        if best is None or (offset, -len(signature.magic)) < (best[1], -len(best[0].magic)):
            best = (signature, offset)
    return best


@dataclass
class ProbeResult:
    signature: Optional[Signature]
    signature_offset: int = 0
    key_name: str = ""
    key: Optional[bytes] = None
    key_start: Optional[int] = None
    raw: bool = False
    confidence: str = "alta"


def structured_score(data: bytes) -> float:
    sample = data[:192]
    if len(sample) < 16:
        return 0
    score = sample.count(0) * 0.35
    score += sum((32 <= value < 127) or value in (9, 10, 13) for value in sample) * 0.08
    common = {0, 1, 2, 3, 4, 5, 8, 10, 12, 16, 24, 28, 32, 40, 48, 64, 80, 96, 128, 256, 512, 1024, 2048, 4096}
    for offset in range(0, min(64, len(sample) - 4), 4):
        if struct.unpack_from("<I", sample, offset)[0] in common:
            score += 1
    return score


def looks_like_structured_2d(data: bytes) -> bool:
    if len(data) < 32:
        return False
    first, second, third = struct.unpack_from("<III", data, 0)
    return first < 100000 and second == third and 0 < second < 100000 and data[:192].count(0) >= 12


def probe_bytes(data: bytes, keys: list[tuple[str, bytes]]) -> ProbeResult:
    direct = find_signature(data, 64)
    if direct:
        return ProbeResult(direct[0], direct[1], raw=True)
    sample = data[:PROBE_DECODE_SIZE]
    best = None
    structural = None
    for key_name, key in keys:
        for start in range(len(key)):
            decoded = xor_transform(sample, key, start)
            match = find_signature(decoded, 256)
            if match:
                signature, offset = match
                rank = (0 if offset == 0 else 1, offset, -len(signature.magic))
                if best is None or rank < best[0]:
                    best = (rank, signature, offset, key_name, key, start)
            score = structured_score(decoded)
            if structural is None or score > structural[0]:
                structural = (score, key_name, key, start, decoded)
    if best:
        _, signature, offset, key_name, key, start = best
        return ProbeResult(signature, offset, key_name, key, start)
    if structural:
        score, key_name, key, start, decoded = structural
        if score >= 15 and looks_like_structured_2d(decoded):
            return ProbeResult(STRUCTURED_SIGNATURE, 0, key_name, key, start, confidence="inferida")
    return ProbeResult(None)


def decode_name(raw: bytes) -> str:
    value = raw.split(b"\0", 1)[0]
    for encoding in ("utf-8", "cp932", "latin-1"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            pass
    return value.decode("latin-1", errors="replace")


def classify_asset(name: str, signature: Optional[Signature]) -> tuple[str, str]:
    name = re.sub(r'([a-z])([A-Z])', r'\1_\2', name)
    lowered = name.casefold().replace("\\", "/")
    suffix = Path(lowered).suffix
    tokens = set(filter(None, re.split(r"[^a-z0-9]+", lowered)))
    base_category = signature.category if signature else ("Dados" if suffix == ".bin" else "Desconhecidos")

    if suffix in {".mdl", ".mesh", ".vbn", ".mbn", ".obj", ".gltf", ".glb"}:
        return "Modelos", "extensão de modelo"
    if base_category not in {"Sprites", "Texturas", "Paletas"}:
        return base_category, "formato do arquivo"
    if base_category == "Paletas":
        return "Paletas", "paleta de cores HPL/HPAL"

    leaf_name = Path(lowered).name
    leaf_stem = re.sub(r"(?:\.[a-z0-9]+)+$", "", leaf_name)
    if re.fullmatch(r"[a-z]{2,12}\d{3}[a-z]?_\d{2}[lr]?", leaf_stem):
        return "Personagens", "padrão numérico de sprite de personagem"

    leaf = set(re.split(r'[^a-z0-9]+', Path(lowered).stem))
    if leaf & {
        'text', 'icon', 'icons', 'symbol', 'symbols', 'badge', 'logo', 'button', 'buttons',
        'header', 'gauge', 'font', 'fonts', 'menu', 'menus', 'cursor', 'guide', 'result',
        'title', 'select', 'frame', 'panel', 'window', 'hud', 'banner', 'card',
    } or ('char' in leaf and 'name' in leaf):
        return 'UI', 'elemento de interface no nome do arquivo'
    if any(re.fullmatch(r'npc\d+', t) for t in tokens):
        return 'Personagens', 'identificador NPC no nome'
    if 'lobbybg' in tokens:
        return 'Backgrounds', 'cenário do lobby'

    furniture_markers = {
        'furniture', 'chair', 'chairs', 'desk', 'desks', 'table', 'tables',
        'sofa', 'couch', 'bed', 'beds', 'shelf', 'shelves', 'cabinet',
        'locker', 'bench', 'stool', 'counter', 'wardrobe', 'dresser',
        'lamp', 'lamps', 'plant', 'plants', 'prop', 'props', 'decoration',
        'decorations', 'decor', 'fixture', 'fixtures',
    }
    surface_markers = {
        'tile', 'tiles', 'tiler', 'tilers', 'floor', 'floors', 'wall', 'walls',
        'ceiling', 'ceilings', 'ground', 'terrain', 'road', 'roads', 'path',
        'paths', 'roof', 'roofs', 'pavement', 'platform', 'platforms',
    }
    effect_markers = {
        'effect', 'effects', 'ef', 'vfx', 'particle', 'particles', 'aura',
        'smoke', 'flash', 'spark', 'sparks', 'glow', 'glows', 'flare',
        'flares', 'shine', 'impact', 'impacts', 'hit', 'slash', 'burst',
        'explosion', 'explosions', 'trail', 'trails', 'streak', 'streaks',
        'speedline', 'speedlines', 'dust', 'ring', 'rings', 'glare',
    }
    if tokens & furniture_markers:
        return base_category, 'móvel ou objeto de cenário no nome'
    if tokens & surface_markers:
        return base_category, 'tile, piso ou parede no nome'
    if tokens & effect_markers:
        return base_category, 'efeito visual no nome'

    marker_groups = (
        ("Backgrounds", {"background", "bg", "stage", "field", "floor", "sky", "map", "ground", "landscape", "room", "clubroom", "scene"}),
        ("Efeitos", {"effect", "effects", "ef", "vfx", "particle", "particles", "aura", "smoke", "flash"}),
        ("Personagens", {"ch", "char", "npc", "chara", "character", "characters", "face", "portrait", "portraits", "costume", "body", "avatar", "uma"}),
        ("UI", {"font", "text", "help", "tutorial", "header", "ui", "hud", "menu", "icon", "icons", "button", "buttons", "window", "banner", "logo", "cursor", "gauge", "result", "title", "select", "guide", "dialog", "frame"}),
    )
    for category, markers in marker_groups:
        matched = sorted(tokens & markers)
        if matched:
            return category, f"contexto do nome ({matched[0]})"
    return base_category, "formato visual sem contexto específico"


def semantic_category(name: str, signature: Optional[Signature]) -> str:
    return classify_asset(name, signature)[0]


@dataclass
class AssetItem:
    source_path: Path
    root: Path
    size: int
    probe: ProbeResult
    source_probe: ProbeResult
    source_offset: int = 0
    logical_path: str = ""
    embedded: bool = False
    depth: int = 0

    @cached_property
    def relative(self) -> str:
        return self.logical_path or safe_relpath(self.source_path, self.root)

    @property
    def display_name(self) -> str:
        return self.relative if not self.embedded else f"{'  ' * min(self.depth, 5)}↳ {Path(self.logical_path).name.strip()}"

    @property
    def signature(self) -> Optional[Signature]:
        return self.probe.signature

    @property
    def format_label(self) -> str:
        if self.signature:
            return self.signature.label
        suffix = Path(self.relative).suffix
        if suffix.lower() == ".bin":
            return "Dados binários"
        return suffix.upper().lstrip(".") if suffix else "BIN"

    @cached_property
    def category(self) -> str:
        return semantic_category(self.relative, self.signature)

    @cached_property
    def category_reason(self) -> str:
        return classify_asset(self.relative, self.signature)[1]

    @cached_property
    def search_blob(self) -> str:
        return f"{self.relative} {self.format_label} {self.category} {self.source_path.name}".casefold()

    @property
    def decoder_label(self) -> str:
        if self.embedded:
            return "interno FPAC"
        if self.probe.raw:
            return "direto"
        if self.probe.key:
            return f"XOR {self.probe.key_name} +{self.probe.key_start}"
        return "não identificado"

    @property
    def hint(self) -> str:
        if self.embedded:
            return f"offset 0x{self.source_offset:X}"
        if not self.signature:
            return "formato desconhecido"
        if self.probe.confidence != "alta":
            return f"identificação {self.probe.confidence}"
        return f"cabeçalho em 0x{self.probe.signature_offset:X}" if self.probe.signature_offset else self.format_label


def make_root_item(path: Path, root: Path, keys: list[tuple[str, bytes]]) -> AssetItem:
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            probe = probe_bytes(stream.read(PROBE_SIZE), keys)
    except OSError:
        size, probe = 0, ProbeResult(None)
    return AssetItem(path, root, size, probe, probe)


def read_source_slice(item: AssetItem, absolute_offset: int, size: int) -> bytes:
    with item.source_path.open("rb") as stream:
        stream.seek(absolute_offset)
        data = stream.read(max(0, size))
    probe = item.source_probe
    if probe.key and not probe.raw:
        start = ((probe.key_start or 0) + absolute_offset) % len(probe.key)
        data = xor_transform(data, probe.key, start)
    return data


def decoded_payload(item: AssetItem, limit: int = MAX_PREVIEW_BYTES) -> Optional[bytes]:
    if item.size > limit:
        return None
    try:
        data = read_source_slice(item, item.source_offset, item.size)
    except OSError:
        return None
    return data[item.probe.signature_offset :] if item.probe.signature_offset else data


def preview_payload(item: AssetItem) -> Optional[bytes]:
    full_formats = {"HIP", "HPL", "DDS", "PNG", "JPEG", "GZIP"}
    if item.format_label in full_formats:
        return decoded_payload(item)
    if item.size > MAX_PREVIEW_BYTES:
        return None
    try:
        data = read_source_slice(item, item.source_offset, min(item.size, 2 * 1024 * 1024))
    except OSError:
        return None
    return data[item.probe.signature_offset :] if item.probe.signature_offset else data


def child_probe(sample: bytes, name: str) -> ProbeResult:
    match = find_signature(sample, 32)
    if match:
        return ProbeResult(match[0], match[1], raw=True)
    inferred = EXTENSION_SIGNATURES.get(Path(name).suffix.lower())
    return ProbeResult(inferred, raw=True, confidence="extensão") if inferred else ProbeResult(None)


def probe_fpac_child(root_item: AssetItem, absolute: int, size: int, name: str) -> ProbeResult:
    suffix = Path(name).suffix.lower()
    inferred = EXTENSION_SIGNATURES.get(suffix)
    if inferred and suffix not in {".pac", ".bin"}:
        return ProbeResult(inferred, raw=True, confidence="extensão")
    try:
        sample = read_source_slice(root_item, absolute, min(PROBE_DECODE_SIZE, size))
    except OSError:
        return ProbeResult(inferred, raw=True, confidence="extensão") if inferred else ProbeResult(None)
    return child_probe(sample, name)


def discover_fpac_items(root_item: AssetItem) -> list[AssetItem]:
    if not root_item.signature or root_item.signature.label != "FPAC":
        return []
    result = []
    visited = set()
    start = root_item.source_offset + root_item.probe.signature_offset
    stack = [(start, root_item.size - root_item.probe.signature_offset, root_item.relative, 0)]
    source_size = root_item.source_path.stat().st_size
    while stack and len(result) < MAX_DISCOVERED_PER_FILE:
        absolute, available, prefix, depth = stack.pop()
        if depth >= MAX_PACKAGE_DEPTH or absolute in visited or available < 32:
            continue
        visited.add(absolute)
        try:
            header = read_source_slice(root_item, absolute, 32)
        except OSError:
            continue
        if not header.startswith(b"FPAC"):
            continue
        base_offset, _total_size, file_count = struct.unpack_from("<III", header, 4)
        name_len = struct.unpack_from("<I", header, 20)[0]
        stride = ((name_len + 12 + 15) // 16) * 16
        table_size = 32 + file_count * stride
        if not 0 < file_count < 100000 or not 0 < name_len <= 1024 or table_size > MAX_PACKAGE_TABLE or base_offset < table_size or base_offset > available + 0x1000:
            continue
        try:
            table = read_source_slice(root_item, absolute, table_size)
        except OSError:
            continue
        for index in range(file_count):
            entry = 32 + index * stride
            name_end = entry + name_len
            if name_end + 12 > len(table):
                break
            name = decode_name(table[entry:name_end]) or f"entry_{index:04d}.bin"
            _file_id, relative_offset, size = struct.unpack_from("<III", table, name_end)
            child_absolute = absolute + base_offset + relative_offset
            if size <= 0 or child_absolute + size > source_size:
                continue
            probe = probe_fpac_child(root_item, child_absolute, size, name)
            logical = f"{prefix}/{name.strip()}"
            child = AssetItem(root_item.source_path, root_item.root, size, probe, root_item.source_probe, child_absolute, logical, True, depth + 1)
            result.append(child)
            if probe.signature and probe.signature.label == "FPAC":
                stack.append((child_absolute + probe.signature_offset, size - probe.signature_offset, logical, depth + 1))
    return result


def dds_info(data: bytes) -> str:
    if len(data) < 20 or not data.startswith(b"DDS "):
        return ""
    height, width = struct.unpack_from("<II", data, 12)
    fourcc = data[84:88].decode("ascii", errors="replace").strip("\x00 ") if len(data) >= 88 else ""
    return f"{width}×{height}" + (f", {fourcc}" if fourcc and fourcc.isprintable() else "")


def fpac_info(data: bytes) -> str:
    if len(data) < 32 or not data.startswith(b"FPAC"):
        return ""
    base_offset, total_size, files = struct.unpack_from("<III", data, 4)
    name_len = struct.unpack_from("<I", data, 20)[0]
    return f"{files} entrada(s), nomes de {name_len} bytes, dados em 0x{base_offset:X}, tamanho declarado {human_size(total_size)}"


def hip_header(data: bytes) -> dict[str, int]:
    if len(data) < 32 or not data.startswith(b"HIP\0"):
        raise ValueError("Cabeçalho HIP inválido")
    version, file_size, palette_size, texture_w, texture_h = struct.unpack_from("<IIIII", data, 4)
    encoding, extra_size = data[24], struct.unpack_from("<I", data, 28)[0]
    width, height, x_offset, y_offset, cursor = texture_w, texture_h, 0, 0, 32
    if extra_size >= 16:
        if len(data) < 48:
            raise ValueError("HIP truncado")
        width, height, x_offset, y_offset = struct.unpack_from("<IIII", data, cursor)
        cursor += extra_size
    return {"version": version, "file_size": file_size, "palette_size": palette_size, "texture_w": texture_w, "texture_h": texture_h, "encoding": encoding, "width": width, "height": height, "x_offset": x_offset, "y_offset": y_offset, "data_offset": cursor}


def decode_hip_fast(data, meta):
    width,height=meta['width'],meta['height']
    count=width*height
    encoding=meta['encoding']
    stride={1:2,16:5,4:3}.get(encoding)
    if stride is None:
        raise ValueError(f'Codificação HIP não suportada: {encoding}')
    cursor=meta['data_offset']
    palette=None
    if encoding==1:
        end=cursor+meta['palette_size']*4
        if end>len(data) or meta['palette_size']==0:
            raise ValueError('Paleta HIP truncada')
        palette=np.frombuffer(data[cursor:end],dtype=np.uint8).reshape(-1,4)
        cursor=end
    available=(len(data)-cursor)//stride
    if available<=0:
        raise ValueError('RLE HIP truncado')
    records=np.frombuffer(data,dtype=np.uint8,count=available*stride,offset=cursor).reshape(-1,stride)
    runs=records[:,-1].astype(np.int32)
    if meta['version']!=0x125:
        runs[runs==0]=256
    ends=np.cumsum(runs,dtype=np.int64)
    if ends[-1]<count:
        raise ValueError('RLE HIP truncado')
    last=int(np.searchsorted(ends,count))+1
    runs=runs[:last].copy()
    runs[-1]-=int(ends[last-1])-count
    records=records[:last]
    if encoding==1:
        if int(records[:,0].max())>=len(palette):
            raise ValueError('Índice de paleta inválido')
        indices=np.repeat(records[:,0],runs)
        pixels=palette[indices]
        image=Image.frombytes('RGBA',(width,height),pixels.tobytes(),'raw','BGRA')
    elif encoding==16:
        colors=records[:,:4]
        pixels=np.repeat(colors,runs,axis=0)
        if meta['version']==0x125:
            image=Image.frombytes('RGBA',(width,height),pixels.tobytes(),'raw','BGRA')
        else:
            image=Image.frombytes('RGBA',(width,height),pixels[:,[1,2,3,0]].tobytes())
    else:
        levels=np.repeat(records[:,1],runs)
        image=Image.frombytes('L',(width,height),levels.tobytes()).convert('RGBA')
    return image,meta


def decode_hip_image(data: bytes):
    if Image is None:
        raise RuntimeError("Pillow não está instalado")
    meta = hip_header(data)
    width, height = meta["width"], meta["height"]
    pixel_count = width * height
    if width <= 0 or height <= 0 or pixel_count > 100_000_000:
        raise ValueError(f"Dimensões HIP inválidas: {width}×{height}")
    if np is not None:
        return decode_hip_fast(data,meta)
    cursor, pixels, encoding = meta["data_offset"], bytearray(), meta["encoding"]
    if encoding == 1:
        palette = []
        for _ in range(meta["palette_size"]):
            if cursor + 4 > len(data):
                raise ValueError("Paleta HIP truncada")
            blue, green, red, alpha = data[cursor : cursor + 4]
            palette.append(bytes((red, green, blue, alpha)))
            cursor += 4
        while len(pixels) // 4 < pixel_count:
            if cursor + 2 > len(data):
                raise ValueError("RLE HIP truncado")
            index, run = data[cursor], data[cursor + 1]
            cursor += 2
            if index >= len(palette):
                raise ValueError("RLE/paleta HIP inválido")
            run_count = run if meta['version'] == 0x125 else (run or 256)
            pixels.extend(palette[index] * min(run_count, pixel_count - len(pixels) // 4))
    elif encoding == 16:
        while len(pixels) // 4 < pixel_count:
            if cursor + 5 > len(data):
                raise ValueError("RLE ARGB truncado")
            if meta['version'] == 0x125:
                blue, green, red, alpha, run = data[cursor : cursor + 5]
            else:
                alpha, red, green, blue, run = data[cursor : cursor + 5]
            cursor += 5
            run_count = run if meta['version'] == 0x125 else (run or 256)
            pixels.extend(bytes((red, green, blue, alpha)) * min(run_count, pixel_count - len(pixels) // 4))
    elif encoding == 4:
        while len(pixels) // 4 < pixel_count:
            if cursor + 3 > len(data):
                raise ValueError("RLE Luma truncado")
            value, run = struct.unpack_from("<HB", data, cursor)
            cursor += 3
            level = value >> 8
            run_count = run if meta['version'] == 0x125 else (run or 256)
            pixels.extend(bytes((level, level, level, 255)) * min(run_count, pixel_count - len(pixels) // 4))
    else:
        raise ValueError(f"Codificação HIP não suportada: 0x{encoding:02X}")
    return Image.frombytes("RGBA", (width, height), bytes(pixels)), meta


def decode_hpl_palette(data: bytes):
    if Image is None:
        raise RuntimeError("Pillow não está instalado")
    if len(data) < 32 or not data.startswith(b"HPAL"):
        raise ValueError("Cabeçalho HPL inválido")
    count = struct.unpack_from("<I", data, 12)[0]
    if count <= 0 or count > 65536 or 32 + count * 4 > len(data):
        raise ValueError("Paleta HPL inválida")
    swatch, columns = 24, min(16, count)
    image = Image.new("RGBA", (columns * swatch, math.ceil(count / columns) * swatch), (25, 29, 38, 255))
    for index in range(count):
        blue, green, red, alpha = data[32 + index * 4 : 36 + index * 4]
        block = Image.new("RGBA", (swatch - 1, swatch - 1), (red, green, blue, alpha))
        image.paste(block, ((index % columns) * swatch, (index // columns) * swatch), block)
    return image, {"colors": count}


def decode_visual(item: AssetItem, data: Optional[bytes] = None):
    if Image is None or not item.signature:
        return None, ""
    if data is None:
        data = decoded_payload(item)
    if data is None:
        raise ValueError("Asset grande demais para prévia")
    if item.format_label == "HIP":
        image, meta = decode_hip_image(data)
        return image, f"{meta['width']}×{meta['height']} · textura {meta['texture_w']}×{meta['texture_h']} · encoding 0x{meta['encoding']:02X}"
    if item.format_label == "HPL":
        image, meta = decode_hpl_palette(data)
        return image, f"{meta['colors']} cores"
    if item.format_label in {"PNG", "JPEG", "DDS"}:
        with Image.open(io.BytesIO(data)) as source:
            return source.convert("RGBA"), f"{source.width}×{source.height} · {source.mode}"
    return None, ""


def text_from_item(item: AssetItem, data: bytes) -> Optional[str]:
    payload = data
    if item.format_label == "GZIP":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as archive:
                payload = archive.read(2 * 1024 * 1024 + 1)
        except (OSError, EOFError):
            return None
    if payload.startswith(b"\xff\xfe"):
        return payload.decode("utf-16", errors="replace")
    if item.format_label in {"JSON", "Texto", "CSV", "XML"} or payload.lstrip().startswith((b"{", b"[")):
        text = payload.decode("utf-8-sig", errors="replace")
        try:
            return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return text
    return None


def hex_preview(data: bytes, limit: int = 2048) -> str:
    lines = []
    for offset in range(0, min(len(data), limit), 16):
        chunk = data[offset : offset + 16]
        hex_part = " ".join(f"{value:02X}" for value in chunk).ljust(47)
        ascii_part = "".join(chr(value) if 32 <= value < 127 else "." for value in chunk)
        lines.append(f"{offset:08X}  {hex_part}  {ascii_part}")
    if len(data) > limit:
        lines.append(f"\n… prévia limitada a {human_size(limit)} de {human_size(len(data))}")
    return "\n".join(lines)


@dataclass
class PreviewResult:
    details: str
    content: str
    image: object | None = None
    image_meta: str = ""
    message_title: str = ""
    message_subtitle: str = ""
    tab_index: int = 0

    @property
    def memory_cost(self) -> int:
        image_bytes = 0
        if self.image is not None:
            width, height = getattr(self.image, "size", (0, 0))
            image_bytes = width * height * 4
        return image_bytes + len(self.details) * 2 + len(self.content) * 2


def scan_folder(folder: Path, progress=None) -> tuple[list[AssetItem], int]:
    keys = derive_key_candidates(locate_game_exe(folder))
    paths = sorted((path for path in folder.rglob("*") if path.is_file()), key=lambda path: str(path).lower())
    items = []
    for index, path in enumerate(paths, 1):
        root_item = make_root_item(path, folder, keys)
        items.append(root_item)
        if root_item.signature and root_item.signature.label == "FPAC":
            items.extend(discover_fpac_items(root_item))
        if progress:
            progress(index, len(paths), len(items), root_item)
    return items, len(paths)


class AssetExplorer(tk.Tk):
    def __init__(self, initial_folder: Path):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(f'{min(1540, self.winfo_screenwidth()-80)}x{min(920, self.winfo_screenheight()-100)}')
        self.minsize(1080, 680)
        self.configure(background=BG)
        self.items = []
        self.item_by_iid = {}
        self.message_queue = queue.Queue()
        self.scan_id = 0
        self.current_item = None
        self.current_image = None
        self.preview_photo = None
        self.resize_after = None
        self.filter_after = None
        self.selection_after = None
        self.preview_token = 0
        self.preview_cache = OrderedDict()
        self.preview_cache_bytes = 0
        self.preview_busy = False
        self.pending_preview = None
        self.page = 0
        self.matches = []
        self.folder_var = tk.StringVar(value=str(initial_folder) if initial_folder else '')
        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="Todos")
        self.sort_var = tk.StringVar(value="Categoria")
        self.status_var = tk.StringVar(value="Pronto")
        self.total_var = tk.StringVar(value="0")
        self.visual_var = tk.StringVar(value="0")
        self.package_var = tk.StringVar(value="0")
        self.unknown_var = tk.StringVar(value="0")
        self._configure_style()
        self._build_ui()
        self.search_var.trace_add("write", lambda *_: self.schedule_filter())
        self.filter_var.trace_add("write", lambda *_: self.schedule_filter())
        self.sort_var.trace_add("write", lambda *_: self.schedule_filter())
        self.bind("<F5>", lambda _event: self.start_scan())
        self.bind("<Control-f>", lambda _event: self.search_entry.focus_set())
        self.bind("<Control-e>", lambda _event: self.export_selected())
        self.after(100, self._poll_queue)
        self.after(250, self.start_scan if initial_folder else self.show_welcome)

    def _configure_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 19))
        style.configure("CardValue.TLabel", background=PANEL, foreground=ACCENT, font=("Segoe UI Semibold", 18))
        style.configure("CardLabel.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("TButton", background=PANEL_2, foreground=TEXT, borderwidth=0, padding=(12, 8))
        style.map("TButton", background=[("active", "#253145"), ("pressed", "#1f8c68")])
        style.configure("Accent.TButton", background="#218b68", foreground="#ffffff", padding=(14, 8))
        style.map("Accent.TButton", background=[("active", "#28a57b"), ("pressed", "#176d51")])
        style.configure("TEntry", fieldbackground=PANEL_2, foreground=TEXT, insertcolor=TEXT, bordercolor=LINE, padding=7)
        style.configure("TCombobox", fieldbackground=PANEL_2, background=PANEL_2, foreground=TEXT, arrowcolor=TEXT, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL_2)], foreground=[("readonly", TEXT)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=29, borderwidth=0)
        style.configure("Treeview.Heading", background=PANEL_2, foreground=MUTED, relief="flat", font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", "#1d5c50")], foreground=[("selected", "#ffffff")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(14, 8), borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", PANEL_2)], foreground=[("selected", TEXT)])
        style.configure("Horizontal.TProgressbar", troughcolor=PANEL, background=ACCENT, borderwidth=0)
        style.configure('Toolbutton', background=PANEL, foreground=MUTED, padding=(12, 5), font=('Segoe UI', 10), relief='flat')
        style.map('Toolbutton', background=[('selected', '#1d5c50'), ('active', PANEL_2)], foreground=[('selected', '#ffffff'), ('active', TEXT)])

    def _card(self, parent, label, variable):
        card = ttk.Frame(parent, style="Panel.TFrame", padding=(14, 10))
        ttk.Label(card, textvariable=variable, style="CardValue.TLabel").pack(anchor="w")
        ttk.Label(card, text=label, style="CardLabel.TLabel").pack(anchor="w")
        return card

    def _build_ui(self):
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        title_box = ttk.Frame(header)
        title_box.pack(side="left")
        ttk.Label(title_box, text="PartyDash Viewer", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="BIBLIOTECA VISUAL  /  PARTY DASH", style="Muted.TLabel").pack(anchor="w", pady=(5, 0))
        cards = ttk.Frame(header)
        cards.pack(side="right")
        for label, variable in (("ASSETS", self.total_var), ("VISUAIS", self.visual_var), ("PACOTES", self.package_var), ("DESCONHECIDOS", self.unknown_var)):
            self._card(cards, label, variable).pack(side="left", padx=(8, 0), ipadx=12)
        toolbar = ttk.Frame(outer, style="Panel.TFrame", padding=10)
        toolbar.pack(fill="x", pady=(14, 10))
        ttk.Label(toolbar, text="Pasta", style="PanelMuted.TLabel").pack(side="left", padx=(2, 7))
        ttk.Entry(toolbar, textvariable=self.folder_var).pack(side="left", fill="x", expand=True)
        ttk.Button(toolbar, text="Escolher…", command=self.choose_folder).pack(side="left", padx=7)
        self.scan_button = ttk.Button(toolbar, text="Escanear  F5", style="Accent.TButton", command=self.start_scan)
        self.scan_button.pack(side="left")
        ttk.Button(toolbar, text="Ajuda", command=self.show_welcome).pack(side="left", padx=(8, 0))
        searchbar = ttk.Frame(outer)
        searchbar.pack(fill="x", pady=(0, 10))
        ttk.Label(searchbar, text="Buscar").pack(side="left")
        self.search_entry = ttk.Entry(searchbar, textvariable=self.search_var, width=42)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(8, 18))
        ttk.Label(searchbar, text="Ordenar").pack(side="left")
        ttk.Combobox(searchbar, textvariable=self.sort_var, values=("Categoria", "Nome", "Tamanho"), state="readonly", width=11).pack(side="left", padx=(8, 0))
        workspace = ttk.Frame(outer)
        workspace.pack(fill="both", expand=True)
        sidebar = ttk.Frame(workspace, style="Panel.TFrame", padding=12)
        sidebar.pack(side="left", fill="y", padx=(0, 12))
        ttk.Label(sidebar, text="BIBLIOTECA", style="PanelMuted.TLabel").pack(anchor="w", pady=(4, 12))
        for category in ('Todos', *CATEGORY_ORDER):
            ttk.Radiobutton(sidebar, text=category, variable=self.filter_var, value=category, style='Toolbutton').pack(fill='x', pady=2)
        ttk.Label(sidebar, text="Ctrl+F  Buscar\nCtrl+E  Exportar\nF5  Atualizar", style="PanelMuted.TLabel").pack(anchor='w', pady=(20, 0))
        panes = ttk.PanedWindow(workspace, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left, right = ttk.Frame(panes, style="Panel.TFrame"), ttk.Frame(panes)
        panes.add(left, weight=3)
        panes.add(right, weight=2)
        self.tree = ttk.Treeview(left, columns=("format", "category", "size", "source"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Asset / caminho interno")
        self.tree.column("#0", width=460, minwidth=240)
        for column, text, width in (("format", "Formato", 92), ("category", "Categoria", 120), ("size", "Tamanho", 92), ("source", "Origem", 126)):
            self.tree.heading(column, text=text)
            self.tree.column(column, width=width, minwidth=65)
        y_scroll, x_scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview), ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        paging = ttk.Frame(left, padding=8)
        paging.grid(row=2, column=0, columnspan=2, sticky='ew')
        self.previous_button = ttk.Button(paging, text='Anterior', command=lambda: self.change_page(-1))
        self.previous_button.pack(side='left')
        self.page_label = ttk.Label(paging, text='Sem resultados', style='Muted.TLabel')
        self.page_label.pack(side='left', padx=14)
        self.next_button = ttk.Button(paging, text='Próxima', command=lambda: self.change_page(1))
        self.next_button.pack(side='right')
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind('<Return>', self.on_select)
        for category, color in (("Personagens", "#ffb86c"), ("Backgrounds", "#72b7ff"), ("UI", "#8be9fd"), ("Sprites", "#78dba9"), ("Texturas", "#d5a6ff"), ("Efeitos", "#ff79c6"), ("Vídeos", "#ff9f8f"), ("Desconhecidos", "#88929f")):
            self.tree.tag_configure(category, foreground=color)
        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill="both", expand=True, padx=(12, 0))
        preview_tab, text_tab, details_tab = ttk.Frame(self.notebook, style="Panel.TFrame"), ttk.Frame(self.notebook, style="Panel.TFrame"), ttk.Frame(self.notebook, style="Panel.TFrame")
        self.notebook.add(preview_tab, text="Prévia")
        self.notebook.add(text_tab, text="Texto / Hex")
        self.notebook.add(details_tab, text="Detalhes")
        preview_head = ttk.Frame(preview_tab, style="Panel.TFrame", padding=(12, 10))
        preview_head.pack(fill="x")
        self.preview_title = ttk.Label(preview_head, text="Selecione um asset", style="Panel.TLabel", font=("Segoe UI Semibold", 12))
        self.preview_title.pack(side="left")
        self.preview_meta = ttk.Label(preview_head, text="", style="PanelMuted.TLabel")
        self.preview_meta.pack(side="right")
        self.preview_canvas = tk.Canvas(preview_tab, background="#11151d", highlightthickness=0)
        self.preview_canvas.pack(fill="both", expand=True)
        self.preview_canvas.bind("<Configure>", self._on_canvas_resize)
        self.content_text = tk.Text(text_tab, wrap="none", background="#10151d", foreground="#dce5ef", insertbackground=TEXT, relief="flat", padx=12, pady=12, font=("Cascadia Mono", 9))
        text_y, text_x = ttk.Scrollbar(text_tab, orient="vertical", command=self.content_text.yview), ttk.Scrollbar(text_tab, orient="horizontal", command=self.content_text.xview)
        self.content_text.configure(yscrollcommand=text_y.set, xscrollcommand=text_x.set)
        self.content_text.grid(row=0, column=0, sticky="nsew")
        text_y.grid(row=0, column=1, sticky="ns")
        text_x.grid(row=1, column=0, sticky="ew")
        text_tab.rowconfigure(0, weight=1)
        text_tab.columnconfigure(0, weight=1)
        self.details_text = tk.Text(details_tab, wrap="word", background=PANEL, foreground=TEXT, relief="flat", padx=16, pady=16, font=("Cascadia Mono", 9))
        self.details_text.pack(fill="both", expand=True)
        actions = ttk.Frame(right)
        actions.pack(fill="x", padx=(12, 0), pady=(10, 0))
        ttk.Button(actions, text="Abrir arquivo-fonte", command=self.open_selected).pack(side="left")
        ttk.Button(actions, text="Exportar PNG / conteúdo  Ctrl+E", style="Accent.TButton", command=self.export_selected).pack(side="right")
        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(10, 0))
        self.progress = ttk.Progressbar(footer, mode="determinate", length=220)
        self.progress.pack(side="left")
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel").pack(side="left", padx=10)
        self._preview_message('Explore sua biblioteca', 'Selecione um item para ver a imagem e os detalhes. Use as categorias à esquerda para começar.')

    def choose_folder(self):
        selected = filedialog.askdirectory(title='Selecione a pasta do jogo ou a subpasta asset', initialdir=self.folder_var.get() or os.getcwd())
        if selected:
            folder = normalize_folder(selected)
            if folder is None:
                messagebox.showinfo(APP_TITLE, 'Não encontramos os assets nessa pasta.\n\nEscolha a pasta que contém Uma Party Dash.exe e a subpasta asset, ou selecione a própria pasta asset.\n\nNa Steam: Biblioteca > jogo > Gerenciar > Explorar arquivos locais.')
                return
            self.folder_var.set(str(folder))
            self.start_scan()

    def show_welcome(self):
        dialog = tk.Toplevel(self)
        dialog.title('Conectar uma instalação')
        dialog.configure(background=BG)
        dialog.geometry('640x420')
        dialog.transient(self)
        body = ttk.Frame(dialog, padding=32)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Sua biblioteca começa aqui', style='Title.TLabel').pack(anchor='w', pady=(0, 16))
        ttk.Label(body, text='Conecte os arquivos de Party Dash para explorar sprites,\ncenários e texturas com prévia e exportação.', justify='left').pack(anchor='w')
        ttk.Label(body, text='ONDE ENCONTRAR', style='Muted.TLabel').pack(anchor='w', pady=(26, 10))
        ttk.Label(body, text='Steam: Biblioteca > jogo > Gerenciar > Explorar arquivos locais.\nOutra instalação: abra a pasta onde você instalou o jogo.\n\nEscolha a pasta com Uma Party Dash.exe e a subpasta asset,\nou escolha diretamente asset.', justify='left').pack(anchor='w')
        def choose():
            dialog.destroy()
            self.choose_folder()
        ttk.Button(body, text='Selecionar pasta do jogo', style='Accent.TButton', command=choose).pack(anchor='w', pady=(24, 0))

    def start_scan(self):
        folder = normalize_folder(Path(self.folder_var.get()).expanduser()) if self.folder_var.get() else None
        if folder is None:
            self.show_welcome()
            return
        self.folder_var.set(str(folder))
        try:
            remember_folder(folder)
        except OSError:
            self.status_var.set('Não foi possível salvar a pasta; a sessão continua normalmente.')
        self.scan_id += 1
        self.preview_token += 1
        if self.selection_after:
            self.after_cancel(self.selection_after)
            self.selection_after = None
        self.preview_cache.clear()
        self.preview_cache_bytes = 0
        self.current_item = None
        token = self.scan_id
        self.items.clear()
        self.item_by_iid.clear()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.scan_button.configure(state="disabled")
        self.progress.configure(value=0, maximum=100)
        self.status_var.set("Analisando arquivos e abrindo pacotes FPAC…")
        threading.Thread(target=self._scan_worker, args=(folder, token), daemon=True).start()

    def _scan_worker(self, folder, token):
        def progress(index, total, asset_count, root_item):
            if token != self.scan_id:
                raise RuntimeError("scan cancelado")
            if index % 20 == 0 or index == total:
                self.message_queue.put(("progress", token, index, total, asset_count, root_item.relative))
        try:
            items, root_count = scan_folder(folder, progress)
        except RuntimeError:
            return
        except Exception as error:
            self.message_queue.put(("error", token, str(error)))
            return
        self.message_queue.put(("done", token, items, root_count))

    def _poll_queue(self):
        try:
            while True:
                kind, token, *payload = self.message_queue.get_nowait()
                if kind == 'preview':
                    self.preview_busy = False
                    pending, self.pending_preview = self.pending_preview, None
                    if pending:
                        self._start_preview(*pending)
                if token != self.scan_id:
                    continue
                if kind == "progress":
                    index, total, assets, current = payload
                    self.progress.configure(maximum=max(1, total), value=index)
                    self.status_var.set(f"{index}/{total} arquivos · {assets:,} assets encontrados · {current}")
                elif kind == "error":
                    self.scan_button.configure(state="normal")
                    messagebox.showerror(APP_TITLE, payload[0])
                elif kind == "done":
                    self.items, root_count = payload
                    self.scan_button.configure(state="normal")
                    self.apply_filter()
                    self.status_var.set(f"Concluído: {root_count:,} arquivos-fonte, {len(self.items):,} assets catalogados. Originais intactos.")
                elif kind == "preview":
                    preview_token, cache_key, item, result = payload
                    if preview_token != self.preview_token or item is not self.current_item:
                        continue
                    self._cache_preview(cache_key, result)
                    self._apply_preview_result(item, result)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    def _update_cards(self):
        visual = {"Personagens", "Backgrounds", "UI", "Sprites", "Texturas", "Paletas", "Efeitos"}
        self.total_var.set(f"{len(self.items):,}")
        self.visual_var.set(f"{sum(item.category in visual for item in self.items):,}")
        self.package_var.set(f"{sum(item.category == 'Pacotes' for item in self.items):,}")
        self.unknown_var.set(f"{sum(item.category == 'Desconhecidos' for item in self.items):,}")

    def schedule_filter(self):
        if self.filter_after:
            self.after_cancel(self.filter_after)
        self.filter_after = self.after(220, self.apply_filter)

    def apply_filter(self):
        self.filter_after = None
        if not hasattr(self, "tree"):
            return
        self.preview_token += 1
        self.current_item = None
        self.pending_preview = None
        self._preview_message('Selecione um asset', 'Use as setas para navegar pelos resultados.')
        self._set_text(self.details_text, '')
        self._set_text(self.content_text, '')
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.item_by_iid.clear()
        wanted, needle = self.filter_var.get(), self.search_var.get().strip().casefold()
        matches = []
        for item in self.items:
            if wanted != "Todos" and item.category != wanted:
                continue
            if needle and needle not in item.search_blob:
                continue
            matches.append(item)
        if self.sort_var.get() == "Nome":
            matches.sort(key=lambda item: item.relative.casefold())
        elif self.sort_var.get() == "Tamanho":
            matches.sort(key=lambda item: (-item.size, item.relative.casefold()))
        else:
            matches.sort(key=lambda item: (CATEGORY_ORDER.get(item.category, 999), item.relative.casefold()))
        self.matches = matches
        self.page = 0
        self.render_page()
        self._update_cards()

    def change_page(self, delta):
        self.preview_token += 1
        self.current_item = None
        self.pending_preview = None
        self._preview_message('Selecione um asset', 'Use as setas para navegar nesta página.')
        self._set_text(self.details_text, '')
        self._set_text(self.content_text, '')
        self.page = max(0, min(max(0, (len(self.matches)-1)//MAX_VISIBLE_ROWS), self.page + delta))
        self.render_page()

    def render_page(self):
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        self.item_by_iid.clear()
        start = self.page * MAX_VISIBLE_ROWS
        for item in self.matches[start:start + MAX_VISIBLE_ROWS]:
            iid = self.tree.insert("", "end", text=item.display_name, values=(item.format_label, item.category, human_size(item.size), item.source_path.name), tags=(item.category,))
            self.item_by_iid[iid] = item
        pages = max(1, math.ceil(len(self.matches)/MAX_VISIBLE_ROWS))
        self.page_label.configure(text=f'{self.page + 1} / {pages}  ·  {len(self.matches):,} resultados')
        self.previous_button.configure(state='normal' if self.page else 'disabled')
        self.next_button.configure(state='normal' if self.page + 1 < pages else 'disabled')
        self.status_var.set(f'{self.filter_var.get()} · {len(self.matches):,} resultados')
        if not self.matches:
            self._preview_message('Nenhum resultado', 'Tente outro nome ou selecione Todos na biblioteca.')

    def on_select(self, _event=None):
        selection = self.tree.selection()
        if not selection or selection[0] not in self.item_by_iid:
            return
        item = self.item_by_iid[selection[0]]
        self.current_item = item
        self.preview_token += 1
        token = self.preview_token
        if self.selection_after:
            self.after_cancel(self.selection_after)
        self.preview_title.configure(text=Path(item.relative).name)
        self.preview_meta.configure(text=f"{item.category} · {item.format_label} · {human_size(item.size)}")
        self._set_text(self.details_text, self.item_details(item, None))
        self._set_text(self.content_text, "Aguardando prévia…")
        self._preview_message("Carregando prévia…", "A navegação continua disponível.")
        self.selection_after = self.after(PREVIEW_DEBOUNCE_MS, lambda: self._start_preview(item, token))

    def _preview_key(self, item):
        return (str(item.source_path), item.source_offset, item.size, item.format_label)

    def _start_preview(self, item, token):
        self.selection_after = None
        if token != self.preview_token or item is not self.current_item:
            return
        if self.preview_busy:
            self.pending_preview = (item, token)
            return
        cache_key = self._preview_key(item)
        cached = self.preview_cache.get(cache_key)
        if cached is not None:
            self.preview_cache.move_to_end(cache_key)
            self._apply_preview_result(item, cached)
            return
        self.preview_busy = True
        threading.Thread(target=self._preview_worker, args=(item, token, cache_key, self.scan_id), daemon=True).start()

    def _preview_worker(self, item, token, cache_key, scan_token):
        try:
            data = preview_payload(item)
            details = self.item_details(item, data)
            if data is None:
                result = PreviewResult(details, "Asset grande demais ou ilegível para carregar na prévia.", message_title="Prévia indisponível", message_subtitle="O limite de leitura é 128 MB.")
            else:
                text = text_from_item(item, data)
                content = text if text is not None else hex_preview(data)
                if text is not None:
                    result = PreviewResult(details, content, message_title="Documento de texto", message_subtitle="Conteúdo decodificado na aba Texto / Hex.", tab_index=1)
                else:
                    try:
                        image, meta = decode_visual(item, data)
                    except Exception as error:
                        image, meta = None, ""
                        result = PreviewResult(details, content, message_title="Não foi possível renderizar", message_subtitle=str(error))
                    else:
                        if image is not None:
                            result = PreviewResult(details, content, image=image, image_meta=meta)
                        elif item.format_label == "WebM":
                            result = PreviewResult(details, content, message_title="Vídeo WebM", message_subtitle="Abra o arquivo-fonte para reproduzir no player padrão.")
                        elif item.format_label in {"FPAC", "PAC"}:
                            children = sum(candidate.embedded and candidate.relative.startswith(item.relative + "/") for candidate in self.items)
                            result = PreviewResult(details, content, message_title="Pacote FPAC", message_subtitle=f"{children:,} item(ns) interno(s) catalogado(s).")
                        elif item.format_label == "GZIP":
                            result = PreviewResult(details, content, message_title="Conteúdo GZIP", message_subtitle="Veja os dados reconhecidos na aba Texto / Hex.")
                        else:
                            result = PreviewResult(details, content, message_title=item.format_label, message_subtitle="Metadados e bytes iniciais estão nas outras abas.")
        except Exception as error:
            result = PreviewResult(self.item_details(item, None), f"Falha ao carregar a prévia:\n{error}", message_title="Falha na prévia", message_subtitle=str(error))
        self.message_queue.put(("preview", scan_token, token, cache_key, item, result))

    def _cache_preview(self, key, result):
        previous = self.preview_cache.pop(key, None)
        if previous is not None:
            self.preview_cache_bytes -= previous.memory_cost
        self.preview_cache[key] = result
        self.preview_cache_bytes += result.memory_cost
        while self.preview_cache and self.preview_cache_bytes > PREVIEW_CACHE_BYTES:
            _, discarded = self.preview_cache.popitem(last=False)
            self.preview_cache_bytes -= discarded.memory_cost

    def _apply_preview_result(self, item, result):
        self._set_text(self.details_text, result.details)
        self._set_text(self.content_text, result.content)
        if result.image is not None:
            self.current_image = result.image
            self.preview_meta.configure(text=f"{item.category} · {result.image_meta}")
            self._render_current_image()
        else:
            self._preview_message(result.message_title or item.format_label, result.message_subtitle)
        self.notebook.select(result.tab_index)

    def _set_text(self, widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _on_canvas_resize(self, _event=None):
        if self.resize_after:
            self.after_cancel(self.resize_after)
        self.resize_after = self.after(80, self._render_current_image)

    def _checkerboard(self):
        width, height, step = max(1, self.preview_canvas.winfo_width()), max(1, self.preview_canvas.winfo_height()), 18
        self.preview_canvas.delete('foreground')
        if getattr(self, '_checker_size', None) == (width, height):
            return
        self._checker_size = (width, height)
        self.preview_canvas.delete('all')
        colors = ("#151b23", "#1b222d")
        for y in range(0, height, step):
            for x in range(0, width, step):
                self.preview_canvas.create_rectangle(x, y, x + step, y + step, fill=colors[(x // step + y // step) % 2], outline="")

    def _render_current_image(self):
        self.resize_after = None
        self._checkerboard()
        if self.current_image is None or ImageTk is None:
            return
        image = self.current_image.copy()
        image.thumbnail((max(80, self.preview_canvas.winfo_width() - 32), max(80, self.preview_canvas.winfo_height() - 32)), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(image)
        self.preview_canvas.create_image(self.preview_canvas.winfo_width() // 2, self.preview_canvas.winfo_height() // 2, image=self.preview_photo, tags='foreground')

    def _preview_message(self, title, subtitle=""):
        self.current_image = None
        self._checkerboard()
        width, height = max(400, self.preview_canvas.winfo_width()), max(300, self.preview_canvas.winfo_height())
        self.preview_canvas.create_text(width // 2, height // 2 - 12, text=title, fill=TEXT, font=("Segoe UI Semibold", 16), tags='foreground')
        if subtitle:
            self.preview_canvas.create_text(width // 2, height // 2 + 24, text=subtitle, fill=MUTED, font=("Segoe UI", 10), width=width - 80, justify="center", tags='foreground')

    def item_details(self, item, data):
        lines = [f"Asset: {item.relative}", f"Arquivo-fonte: {item.source_path}", f"Tamanho: {human_size(item.size)} ({item.size:,} bytes)", f"Formato: {item.format_label}", f"Categoria: {item.category}", f"Critério: {item.category_reason}", f"Leitura: {item.decoder_label}", f"Offset físico: 0x{item.source_offset:X}", f"Confiança: {item.probe.confidence}"]
        if data:
            if item.format_label == "DDS":
                lines.append("Imagem: " + dds_info(data))
            elif item.format_label in {"FPAC", "PAC"}:
                info = fpac_info(data)
                if info:
                    lines.append("Pacote: " + info)
            elif item.format_label == "HIP":
                try:
                    meta = hip_header(data)
                    lines.append(f"Sprite: {meta['width']}×{meta['height']}, textura {meta['texture_w']}×{meta['texture_h']}, encoding 0x{meta['encoding']:02X}")
                except ValueError:
                    pass
        if item.embedded:
            lines.append("\nItem interno de FPAC. A exportação cria uma cópia independente; o original não é alterado.")
        return "\n".join(lines)

    def open_selected(self):
        if not self.current_item:
            return
        try:
            os.startfile(self.current_item.source_path)
        except Exception as error:
            messagebox.showerror(APP_TITLE, f"Não foi possível abrir o arquivo-fonte:\n{error}")

    def export_selected(self):
        item = self.current_item
        if not item:
            messagebox.showinfo(APP_TITLE, "Selecione um asset primeiro.")
            return
        data = decoded_payload(item)
        if data is None:
            messagebox.showwarning(APP_TITLE, "Este asset é grande demais para exportação pela interface.")
            return
        try:
            image, _ = decode_visual(item, data)
        except Exception:
            image = None
        if image is not None:
            extension, initial, filetypes = ".png", Path(item.relative).stem + ".png", [("Imagem PNG", "*.png"), ("Todos os arquivos", "*.*")]
        else:
            extension = item.signature.extension if item.signature else (Path(item.relative).suffix or ".bin")
            initial, filetypes = Path(item.relative).stem + extension, [("Conteúdo decodificado", f"*{extension}"), ("Todos os arquivos", "*.*")]
        destination = filedialog.asksaveasfilename(title="Exportar asset", initialfile=initial, defaultextension=extension, filetypes=filetypes)
        if not destination:
            return
        try:
            image.save(destination, "PNG") if image is not None else Path(destination).write_bytes(data)
        except OSError as error:
            messagebox.showerror(APP_TITLE, f"Falha ao exportar:\n{error}")
            return
        self.status_var.set(f"Exportado: {destination}")


def default_folder() -> Path:
    found = discover_folders()
    return found[0] if found else None


def cli_scan(folder: Path) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not folder.is_dir():
        print(f"Pasta não encontrada: {folder}", file=sys.stderr)
        return 2
    items, root_count = scan_folder(folder)
    categories, formats = {}, {}
    for item in items:
        categories[item.category] = categories.get(item.category, 0) + 1
        formats[item.format_label] = formats.get(item.format_label, 0) + 1
    print(f"Pasta: {folder}")
    print(f"Arquivos-fonte: {root_count}")
    print(f"Assets catalogados: {len(items)}")
    print("Categorias:", ", ".join(f"{key}={value}" for key, value in sorted(categories.items())))
    print("Formatos:", ", ".join(f"{key}={value}" for key, value in sorted(formats.items())))
    print("Desconhecidos:", categories.get("Desconhecidos", 0))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Explorador local de assets de Party Dash")
    parser.add_argument("--scan", metavar="PASTA", help="faz um scan textual sem abrir a interface")
    parser.add_argument('--self-test', action='store_true', help='verifica dependências e inicialização da interface')
    parser.add_argument("--version", action="version", version="PartyDash Viewer 1.0.0")
    args = parser.parse_args()
    if args.self_test:
        if Image is None:
            return 1
        app = AssetExplorer(None)
        app.withdraw()
        app.update_idletasks()
        app.destroy()
        return 0
    if args.scan:
        return cli_scan(Path(args.scan).expanduser())
    app = AssetExplorer(default_folder())
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
