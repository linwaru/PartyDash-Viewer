from __future__ import annotations
import sys
import json
import re
import qtawesome as qta
import queue
import threading
import hashlib
import tempfile
import urllib.request
from collections import OrderedDict, Counter
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import Qt, QTimer, QSize, QRectF, QPointF, Signal, QUrl
from PySide6.QtGui import QImage, QPixmap, QIcon, QPainter, QColor, QFont, QPainterPath, QKeySequence, QShortcut, QBrush, QPen, QPalette
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QListWidget, QListWidgetItem, QListView,
    QLineEdit, QComboBox, QSplitter, QFileDialog, QMessageBox, QPlainTextEdit,
    QProgressBar, QFrame, QDialog, QDialogButtonBox, QToolButton, QMenu, QStyle, QStyledItemDelegate, QScrollArea, QSizePolicy, QProxyStyle, QStyleOptionFocusRect, QGridLayout, QSlider)
import uma_asset_explorer as engine
from asset_export import export_asset
from catalog_cache import scan_cached
from game_location import discover_folders, normalize_folder, remember_folder, settings_path
from i18n import LANGUAGES, Translator
from version import APP_NAME, DISPLAY_VERSION, VERSION, REPOSITORY

VISUAL = {'HIP', 'DDS', 'PNG', 'JPEG', 'HPL'}
SECTIONS = {
    'Personagens': ({'Personagens'},),
    'Cenários': ({'Backgrounds'},),
    'Objetos e sprites': ({'Sprites', 'Texturas'},),
    'Interface': ({'UI'},),
    'Efeitos': ({'Efeitos'},),
    'Paletas': ({'Paletas'},),
    'Áudio e vídeo': ({'Áudio', 'Vídeos'},),
    'Arquivos técnicos': ({'Pacotes', 'Dados', 'Animações', 'Modelos', 'Fontes', 'Desconhecidos'},),
    'Todos os assets': ({'Personagens', 'Backgrounds', 'UI', 'Sprites', 'Texturas', 'Paletas', 'Efeitos', 'Animações', 'Modelos', 'Áudio', 'Vídeos', 'Fontes', 'Dados', 'Pacotes', 'Desconhecidos'},),
    'Imagens': ({'Backgrounds', 'Texturas', 'Paletas'},),
    'Sprites': ({'Sprites'},),
    'Modelos': ({'Modelos'},),
    'Áudio': ({'Áudio', 'Vídeos'},),
    'Outros': ({'Efeitos', 'Paletas', 'Animações', 'Pacotes', 'Dados', 'Fontes', 'Desconhecidos'},),
}

SIDEBAR_ITEMS = (
    ('Todos os assets', 'Todos os assets'),
    ('Imagens', 'Imagens'),
    ('Sprites', 'Sprites'),
    ('Modelos', 'Modelos'),
    ('Áudio', 'Áudio'),
    ('Interface', 'Interface'),
    ('Personagens', 'Personagens'),
    ('Outros', 'Outros'),
)

SEMANTIC_SUBCATEGORY_KEYS = {
    'Personagens': 'subcat.characters',
    'Backgrounds': 'subcat.scenarios',
    'UI': 'subcat.interface',
    'Sprites': 'subcat.sprites',
    'Texturas': 'subcat.textures',
    'Paletas': 'subcat.palettes',
    'Efeitos': 'subcat.effects',
    'Animações': 'subcat.animations',
    'Modelos': 'subcat.models',
    'Áudio': 'subcat.audio',
    'Vídeos': 'subcat.video',
    'Fontes': 'subcat.fonts',
    'Dados': 'subcat.data',
    'Pacotes': 'subcat.packages',
    'Desconhecidos': 'subcat.other',
}

CATEGORY_LABEL_KEYS = {
    'Personagens': 'category.characters',
    'Backgrounds': 'category.backgrounds',
    'UI': 'category.interface',
    'Sprites': 'category.sprites',
    'Texturas': 'category.textures',
    'Paletas': 'category.palettes',
    'Efeitos': 'category.effects',
    'Animações': 'category.animations',
    'Modelos': 'category.models',
    'Áudio': 'category.audio',
    'Vídeos': 'category.video',
    'Fontes': 'category.fonts',
    'Dados': 'category.data',
    'Pacotes': 'category.packages',
    'Desconhecidos': 'category.unknown',
}

SUBCATEGORY_RULES = {
    'Personagens': (
        ('subcat.characters.portraits', {'face', 'faces', 'portrait', 'portraits', 'head', 'expression', 'expressions'}),
        ('subcat.characters.costumes', {'costume', 'costumes', 'outfit', 'outfits', 'dress', 'uniform', 'clothes', 'skin'}),
        ('subcat.characters.models', {'model', 'models', 'body', 'mesh', '3d'}),
    ),
    'UI': (
        ('subcat.ui.controls', {'button', 'buttons', 'btn', 'menu', 'menus', 'dialog', 'select', 'gauge', 'hud'}),
        ('subcat.ui.icons', {'icon', 'icons', 'symbol', 'symbols', 'logo', 'badge'}),
        ('subcat.ui.text', {'font', 'fonts', 'text', 'title', 'label'}),
        ('subcat.ui.panels', {'frame', 'panel', 'window', 'header', 'banner'}),
    ),
    'Sprites': (
        ('subcat.furniture.seating', {'chair', 'chairs', 'sofa', 'couch', 'bench', 'stool'}),
        ('subcat.furniture.tables', {'desk', 'desks', 'table', 'tables', 'counter'}),
        ('subcat.furniture.storage', {'shelf', 'shelves', 'cabinet', 'locker', 'wardrobe', 'dresser'}),
        ('subcat.furniture.decor', {'lamp', 'lamps', 'plant', 'plants', 'prop', 'props', 'decoration', 'decorations', 'decor', 'fixture', 'fixtures'}),
        ('subcat.surfaces.walls', {'wall', 'walls', 'ceiling', 'ceilings', 'roof', 'roofs'}),
        ('subcat.surfaces.floors', {'tile', 'tiles', 'tiler', 'tilers', 'floor', 'floors', 'ground', 'terrain', 'road', 'roads', 'path', 'paths', 'pavement', 'platform', 'platforms'}),
        ('subcat.effects.particles', {'effect', 'effects', 'particle', 'particles', 'vfx', 'aura', 'smoke'}),
        ('subcat.effects.lighting', {'spark', 'sparks', 'glow', 'glows', 'flare', 'flares', 'shine', 'glare'}),
        ('subcat.effects.impacts', {'impact', 'impacts', 'hit', 'slash', 'burst', 'explosion', 'explosions'}),
        ('subcat.effects.motion', {'trail', 'trails', 'streak', 'streaks', 'speedline', 'speedlines', 'dust', 'ring', 'rings'}),
        ('subcat.sprites.characters', {'ch', 'char', 'chara', 'character', 'npc', 'uma'}),
        ('subcat.sprites.interface', {'icon', 'icons', 'button', 'buttons', 'ui', 'menu'}),
    ),
    'Texturas': (
        ('subcat.furniture.seating', {'chair', 'chairs', 'sofa', 'couch', 'bench', 'stool'}),
        ('subcat.furniture.tables', {'desk', 'desks', 'table', 'tables', 'counter'}),
        ('subcat.furniture.storage', {'shelf', 'shelves', 'cabinet', 'locker', 'wardrobe', 'dresser'}),
        ('subcat.furniture.decor', {'lamp', 'lamps', 'plant', 'plants', 'prop', 'props', 'decoration', 'decorations', 'decor', 'fixture', 'fixtures'}),
        ('subcat.surfaces.walls', {'wall', 'walls', 'ceiling', 'ceilings', 'roof', 'roofs'}),
        ('subcat.surfaces.floors', {'tile', 'tiles', 'tiler', 'tilers', 'floor', 'floors', 'ground', 'terrain', 'road', 'roads', 'path', 'paths', 'pavement', 'platform', 'platforms'}),
        ('subcat.effects.particles', {'effect', 'effects', 'particle', 'particles', 'vfx', 'aura', 'smoke'}),
        ('subcat.effects.lighting', {'spark', 'sparks', 'glow', 'glows', 'flare', 'flares', 'shine', 'glare'}),
        ('subcat.effects.impacts', {'impact', 'impacts', 'hit', 'slash', 'burst', 'explosion', 'explosions'}),
        ('subcat.effects.motion', {'trail', 'trails', 'streak', 'streaks', 'speedline', 'speedlines', 'dust', 'ring', 'rings'}),
        ('subcat.textures.characters', {'ch', 'char', 'chara', 'character', 'npc', 'face', 'costume'}),
        ('subcat.textures.environment', {'bg', 'background', 'stage', 'field', 'sky', 'map', 'scene'}),
        ('subcat.textures.interface', {'ui', 'icon', 'button', 'menu', 'font'}),
    ),
    'Áudio': (
        ('subcat.audio.music', {'bgm', 'music', 'song', 'songs', 'theme', 'ost'}),
        ('subcat.audio.voices', {'voice', 'voices', 'vo', 'speech', 'talk'}),
        ('subcat.audio.effects', {'se', 'sfx', 'sound', 'sounds', 'effect', 'effects'}),
    ),
    'Vídeos': (
        ('subcat.video.cutscenes', {'video', 'movie', 'cutscene', 'opening', 'ending', 'webm'}),
    ),
    'Efeitos': (
        ('subcat.effects.particles', {'particle', 'particles', 'vfx', 'aura', 'smoke'}),
        ('subcat.effects.lighting', {'spark', 'sparks', 'glow', 'glows', 'flare', 'flares', 'shine', 'glare'}),
        ('subcat.effects.impacts', {'impact', 'impacts', 'hit', 'slash', 'burst', 'explosion', 'explosions'}),
        ('subcat.effects.motion', {'trail', 'trails', 'streak', 'streaks', 'speedline', 'speedlines', 'dust', 'ring', 'rings'}),
        ('subcat.effects.transitions', {'transition', 'wipe', 'fade'}),
    ),
}

CHARACTER_SPRITE_PATTERN = re.compile(r'^(?P<prefix>[a-z]{2,12})(?P<family>\d{3}[a-z]?)_(?P<frame>\d{2})(?P<side>[lr])?(?:\.[a-z0-9]+)+$', re.IGNORECASE)


def character_sprite_subcategory(relative: str) -> str | None:
    leaf = str(relative).replace('\\', '/').rsplit('/', 1)[-1].casefold()
    match = CHARACTER_SPRITE_PATTERN.fullmatch(leaf)
    if not match:
        return None
    return 'subcat.characters.accessories' if match.group('side') in {'l', 'r'} else 'subcat.characters.base'


def infer_subcategory_key(item) -> str | None:
    category = getattr(item, 'category', '')
    relative = str(getattr(item, 'relative', '')).casefold().replace('\\', '/')
    if category == 'Personagens':
        character_key = character_sprite_subcategory(relative)
        if character_key:
            return character_key
    normalized = re.sub(r'([a-z])([A-Z])', r'\1_\2', relative)
    parts = normalized.split('/')
    leaf_tokens = set(re.findall(r'[a-z0-9]+', parts[-1] if parts else normalized))
    folder_tokens = set(re.findall(r'[a-z0-9]+', '/'.join(parts[:-1])))
    for key, markers in SUBCATEGORY_RULES.get(category, ()):
        if leaf_tokens & markers:
            return key
    for key, markers in SUBCATEGORY_RULES.get(category, ()):
        if folder_tokens & markers:
            return key
    return None

SECTION_DESCRIPTION_KEYS = {
    'Personagens': 'section.characters.description',
    'Cenários': 'section.scenarios.full_description',
    'Objetos e sprites': 'section.objects.full_description',
    'Interface': 'section.interface.full_description',
    'Efeitos': 'section.effects.description',
    'Paletas': 'section.palettes.description',
    'Áudio e vídeo': 'section.audio.description',
    'Arquivos técnicos': 'section.technical.description',
    'Todos os assets': 'section.all.description',
    'Imagens': 'section.images.description',
    'Sprites': 'section.sprites.description',
    'Modelos': 'section.models.description',
    'Áudio': 'section.audio.description',
    'Outros': 'section.other.description',
}

SECTION_TITLE_KEYS = {
    'Todos os assets': 'all_assets',
    'Imagens': 'images',
    'Sprites': 'sprites',
    'Modelos': 'models',
    'Áudio': 'audio',
    'Interface': 'interface',
    'Personagens': 'characters',
    'Outros': 'other',
    'Cenários': 'section.scenarios',
    'Objetos e sprites': 'section.objects',
}


def version_tuple(value: str) -> tuple[int, int, int]:
    parts = [int(part) for part in re.findall(r'\d+', value)[:3]]
    return tuple((parts + [0, 0, 0])[:3])

STYLE = '''
QWidget { font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 13px; color: #17233a; }
QMainWindow, QWidget#shell { background: #f8f9fc; }
QFrame#topbar { background: #ffffff; border-bottom: 1px solid #e5e8ee; }
QWidget#rail { background: #ffffff; border-right: 1px solid #e1e5eb; }
QLabel#eyebrow { color: #738097; font-size: 10px; font-weight: 700; letter-spacing: 1.25px; }
QLabel#title { font-size: 25px; font-weight: 700; letter-spacing: -0.65px; color: #15223a; }
QLabel#heroTitle { font-size: 32px; font-weight: 700; letter-spacing: -0.9px; color: #15223a; }
QLabel#sectionTitle { font-size: 15px; font-weight: 700; color: #17233a; }
QLabel#assetTitle { font-size: 18px; font-weight: 700; color: #15223a; }
QLabel#counter { color: #77849a; font-size: 12px; }
QLabel#muted { color: #6d7b90; }
QLabel#status { color: #718097; font-size: 11px; }
QLabel#navCount { color: #8a96a8; font-size: 11px; }
QLabel#infoLabel { color: #77849a; font-size: 12px; }
QLabel#infoValue { color: #27344a; font-size: 12px; }
QPushButton { background: #ffffff; border: 1px solid #d8dee7; border-radius: 8px; padding: 9px 14px; color: #26344b; }
QPushButton:hover { background: #fff7f7; border-color: #f19b9e; }
QPushButton:pressed { background: #ffecee; }
QPushButton:disabled { color: #9aa5b4; background: #f0f2f5; border-color: #e1e5eb; }
QPushButton#primary { background: #d93645; color: #ffffff; border: 1px solid #d93645; font-weight: 700; }
QPushButton#primary:hover { background: #df464b; border-color: #df464b; }
QPushButton#primary:pressed { background: #c83c42; }
QPushButton#nav { text-align: left; border: 0; background: transparent; padding: 9px 10px; color: #536178; }
QPushButton#nav:checked { background: #fff0f1; color: #df474d; border-left: 3px solid #ff535d; padding-left: 7px; font-weight: 700; }
QPushButton#nav:hover { background: #fff7f7; color: #d6494f; }
QLineEdit, QComboBox { background: #ffffff; border: 1px solid #d8dee7; border-radius: 8px; padding: 9px 11px; color: #26344b; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #ff535d; }
QLineEdit#globalSearch { padding: 10px 14px; }
QLineEdit#folderField { background: #fbfcfd; color: #4d5b70; }
QLineEdit#folderField:disabled { color: #9aa5b4; }
QListWidget#gallery { background: transparent; border: 0; outline: 0; }
QFrame#panel { background: #ffffff; border: 1px solid #e2e6ed; border-radius: 8px; }
QFrame#infoCard { background: #ffffff; border: 0; border-radius: 8px; }
QFrame#sideCard { background: #fbfcfd; border: 1px solid #e3e7ed; border-radius: 8px; }
QFrame#successCard { background: #f1fbf5; border: 1px solid #bde9cb; border-radius: 8px; }
QFrame#emptyCard { background: #ffffff; border: 1px dashed #d9dfe7; border-radius: 8px; }
QPlainTextEdit { background: #fafbfc; border: 1px solid #e2e6ed; border-radius: 8px; padding: 10px; font-family: Consolas; font-size: 12px; }
QProgressBar { background: #e9edf2; border: 0; border-radius: 3px; height: 6px; }
QProgressBar::chunk { background: #ff535d; border-radius: 3px; }
QFrame#footerSeparator { background: #dfe4eb; border: 0; }
QSplitter::handle { background: #e5e8ee; width: 8px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #c6ced9; border-radius: 4px; min-height: 32px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QComboBox::drop-down { border: 0; width: 24px; }
QToolTip { background: #ffffff; color: #26344b; border: 1px solid #d8dee7; padding: 6px; }
QToolButton#export { background: #d93645; color: #ffffff; border: 1px solid #d93645; border-radius: 8px; padding: 11px 40px 11px 14px; font-weight: 700; }
QToolButton#export:hover { background: #df464b; }
QToolButton#export:pressed { background: #c83c42; }
QToolButton#export:disabled { background: #edf0f3; color: #9aa5b4; border-color: #e1e5eb; }
QToolButton#export::menu-button { border-left: 1px solid #f47f82; width: 30px; }
QToolButton#iconButton, QToolButton#viewButton { background: #ffffff; border: 1px solid #d8dee7; border-radius: 8px; padding: 7px; }
QToolButton#iconButton:hover, QToolButton#viewButton:hover { background: #fff4f4; border-color: #f19b9e; }
QToolButton#viewButton:checked { background: #fff0f1; border-color: #ff535d; }
QMenu { background: #ffffff; border: 1px solid #d8dee7; padding: 6px; }
QMenu::item { padding: 9px 26px; }
QMenu::item:selected { background: #fff0f1; color: #ca3f46; }
QMenu::item:disabled { color: #9aa5b4; }
QPushButton:focus, QToolButton:focus { border-color: #d3424e; }
QToolButton#viewButton { padding: 0; border: 0; background: transparent; }
QToolButton#viewButton:checked { background: white; border: 1px solid #dce1e8; }
QFrame#inspectorContent { background: #ffffff; border: 0; }
QFrame#viewGroup { background: #edf0f4; border-radius: 8px; }
QComboBox { padding: 0 30px 0 12px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #fff0f1; selection-color: #a52c39; padding: 6px; border: 1px solid #dce1e8; }
QPushButton, QLineEdit { padding-top: 0; padding-bottom: 0; }
QLabel#eyebrow { font-size: 11px; letter-spacing: 0.8px; color: #637087; }
QLabel#muted, QLabel#counter { color: #637087; }
QToolButton#iconButton { padding: 0; background: transparent; border: 1px solid transparent; }
QToolButton#iconButton:hover { background: #f0f2f6; border-color: #dce1e8; }
QSplitter::handle { background: transparent; width: 12px; }
QFrame#sideCard { background: #f5f7fa; border: 0; }
QFrame#emptyCard { background: transparent; border: 0; }
QToolButton#export { padding: 0 36px 0 12px; font-size: 14px; }
QToolButton#export::menu-button:disabled { border-color: #dce1e8; }
QDialog, QMessageBox { background: #ffffff; color: #17233a; }
QDialog QLabel, QMessageBox QLabel { color: #17233a; background: transparent; }
QDialog QPlainTextEdit, QMessageBox QPlainTextEdit { background: #f8f9fc; color: #17233a; border: 1px solid #d8dee7; }
QDialog QPushButton, QMessageBox QPushButton { min-width: 92px; min-height: 36px; background: #ffffff; color: #26344b; border: 1px solid #cfd6e2; }
QDialog QPushButton:hover, QMessageBox QPushButton:hover { background: #fff0f1; border-color: #ff535d; color: #a52c39; }
QDialog QPushButton:default, QMessageBox QPushButton:default { background: #d93645; color: #ffffff; border-color: #d93645; }
QDialog QPushButton:default:hover, QMessageBox QPushButton:default:hover { background: #c22e3d; color: #ffffff; }
QDialogButtonBox { background: transparent; }
QMenu { color: #26344b; }
QMenu::separator { height: 1px; background: #edf0f4; margin: 5px 8px; }
QToolButton#languageButton { background: #ffffff; border: 1px solid #d8dee7; border-radius: 8px; padding: 0; }
QToolButton#languageButton:hover { background: #fff0f1; border-color: #ff535d; }
QWidget#playerSurface { background: #ffffff; }
QLabel#playerTitle { font-size: 17px; font-weight: 700; color: #17233a; }
QLabel#playerState { color: #637087; }
QSlider::groove:horizontal { height: 4px; background: #e7ebf0; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; border-radius: 7px; background: #d93645; }
QFrame#toast { background: #ffffff; border: 1px solid #bde9cb; border-left: 3px solid #219653; border-radius: 9px; }
QFrame#toast QLabel { color: #1e5c39; background: transparent; }
QFrame#toast QPushButton { min-width: 28px; min-height: 28px; border: 0; padding: 0; background: transparent; color: #357557; }
QFrame#toast QPushButton:hover { background: #eef9f1; }
'''



class ExplorerStyle(QProxyStyle):
    ICONS = {
        'SP_DialogOpenButton': 'folder-open-outline', 'SP_DirIcon': 'folder-outline',
        'SP_DirOpenIcon': 'folder-open-outline', 'SP_DirHomeIcon': 'account-outline',
        'SP_FileIcon': 'file-outline', 'SP_DialogSaveButton': 'export-variant',
        'SP_BrowserReload': 'refresh', 'SP_DialogHelpButton': 'help-circle-outline',
        'SP_FileDialogInfoView': 'information-outline', 'SP_FileDialogContentsView': 'view-grid-outline',
        'SP_FileDialogDetailedView': 'table', 'SP_FileDialogListView': 'format-list-bulleted',
        'SP_ComputerIcon': 'monitor', 'SP_DesktopIcon': 'home-outline',
        'SP_MediaVolume': 'music-note-outline', 'SP_DriveHDIcon': 'harddisk',
        'SP_TitleBarCloseButton': 'close', 'SP_DialogOkButton': 'check-circle-outline',
        'SP_MessageBoxWarning': 'alert-circle-outline', 'SP_MessageBoxInformation': 'information-outline',
    }
    def standardIcon(self, standard, option=None, widget=None):
        name = self.ICONS.get(standard.name)
        return qta.icon('mdi6.'+name, color='#657188') if name else super().standardIcon(standard, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_FrameFocusRect:
            return
        super().drawPrimitive(element, option, painter, widget)


def apply_light_theme(app=None):
    app = app or QApplication.instance()
    if app is None:
        return
    app.setStyle(ExplorerStyle('Fusion'))
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor('#ffffff'))
    palette.setColor(QPalette.ColorRole.Base, QColor('#ffffff'))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor('#f7f8fb'))
    palette.setColor(QPalette.ColorRole.Text, QColor('#17233a'))
    palette.setColor(QPalette.ColorRole.WindowText, QColor('#17233a'))
    palette.setColor(QPalette.ColorRole.Button, QColor('#ffffff'))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor('#26344b'))
    palette.setColor(QPalette.ColorRole.Highlight, QColor('#ff535d'))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor('#ffffff'))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor('#ffffff'))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor('#26344b'))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor('#9aa5b4'))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)
    app.setFont(QFont('Segoe UI Variable Text', 10))


class ElidedLabel(QLabel):
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setWordWrap(False)
    def minimumSizeHint(self):
        return QSize(0,20)
    def sizeHint(self):
        return QSize(120,20)
    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)
    def paintEvent(self, event):
        p = QPainter(self)
        p.setClipRect(self.rect())
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(self.contentsRect(), self.alignment() | Qt.AlignmentFlag.AlignVCenter,
                   self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideMiddle, self.contentsRect().width()))


class NavigationButton(QPushButton):
    def __init__(self, text, callback, depth=0):
        super().__init__(text)
        self.count = ''
        self.depth = depth
        self.expandable = False
        self.expanded = False
        self.setCheckable(True)
        self.setFixedHeight(34 if depth else 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(callback)

    def set_expandable(self, enabled: bool):
        self.expandable = enabled
        self.update()

    def set_expanded(self, expanded: bool):
        self.expanded = expanded
        self.update()

    def paintEvent(self, event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=QRectF(self.rect()).adjusted(1,1,-1,-1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#ffedf0' if self.isChecked() else '#f3f5f8' if self.underMouse() else '#ffffff'))
        p.drawRoundedRect(rect,8,8)
        if self.hasFocus() and self.testAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange):
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor('#d3424e'),1.5))
            p.drawRoundedRect(rect,8,8)
        if self.depth:
            p.setPen(QPen(QColor('#d9dfe8'), 1))
            p.drawLine(15, 6, 15, self.height() - 6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#df474d' if self.isChecked() else '#9aa5b4'))
            p.drawEllipse(QRectF(13, self.height() / 2 - 2, 4, 4))
            text_left = 28
        else:
            text_left = 44
            if self.expandable:
                p.setPen(QPen(QColor('#6f7b8e'), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                mid = self.height() / 2
                if self.expanded:
                    p.drawLine(8, mid - 2, 12, mid + 2)
                    p.drawLine(12, mid + 2, 16, mid - 2)
                else:
                    p.drawLine(9, mid - 3, 13, mid)
                    p.drawLine(13, mid, 9, mid + 3)
                self.icon().paint(p, 27, (self.height() - 20) // 2, 20, 20)
                text_left = 57
            else:
                self.icon().paint(p,12,(self.height() - 20) // 2,20,20)
        p.setPen(QColor('#b82e40' if self.isChecked() else '#344157'))
        font=QFont('Segoe UI',10);font.setWeight(QFont.Weight.DemiBold if self.isChecked() else QFont.Weight.Normal)
        p.setFont(font)
        p.drawText(self.rect().adjusted(text_left,0,-46,0),Qt.AlignmentFlag.AlignVCenter,self.text())
        font.setPointSize(9);font.setWeight(QFont.Weight.Normal);p.setFont(font)
        p.setPen(QColor('#ae4150' if self.isChecked() else '#738097'))
        p.drawText(self.rect().adjusted(0,0,-12,0),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,self.count)


class AssetGallery(QListWidget):
    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.reflow()
    def reflow(self):
        grid=self.viewMode()==QListView.ViewMode.IconMode
        width=max(1,self.viewport().width())
        columns=max(1,width//172)
        cell=QSize((width-2)//columns,184) if grid else QSize(width,76)
        self.setGridSize(cell)
        for i in range(self.count()):
            self.item(i).setSizeHint(cell)


class AssetPlayerDialog(QDialog):

    def __init__(self, path: Path, is_video: bool, translator: Translator, parent=None, temporary=False):
        super().__init__(parent)
        self.path = Path(path)
        self.temporary = temporary
        self.i18n = translator
        self.is_video = is_video
        self.is_playing = False
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.setObjectName('playerDialog')
        self.setWindowTitle(self.i18n.text('player.video' if is_video else 'player.audio'))
        self.setMinimumSize(520, 360 if is_video else 250)
        self.resize(760, 520 if is_video else 300)
        self.setModal(False)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)
        title_row = QHBoxLayout()
        title = QLabel(self.i18n.text('player.video' if is_video else 'player.audio'))
        title.setObjectName('playerTitle')
        title_row.addWidget(title, 1)
        name = QLabel(self.path.name)
        name.setObjectName('playerState')
        name.setToolTip(str(self.path))
        title_row.addWidget(name)
        root.addLayout(title_row)
        if is_video:
            self.video_surface = QVideoWidget()
            self.video_surface.setObjectName('playerSurface')
            self.video_surface.setMinimumHeight(180)
            self.player.setVideoOutput(self.video_surface)
            root.addWidget(self.video_surface, 1)
        else:
            surface = QFrame()
            surface.setObjectName('playerSurface')
            surface.setMinimumHeight(110)
            surface_layout = QVBoxLayout(surface)
            glyph = QLabel()
            glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            glyph.setPixmap(qta.icon('mdi6.music-note-outline', color='#d93645').pixmap(56, 56))
            surface_layout.addWidget(glyph)
            root.addWidget(surface, 1)
        self.state = QLabel(self.i18n.text('player.play'))
        self.state.setObjectName('playerState')
        root.addWidget(self.state)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.setEnabled(False)
        self.position_slider.sliderMoved.connect(self.player.setPosition)
        root.addWidget(self.position_slider)
        self.time_label = QLabel('00:00 / 00:00')
        self.time_label.setObjectName('playerState')
        root.addWidget(self.time_label)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.play_button = QPushButton(self.i18n.text('player.play'))
        self.play_button.setObjectName('primary')
        self.play_button.setIcon(qta.icon('mdi6.play', color='white'))
        self.play_button.clicked.connect(self.toggle_playback)
        controls.addWidget(self.play_button)
        self.stop_button = QPushButton(self.i18n.text('player.stop'))
        self.stop_button.setIcon(qta.icon('mdi6.stop', color='#657188'))
        self.stop_button.clicked.connect(self.stop)
        controls.addWidget(self.stop_button)
        controls.addStretch(1)
        root.addLayout(controls)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.errorOccurred.connect(self._media_error)
        self.player.setSource(QUrl.fromLocalFile(str(self.path)))

    @staticmethod
    def _format_time(milliseconds):
        seconds = max(0, int(milliseconds) // 1000)
        return f'{seconds // 60:02d}:{seconds % 60:02d}'

    def _position_changed(self, position):
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(position)
        self.time_label.setText(f'{self._format_time(position)} / {self._format_time(self.player.duration())}')

    def _duration_changed(self, duration):
        self.position_slider.setRange(0, max(0, duration))
        self.position_slider.setEnabled(duration > 0)
        self.time_label.setText(f'{self._format_time(self.player.position())} / {self._format_time(duration)}')

    def _media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.is_playing = False
            self.state.setText(self.i18n.text('player.play'))

    def _media_error(self, _error, _error_string):
        self.is_playing = False
        self.state.setText(self.i18n.text('player.error'))

    def toggle_playback(self):
        if self.is_playing:
            self.player.pause()
            self.is_playing = False
            self.state.setText(self.i18n.text('player.play'))
        else:
            self.player.play()
            self.is_playing = True
            self.state.setText(self.i18n.text('player.pause'))

    def stop(self):
        self.player.stop()
        self.is_playing = False
        self.state.setText(self.i18n.text('player.stop'))

    def closeEvent(self, event):
        self.stop()
        self.player.setSource(QUrl())
        if self.temporary:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
        super().closeEvent(event)


def show_app_message(parent, title: str, text: str, icon=QMessageBox.Icon.Information):
    box = QMessageBox(parent)
    box.setObjectName('appMessageBox')
    box.setWindowTitle(title)
    box.setText(text)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setIcon(icon)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.setDefaultButton(QMessageBox.StandardButton.Ok)
    box.exec()


class ToastWidget(QFrame):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('toast')
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAccessibleName('')
        self.setMinimumWidth(300)
        self.setMaximumWidth(460)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        layout.addWidget(self.icon)
        self.message = ElidedLabel('')
        self.message.setObjectName('toastText')
        self.message.setAccessibleName('')
        layout.addWidget(self.message, 1)
        self.close_button = QPushButton()
        self.close_button.setIcon(qta.icon('mdi6.close', color='#357557'))
        self.close_button.setIconSize(QSize(16, 16))
        self.close_button.setToolTip('')
        self.close_button.setAccessibleName('')
        self.close_button.clicked.connect(self.hide)
        layout.addWidget(self.close_button)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, text: str, error=False):
        self.message.setText(text)
        self.message.setAccessibleDescription(text)
        self.icon.setPixmap(qta.icon('mdi6.alert-circle-outline' if error else 'mdi6.check-circle-outline', color='#bd3948' if error else '#219653').pixmap(20, 20))
        self.setStyleSheet(STYLE + ('QFrame#toast { border-color: #f1bcc3; border-left-color: #bd3948; } QFrame#toast QLabel { color: #8f2938; }' if error else ''))
        self.adjustSize()
        if self.parentWidget() is not None:
            parent = self.parentWidget()
            self.move(max(16, parent.width() - self.width() - 24), max(16, parent.height() - self.height() - 54))
        self.raise_()
        self.show()
        self.timer.start(4200)

    def set_labels(self, notification: str, message: str, close: str):
        self.setAccessibleName(notification)
        self.message.setAccessibleName(message)
        self.close_button.setToolTip(close)
        self.close_button.setAccessibleName(close)


def label(text, name=None):
    widget = ElidedLabel(text) if name in {'assetTitle', 'infoValue', 'status'} else QLabel(text)
    widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    widget.setFixedHeight(40)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setIconSize(QSize(20,20))
    if primary:
        widget.setObjectName('primary')
    widget.clicked.connect(callback)
    return widget


def qt_image(image):
    rgba = image.convert('RGBA')
    raw = rgba.tobytes()
    return QImage(raw, rgba.width, rgba.height, rgba.width*4, QImage.Format.Format_RGBA8888).copy()


class Canvas(QWidget):
    viewChanged = Signal(str)

    def __init__(self, message='', accessible_name=''):
        super().__init__()
        self.image = None
        self.zoom = 1.0
        self.checker = True
        self.message = message
        self.pan = QPointF()
        self.drag_start = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName(accessible_name)
        self.setToolTip('')
        self.checker_tile=QPixmap(32,32)
        self.checker_tile.fill(QColor('#f9fbfd'))
        painter=QPainter(self.checker_tile)
        painter.fillRect(0,0,16,16,QColor('#e8eff6'))
        painter.fillRect(16,16,16,16,QColor('#e8eff6'))
        painter.end()
        self.setMinimumSize(240, 160)

    def fit_scale(self):
        if self.image is None:
            return 1.0
        return max(.001,min((self.width()-48)/self.image.width(),(self.height()-48)/self.image.height()))

    def reset_view(self):
        self.zoom=1.0
        self.pan=QPointF()
        self.update_view()

    def update_view(self):
        self.viewChanged.emit(f'{self.fit_scale()*self.zoom*100:.0f}%')
        self.update()

    def zoom_at(self, factor, position=None):
        if self.image is None:
            return
        center=QPointF(self.width()/2,self.height()/2)
        anchor=position if position is not None else center
        old=self.zoom
        self.zoom=max(.05,min(64.0,self.zoom*factor))
        self.pan=anchor-center-(anchor-center-self.pan)*(self.zoom/old)
        self.update_view()

    def wheelEvent(self,event):
        delta=event.angleDelta().y() or event.pixelDelta().y()*4
        self.zoom_at(1.18**max(-4,min(4,delta/120)),event.position())
        event.accept()

    def mousePressEvent(self,event):
        if event.button() in (Qt.MouseButton.LeftButton,Qt.MouseButton.MiddleButton):
            self.drag_start=event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.setFocus()
            event.accept()

    def mouseMoveEvent(self,event):
        if self.drag_start is not None:
            self.pan+=event.position()-self.drag_start
            self.drag_start=event.position()
            self.update()

    def mouseReleaseEvent(self,event):
        self.drag_start=None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self,event):
        self.reset_view()

    def keyPressEvent(self,event):
        key=event.key()
        if key in (Qt.Key.Key_Plus,Qt.Key.Key_Equal):
            self.zoom_at(1.2)
        elif key==Qt.Key.Key_Minus:
            self.zoom_at(1/1.2)
        elif key in (Qt.Key.Key_0,Qt.Key.Key_Home):
            self.reset_view()
        elif key==Qt.Key.Key_1:
            self.zoom=1/self.fit_scale()
            self.pan=QPointF()
            self.update_view()
        elif key in (Qt.Key.Key_Left,Qt.Key.Key_Right,Qt.Key.Key_Up,Qt.Key.Key_Down):
            shifts={Qt.Key.Key_Left:(32,0),Qt.Key.Key_Right:(-32,0),Qt.Key.Key_Up:(0,32),Qt.Key.Key_Down:(0,-32)}
            self.pan+=QPointF(*shifts[key])
            self.update()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self,event):
        self.viewChanged.emit(f'{self.fit_scale()*self.zoom*100:.0f}%')

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()),8,8)
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor('#f3f5f8'))
        if self.checker and self.image is not None:
            p.fillRect(self.rect(),QBrush(self.checker_tile))
        if self.image is not None:
            scale = self.fit_scale() * self.zoom
            w, h = self.image.width()*scale, self.image.height()*scale
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, max(self.image.width(), self.image.height())>256)
            p.drawImage(QRectF((self.width()-w)/2+self.pan.x(), (self.height()-h)/2+self.pan.y(), w, h), self.image)
        else:
            p.setPen(QColor('#607287'))
            p.drawText(self.rect().adjusted(24,24,-24,-24), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)
        p.end()


class AssetDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        rect = QRectF(option.rect).adjusted(4, 4, -4, -4)
        painter.setBrush(QColor('#fff5f5' if selected else '#ffffff'))
        painter.setPen(QPen(QColor('#ff535d' if selected else '#efb4b8' if hover else '#e2e6ed'), 1.5 if selected else 1))
        painter.drawRoundedRect(rect, 8, 8)
        grid = self.parent().viewMode() == QListView.ViewMode.IconMode
        preview = QRectF(rect.left()+8, rect.top()+8, rect.width()-16 if grid else 62, 116 if grid else rect.height()-16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#f3f5f8'))
        painter.drawRoundedRect(preview, 5, 5)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon and not icon.isNull():
            icon.paint(painter, preview.toRect(), Qt.AlignmentFlag.AlignCenter)
        else:
            item = index.data(Qt.ItemDataRole.UserRole)
            painter.setPen(QColor('#b65b63'))
            painter.drawText(preview, Qt.AlignmentFlag.AlignCenter, item.format_label if item else '…')
        x = rect.left()+10 if grid else preview.right()+12
        y = preview.bottom()+9 if grid else rect.top()+12
        width = rect.right()-x-8
        lines = index.data(Qt.ItemDataRole.DisplayRole).split('\n')
        font = QFont('Segoe UI', 9)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor('#19243b'))
        painter.drawText(QRectF(x,y,width,20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(lines[0], Qt.TextElideMode.ElideRight, int(width)))
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor('#6d788e'))
        painter.drawText(QRectF(x,y+22,width,18), Qt.AlignmentFlag.AlignLeft, lines[-1])
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QPen(QColor('#c83c42'), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(3,3,-3,-3), 6, 6)
        painter.restore()


class BrandMark(QWidget):

    def __init__(self, accessible_name=''):
        super().__init__()
        self.setFixedSize(46, 46)
        self.setAccessibleName(accessible_name)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        logo_path = Path(__file__).resolve().parent / 'assets' / 'branding' / 'logo.png'
        pixmap = QPixmap(str(logo_path))
        if not pixmap.isNull():
            pixmap = pixmap.scaled(46, 46, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((self.width() - pixmap.width()) // 2, (self.height() - pixmap.height()) // 2, pixmap)
        else:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor('#ff535d'))
            painter.drawEllipse(QRectF(2, 2, 42, 42))
            qta.icon('mdi6.horseshoe', color='#ffffff').paint(painter, 11, 10, 26, 26)
        painter.end()


class Studio(QMainWindow):
    def __init__(self, autostart=True):
        super().__init__()
        apply_light_theme()
        self.i18n = Translator('pt-BR')
        self.i18n.changed = self.apply_language
        self.playable_formats = {'Ogg', 'FLAC', 'WAV', 'RIFF', 'WebM'}
        self.player_dialog = None
        self._language_menu = None
        self.setWindowTitle(self.t('app.title'))
        self.resize(1280, 800)
        self.setMinimumSize(1040, 680)
        self.items = []
        self.matches = []
        self.folder = None
        self.section = 'Todos os assets'
        self.page = 0
        self.page_size = 48
        self.generation = 0
        self.selection_token = 0
        self.current = None
        self.current_data = None
        self.current_image = None
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.jobs = queue.Queue()
        self.render_queue = []
        self.render_busy = False
        self.pending_selection = None
        self.scanning = False
        self.source_stamps = {}
        self.discovering = False
        self.manual_choice = False
        self.preview_ready = False
        self.nav_count_labels = {}
        self.nav_group_layouts = {}
        self.nav_child_containers = {}
        self.nav_child_buttons = {}
        self.sidebar_filters = {name: set(section[0]) for name, section in SECTIONS.items()}
        self.sidebar_matchers = {name: (set(section[0]), None) for name, section in SECTIONS.items()}
        self.sidebar_labels = {name: self.t(SECTION_TITLE_KEYS.get(name, 'library')) for name in SECTIONS}
        self.sidebar_expanded = {}
        self.info_value_labels = {}
        self.info_caption_labels = {}
        self.nav_header = None
        self.help_button = None
        self.footer_status_is_version = True
        self.update_check_running = False
        self.home_card_labels = {}
        self.home_card_buttons = {}
        self._media_temp_files = set()
        self.build_ui()
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.drain)
        self.poll.start(16)
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(180)
        self.filter_timer.timeout.connect(self.filter_items)
        self.select_timer = QTimer(self)
        self.select_timer.setSingleShot(True)
        self.select_timer.setInterval(85)
        self.select_timer.timeout.connect(self.request_preview)
        QShortcut(QKeySequence('Ctrl+F'), self, activated=self.search.setFocus)
        QShortcut(QKeySequence('Ctrl+K'), self, activated=self.search.setFocus)
        QShortcut(QKeySequence('Ctrl+E'), self, activated=self.export)
        QShortcut(QKeySequence('Ctrl+Shift+C'), self, activated=self.copy_to_clipboard)
        QShortcut(QKeySequence('F5'),self,activated=self.refresh_catalog)
        if autostart:
            QTimer.singleShot(0, self.discover)
            QTimer.singleShot(1400, self.check_for_updates)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'toast') and self.toast.isVisible():
            self.toast.move(max(16, self.width() - self.toast.width() - 24), max(16, self.height() - self.toast.height() - 54))

    def t(self, key: str, **values) -> str:
        return self.i18n.text(key, **values)

    def version_text(self) -> str:
        return self.t('app.version', version=DISPLAY_VERSION)

    def section_description(self, name: str) -> str:
        return self.t(SECTION_DESCRIPTION_KEYS.get(name, 'library.description'))

    def category_label(self, category: str) -> str:
        return self.t(CATEGORY_LABEL_KEYS.get(category, 'category.unknown'))

    def show_toast(self, text: str, error=False):
        self.toast.show_message(text, error=error)

    def check_for_updates(self):
        if self.update_check_running:
            return
        self.update_check_running = True

        def work():
            latest = None
            try:
                request = urllib.request.Request(
                    f'https://api.github.com/repos/{REPOSITORY}/releases/latest',
                    headers={'Accept': 'application/vnd.github+json', 'User-Agent': APP_NAME},
                )
                with urllib.request.urlopen(request, timeout=4) as response:
                    payload = json.loads(response.read().decode('utf-8'))
                latest = str(payload.get('tag_name') or payload.get('name') or '').strip()
            except Exception:
                latest = None
            self.jobs.put(('update_check', latest))

        threading.Thread(target=work, daemon=True).start()

    def apply_language(self, _locale=None):
        self.setWindowTitle(self.t('app.title'))
        self.folder_field.setPlaceholderText(self.t('folder.placeholder'))
        self.browse_button.setToolTip(self.t('folder.choose'))
        self.browse_button.setAccessibleName(self.t('folder.choose'))
        self.language_button.setToolTip(self.t('folder.language'))
        self.language_button.setAccessibleName(self.t('folder.language'))
        self.toast.set_labels(
            self.t('toast.accessible'),
            self.t('toast.message.accessible'),
            self.t('toast.close'),
        )
        self.search.setPlaceholderText(self.t('search.placeholder'))
        self.search.setAccessibleName(self.t('search.accessible'))
        self.scan_button.setText(self.t('scan'))
        self.scan_button.setAccessibleName(self.t('scan.accessible'))
        self.nav_header.setText(self.t('library'))
        nav_keys = {
            'Todos os assets': 'all_assets', 'Imagens': 'images', 'Sprites': 'sprites',
            'Modelos': 'models', 'Áudio': 'audio', 'Interface': 'interface',
            'Personagens': 'characters',
            'Outros': 'other',
        }
        for internal, key in nav_keys.items():
            if internal in self.nav_buttons:
                self.nav_buttons[internal].setText(self.t(key))
        for children in self.nav_child_buttons.values():
            for child_id, (button, label_key) in children.items():
                button.setText(self.t(label_key))
                self.sidebar_labels[child_id] = self.t(label_key)
        if self.section in SECTION_TITLE_KEYS:
            self.heading.setText(self.t(SECTION_TITLE_KEYS[self.section]))
            self.description.setText(self.section_description(self.section))
        elif self.section in self.sidebar_labels:
            self.heading.setText(self.sidebar_labels[self.section])
        self.install_nav_button.setText(self.t('game_folder'))
        self.help_button.setText(self.t('help'))
        self.footer_brand.setText(self.t('app.title'))
        if self.footer_status_is_version:
            self.status.setText(self.version_text())
        if self.progress_text.isVisible():
            self.progress_text.setText(self.t('status.scanning'))
        if self.current is None:
            self.asset_title.setText(self.t('preview.empty'))
            self.canvas.message = self.t('empty.preview') if self.matches else self.t('empty.collection')
            self.canvas.update()
        self.preview_zoom_label.setText(self.t('preview.zoom'))
        self.fit_button.setText(self.t('preview.fit'))
        self.info_heading.setText(self.t('asset.info'))
        caption_keys = {
            'name': 'asset.filename', 'type': 'asset.type', 'size': 'asset.size',
            'dimensions': 'asset.dimensions', 'path': 'asset.path', 'category': 'asset.category',
        }
        for key, text_key in caption_keys.items():
            if key in self.info_caption_labels:
                self.info_caption_labels[key].setText(self.t(text_key))
        self.export_button.setText(self.t('export'))
        self.export_button.setAccessibleName(self.t('export.accessible'))
        self.copy_clipboard_action.setText(self.t('export.copy_clipboard'))
        for mode, text_key in {'png':'export.png','crop':'export.crop','webp':'export.webp','jpeg':'export.jpeg','raw':'export.raw','json':'export.json'}.items():
            self.export_actions[mode].setText(self.t(text_key))
        self.details_action.setText(self.t('export.details'))
        self.play_button.setText(self.t('player.play'))
        self.play_button.setToolTip(self.t('player.title'))
        self.canvas.setToolTip(self.t('preview.canvas.help'))
        self.canvas.setAccessibleName(self.t('preview.canvas.accessible'))
        self.grid_button.setToolTip(self.t('view.grid'))
        self.grid_button.setAccessibleName(self.t('view.grid'))
        self.list_button.setToolTip(self.t('view.list'))
        self.list_button.setAccessibleName(self.t('view.list'))
        self.filter_button.setToolTip(self.t('view.filter'))
        self.filter_button.setAccessibleName(self.t('view.filter'))
        self.order.setAccessibleName(self.t('sort.accessible'))
        for index, key in enumerate(('sort.name', 'sort.largest', 'sort.smallest')):
            self.order.setItemText(index, self.t(key))
        self.prev.setText(self.t('pager.previous'))
        self.next.setText(self.t('pager.next'))
        self.close_preview_button.setToolTip(self.t('selection.clear'))
        self.close_preview_button.setAccessibleName(self.t('selection.clear'))
        self.gallery.setAccessibleName(self.t('gallery.accessible'))
        self.details_button.setText(self.t('export.details'))
        self.empty_title.setText(self.t('empty.no_results') if self.items and not self.matches else self.t('empty.title'))
        self.empty_description.setText(self.t('empty.no_results.description') if self.items and not self.matches else self.t('empty.description'))
        self.empty_action.setText(self.t('empty.clear') if self.search.text() else self.t('empty.view_all') if self.items else self.t('empty.choose'))
        self.install_eyebrow.setText(self.t('install.eyebrow'))
        self.install_title.setText(self.t('install.title'))
        self.install_description.setText(self.t('install.description'))
        self.install_found.setText(self.t('install.found'))
        self.locations.setPlaceholderText(self.t('install.select'))
        self.detect_button.setText(self.t('install.retry'))
        self.choose_install_button.setText(self.t('folder.choose.short'))
        self.use_button.setText(self.t('install.use'))
        self.home_nav_button.setText(self.t('nav.home'))
        self.install_guide.setText(self.t('install.guide'))
        self.install_guide_text.setText(self.t('install.guide.text'))
        self.install_guide_note.setText(self.t('install.guide.note'))
        if self.current is None:
            self.asset_meta.setText(self.t('preview.empty.description'))
        self.home_eyebrow.setText(self.t('home.eyebrow'))
        self.home_title.setText(self.t('home.title'))
        self.home_description.setText(self.t('home.description'))
        self.home_start.setText(self.t('home.start'))
        self.home_search.setText(self.t('home.search'))
        self.home_explore_button.setText(self.t('home.explore'))
        self.home_choose_button.setText(self.t('folder.choose.short'))
        self.home_footer.setText(self.t('home.footer'))
        for name, (title, description) in self.home_card_labels.items():
            title_key = {'Cenários':'section.scenarios', 'Interface':'interface', 'Objetos e sprites':'section.objects'}[name]
            description_key = {'Cenários':'section.scenarios.description', 'Interface':'section.interface.description', 'Objetos e sprites':'section.objects.description'}[name]
            title.setText(self.t(title_key))
            description.setText(self.t(description_key))
            self.home_card_buttons[name].setText(self.t('collection.open'))
        self.status_count.setText(self.t('status.count', count=f'{len(self.items):,}'))
        if not self.folder:
            self.status_folder.setText(self.t('folder.none'))

    def choose_language(self):
        menu = QMenu(self)
        menu.setTitle(self.t('folder.language.menu'))
        for locale, name in LANGUAGES.items():
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(locale == self.i18n.locale)
            action.triggered.connect(lambda checked=False, loc=locale: self.i18n.set_locale(loc))
        self._language_menu = menu
        menu.exec(self.language_button.mapToGlobal(self.language_button.rect().bottomLeft()))

    def build_ui(self):
        shell = QWidget()
        shell.setObjectName('shell')
        self.setCentralWidget(shell)
        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        topbar = QFrame()
        topbar.setObjectName('topbar')
        topbar.setFixedHeight(88)
        header = QHBoxLayout(topbar)
        header.setContentsMargins(18, 14, 18, 13)
        header.setSpacing(12)

        brand_box = QHBoxLayout()
        brand_box.setContentsMargins(0, 0, 0, 0)
        brand_box.setSpacing(0)
        brand_box.addWidget(BrandMark(self.t('app.title')))
        brand_widget = QWidget()
        brand_widget.setLayout(brand_box)
        brand_widget.setFixedWidth(54)
        brand_widget.setToolTip(self.t('app.title'))
        brand_widget.setAccessibleName(self.t('app.title'))
        header.addWidget(brand_widget)

        folder_box = QVBoxLayout()
        folder_box.setContentsMargins(0, 0, 0, 0)
        folder_box.setSpacing(4)

        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.setSpacing(7)
        self.folder_field = QLineEdit()
        self.folder_field.setObjectName('folderField')
        self.folder_field.setReadOnly(True)
        self.folder_field.setPlaceholderText(self.t('folder.placeholder'))
        self.folder_field.setFixedHeight(40)
        self.folder_field.addAction(qta.icon('mdi6.folder-outline',color='#657188'),QLineEdit.ActionPosition.LeadingPosition)
        self.folder_field.setAccessibleName(self.t('folder.connected'))
        folder_row.addWidget(self.folder_field, 1)
        self.browse_button = button('', self.choose_folder)
        self.browse_button.setFixedWidth(40)
        self.browse_button.setToolTip(self.t('folder.choose'))
        self.browse_button.setAccessibleName(self.t('folder.choose'))
        self.browse_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        folder_row.addWidget(self.browse_button)
        self.language_button = QToolButton()
        self.language_button.setObjectName('languageButton')
        self.language_button.setFixedSize(40, 40)
        self.language_button.setIcon(qta.icon('mdi6.translate', color='#657188'))
        self.language_button.setIconSize(QSize(20, 20))
        self.language_button.setToolTip(self.t('folder.language'))
        self.language_button.setAccessibleName(self.t('folder.language'))
        self.language_button.clicked.connect(self.choose_language)
        folder_row.addWidget(self.language_button)
        folder_box.addLayout(folder_row)
        folder_widget = QWidget()
        folder_widget.setLayout(folder_box)
        header.addWidget(folder_widget, 1)

        self.search = QLineEdit()
        self.search.setObjectName('globalSearch')
        self.search.setPlaceholderText(self.t('search.placeholder'))
        self.search.setFixedHeight(40)
        self.search.addAction(qta.icon('mdi6.magnify',color='#657188'),QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(self.t('search.accessible'))
        self.search.setMinimumWidth(180)
        header.addWidget(self.search, 1)

        self.scan_button = button(self.t('scan'), self.scan_action, True)
        self.scan_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.scan_button.setAccessibleName(self.t('scan.accessible'))
        self.scan_button.setMinimumWidth(118)
        self.scan_button.setMinimumHeight(40)
        header.addWidget(self.scan_button)
        root.addWidget(topbar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        rail = QWidget()
        rail.setObjectName('rail')
        rail.setMinimumWidth(208)
        nav = QVBoxLayout(rail)
        nav.setContentsMargins(12, 20, 12, 12)
        nav.setSpacing(3)
        self.home_nav_button = button(self.t('nav.home'), lambda: self.navigate('Início'))
        self.home_nav_button.setObjectName('nav')
        self.home_nav_button.setCheckable(True)
        self.home_nav_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DesktopIcon))
        self.home_nav_button.setIconSize(QSize(19, 19))
        self.nav_buttons = {'Início': self.home_nav_button}
        self.home_nav_button.hide()
        icon_names = {
            'Todos os assets': QStyle.StandardPixmap.SP_FileDialogInfoView,
            'Imagens': QStyle.StandardPixmap.SP_FileDialogContentsView,
            'Sprites': QStyle.StandardPixmap.SP_FileDialogListView,
            'Modelos': QStyle.StandardPixmap.SP_ComputerIcon,
            'Áudio': QStyle.StandardPixmap.SP_MediaVolume,
            'Interface': QStyle.StandardPixmap.SP_FileDialogDetailedView,
            'Personagens': QStyle.StandardPixmap.SP_DirHomeIcon,
            'Outros': QStyle.StandardPixmap.SP_FileIcon,
        }
        self.nav_header = label(self.t('library'), 'eyebrow')
        nav.addWidget(self.nav_header)
        nav.addSpacing(8)
        self.nav_layout = nav
        for name, _ in SIDEBAR_ITEMS:
            group = QWidget()
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(2)
            b = NavigationButton(name, lambda checked=False, n=name: self.category_clicked(n))
            self.nav_buttons[name] = b
            self.nav_count_labels[name] = b
            group_layout.addWidget(b)
            children = QWidget()
            children_layout = QVBoxLayout(children)
            children_layout.setContentsMargins(20, 0, 0, 0)
            children_layout.setSpacing(2)
            children.hide()
            group_layout.addWidget(children)
            nav.addWidget(group)
            self.nav_group_layouts[name] = group_layout
            self.nav_child_containers[name] = (children, children_layout)
            self.nav_child_buttons[name] = {}
        nav.addSpacing(10)
        self.install_nav_button = NavigationButton(self.t('game_folder'), lambda: self.navigate('Instalação'))
        self.install_nav_button.setObjectName('nav')
        self.install_nav_button.setCheckable(True)
        self.install_nav_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.install_nav_button.setIconSize(QSize(19, 19))
        self.nav_buttons['Instalação'] = self.install_nav_button
        nav.addWidget(self.install_nav_button)
        nav.addStretch()
        self.help_button = button(self.t('help'), self.help)
        self.help_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton))
        nav.addWidget(self.help_button)
        rail_scroll = QScrollArea()
        rail_scroll.setFixedWidth(232)
        rail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rail_scroll.setWidgetResizable(True)
        rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rail_scroll.setStyleSheet('QScrollArea { border: 0; background: white; }')
        rail_scroll.setWidget(rail)
        body_layout.addWidget(rail_scroll)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 18, 18, 10)
        content_layout.setSpacing(0)
        self.pages = QStackedWidget()
        content_layout.addWidget(self.pages, 1)
        body_layout.addWidget(content, 1)
        root.addWidget(body, 1)

        statusbar = QFrame()
        statusbar.setObjectName('statusbar')
        statusbar.setStyleSheet('QFrame#statusbar { background: #ffffff; border-top: 1px solid #e5e8ee; }')
        statusbar.setMinimumHeight(40)
        status_layout = QHBoxLayout(statusbar)
        status_layout.setContentsMargins(18, 0, 18, 0)
        status_layout.setSpacing(9)
        status_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(8, 8)
        self.status_indicator.setStyleSheet('background: #2aa45a; border-radius: 4px;')
        self.status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self.status_indicator)
        self.status = label(self.version_text(), 'status')
        self.status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status.setWordWrap(False)
        self.status.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Preferred)
        self.status.setFixedWidth(150)
        status_layout.addWidget(self.status)
        status_layout.addWidget(self.footer_separator())
        self.status_count = label(self.t('status.count', count=0), 'status')
        self.status_count.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status_count.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Preferred)
        self.status_count.setFixedWidth(88)
        status_layout.addWidget(self.status_count)
        status_layout.addWidget(self.footer_separator())
        self.status_folder = label(self.t('folder.none'), 'status')
        self.status_folder.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status_folder.setWordWrap(False)
        self.status_folder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        status_layout.addWidget(self.status_folder, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(150)
        self.progress.setFixedHeight(6)
        self.progress.setVisible(False)
        status_layout.addWidget(self.progress)
        self.progress_text = label('', 'status')
        self.progress_text.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.progress_text.setWordWrap(False)
        self.progress_text.setFixedWidth(108)
        self.progress_text.setVisible(False)
        status_layout.insertWidget(status_layout.indexOf(self.progress), self.progress_text)
        self.footer_brand = label(self.t('app.title'), 'status')
        self.footer_brand.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.footer_brand.setWordWrap(False)
        self.footer_brand.setFixedWidth(112)
        status_layout.addWidget(self.footer_brand)
        root.addWidget(statusbar)
        self.toast = ToastWidget(self)
        self.toast.set_labels(
            self.t('toast.accessible'),
            self.t('toast.message.accessible'),
            self.t('toast.close'),
        )
        self.build_home()
        self.build_library()
        self.build_install()
        icons = ['view-grid-outline', 'image-outline', 'filmstrip', 'cube-outline',
                 'music-note-outline', 'application-outline', 'account-group-outline', 'file-outline']
        for (name, _), icon in zip(SIDEBAR_ITEMS, icons):
            self.nav_buttons[name].setIcon(qta.icon('mdi6.'+icon, color='#69758b', color_active='#e44954'))
        self.browse_button.setIcon(qta.icon('mdi6.folder-outline', color='#69758b'))
        self.scan_button.setIcon(qta.icon('mdi6.magnify', color='white'))
        self.grid_button.setIcon(qta.icon('mdi6.view-grid-outline', color='#26344b'))
        self.list_button.setIcon(qta.icon('mdi6.format-list-bulleted', color='#26344b'))
        self.install_nav_button.setIcon(qta.icon('mdi6.folder-cog-outline', color='#69758b'))
        self.export_button.setIcon(qta.icon('mdi6.export-variant', color='white'))
        self.export_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.export_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.export_button.setMinimumHeight(48)
        self.navigate('Todos os assets')

    @staticmethod
    def footer_separator():
        separator = QFrame()
        separator.setObjectName('footerSeparator')
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        separator.setFixedSize(1, 14)
        separator.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return separator

    def build_home(self):
        home = QWidget()
        layout = QVBoxLayout(home)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(14)
        self.home_eyebrow = label(self.t('home.eyebrow'), 'eyebrow')
        self.home_title = label(self.t('home.title'), 'heroTitle')
        self.home_description = label(self.t('home.description'), 'muted')
        layout.addWidget(self.home_eyebrow)
        layout.addWidget(self.home_title)
        layout.addWidget(self.home_description)
        layout.addSpacing(8)

        hero = QHBoxLayout()
        hero.setSpacing(14)
        intro_card = QFrame()
        intro_card.setObjectName('panel')
        intro = QVBoxLayout(intro_card)
        intro.setContentsMargins(18, 18, 18, 18)
        intro.setSpacing(10)
        self.home_start = label(self.t('home.start'), 'eyebrow')
        intro.addWidget(self.home_start)
        self.home_summary = label(self.t('home.summary'), 'sectionTitle')
        intro.addWidget(self.home_summary)
        self.home_search = label(self.t('home.search'), 'muted')
        intro.addWidget(self.home_search)
        intro.addStretch()
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.home_explore_button = button(self.t('home.explore'), lambda: self.navigate('Personagens'), True)
        self.home_choose_button = button(self.t('folder.choose.short'), self.choose_folder)
        action_row.addWidget(self.home_explore_button)
        action_row.addWidget(self.home_choose_button)
        intro.addLayout(action_row)
        hero.addWidget(intro_card, 1)

        banner_card = QFrame()
        banner_card.setObjectName('panel')
        banner_box = QVBoxLayout(banner_card)
        banner_box.setContentsMargins(8, 8, 8, 8)
        banner = Canvas(accessible_name=self.t('app.title'))
        banner.image = QImage(str(Path(__file__).resolve().parent / 'assets' / 'branding' / 'banner.jpeg'))
        if banner.image.isNull():
            banner.image = None
        banner.checker = False
        banner.setMinimumSize(380, 240)
        banner_box.addWidget(banner)
        hero.addWidget(banner_card, 1)
        layout.addLayout(hero, 1)

        section_row = QHBoxLayout()
        section_row.setSpacing(10)
        for name, title_key, description_key in [
            ('Cenários', 'section.scenarios', 'section.scenarios.description'),
            ('Interface', 'interface', 'section.interface.description'),
            ('Objetos e sprites', 'section.objects', 'section.objects.description'),
        ]:
            card = QFrame()
            card.setObjectName('panel')
            box = QVBoxLayout(card)
            box.setContentsMargins(14, 13, 14, 13)
            box.setSpacing(6)
            title = label(self.t(title_key), 'sectionTitle')
            description = label(self.t(description_key), 'muted')
            open_button = button(self.t('collection.open'), lambda checked=False, n=name: self.navigate(n))
            box.addWidget(title)
            box.addWidget(description)
            box.addWidget(open_button)
            self.home_card_labels[name] = (title, description)
            self.home_card_buttons[name] = open_button
            section_row.addWidget(card)
        layout.addLayout(section_row)
        self.home_footer = label(self.t('home.footer'), 'muted')
        layout.addWidget(self.home_footer)
        self.pages.addWidget(home)

    def build_library(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 2)
        titles = QVBoxLayout()
        titles.setSpacing(3)
        self.heading = label(self.t('characters'), 'title')
        self.description = label(self.section_description('Personagens'), 'muted')
        titles.addWidget(self.heading)
        titles.addWidget(self.description)
        head.addLayout(titles,1)
        self.counter = label(self.t('status.count', count=0), 'counter')
        self.counter.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.counter)
        tools = QHBoxLayout()
        tools.setSpacing(7)
        view_group = QFrame()
        view_group.setObjectName('viewGroup')
        view_group.setFixedHeight(40)
        view_layout = QHBoxLayout(view_group)
        view_layout.setContentsMargins(3, 3, 3, 3)
        view_layout.setSpacing(4)
        self.grid_button = QToolButton()
        self.grid_button.setObjectName('viewButton')
        self.grid_button.setCheckable(True)
        self.grid_button.setChecked(True)
        self.grid_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView))
        self.grid_button.setIconSize(QSize(18, 18))
        self.grid_button.setToolTip(self.t('view.grid'))
        self.grid_button.setAccessibleName(self.t('view.grid'))
        self.grid_button.clicked.connect(lambda: self.set_gallery_view('grid'))
        self.list_button = QToolButton()
        self.list_button.setObjectName('viewButton')
        self.list_button.setCheckable(True)
        self.list_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView))
        self.list_button.setIconSize(QSize(18, 18))
        self.list_button.setToolTip(self.t('view.list'))
        self.list_button.setAccessibleName(self.t('view.list'))
        self.list_button.clicked.connect(lambda: self.set_gallery_view('list'))
        view_layout.addWidget(self.grid_button)
        view_layout.addWidget(self.list_button)
        tools.addWidget(view_group)
        self.order = QComboBox()
        self.order.addItems([self.t('sort.name'), self.t('sort.largest'), self.t('sort.smallest')])
        self.order.setAccessibleName(self.t('sort.accessible'))
        self.order.setFixedHeight(40)
        self.order.setMinimumWidth(172)
        self.order.currentIndexChanged.connect(lambda: self.filter_timer.start())
        tools.addWidget(self.order)
        self.filter_button = QToolButton()
        self.filter_button.setObjectName('viewButton')
        self.filter_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.filter_button.setIconSize(QSize(18, 18))
        self.filter_button.setToolTip(self.t('view.filter'))
        self.filter_button.setAccessibleName(self.t('view.filter'))
        tools.addWidget(self.filter_button)
        tools.addStretch()
        self.filter_button.hide()
        self.grid_button.setFixedSize(34,34)
        self.list_button.setFixedSize(34,34)

        split = QSplitter()
        left = QWidget()
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 10, 0)
        left_box.setSpacing(16)
        left_box.addLayout(head)
        left_box.addLayout(tools)
        self.gallery_empty = QFrame()
        self.gallery_empty.setObjectName('emptyCard')
        empty_layout = QVBoxLayout(self.gallery_empty)
        empty_layout.setContentsMargins(14, 12, 14, 12)
        empty_layout.setSpacing(3)
        empty_layout.addStretch()
        empty_icon = QLabel()
        empty_icon.setPixmap(qta.icon('mdi6.image-search-outline',color='#a0aabd').pixmap(48,48))
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_icon)
        empty_layout.addSpacing(12)
        self.empty_title = label(self.t('empty.title'), 'sectionTitle')
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_description = label(self.t('empty.description'), 'muted')
        self.empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_description)
        empty_layout.addSpacing(16)
        self.empty_action = button(self.t('empty.choose'), self.empty_action_clicked, True)
        empty_layout.addWidget(self.empty_action,0,Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch()
        self.gallery_empty.setVisible(False)

        self.gallery = AssetGallery()
        self.gallery.setObjectName('gallery')
        self.gallery.setItemDelegate(AssetDelegate(self.gallery))
        self.gallery.setAccessibleName(self.t('gallery.accessible'))
        self.gallery.setViewMode(QListView.ViewMode.IconMode)
        self.gallery.setResizeMode(QListView.ResizeMode.Adjust)
        self.gallery.setMovement(QListView.Movement.Static)
        self.gallery.setIconSize(QSize(138, 108))
        self.gallery.setGridSize(QSize(166, 168))
        self.gallery.setSpacing(0)
        self.gallery.setMouseTracking(True)
        self.gallery.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.gallery.setUniformItemSizes(True)
        self.gallery.setWordWrap(True)
        self.gallery.setWrapping(True)
        self.gallery.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.gallery.currentItemChanged.connect(self.selected)
        self.gallery.verticalScrollBar().valueChanged.connect(self.prioritize_visible)
        self.gallery_stack = QStackedWidget()
        self.gallery_stack.addWidget(self.gallery_empty)
        self.gallery_stack.addWidget(self.gallery)
        left_box.addWidget(self.gallery_stack,1)
        pager = QHBoxLayout()
        pager.setSpacing(7)
        self.prev = button(self.t('pager.previous'), lambda: self.turn_page(-1))
        self.next = button(self.t('pager.next'), lambda: self.turn_page(1))
        self.page_label = label('', 'muted')
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prev.setFixedWidth(96)
        self.next.setFixedWidth(96)
        pager.addWidget(self.prev)
        pager.addWidget(self.page_label, 1)
        pager.addWidget(self.next)
        left_box.addLayout(pager)
        split.addWidget(left)

        inspector = QFrame()
        inspector.setObjectName('panel')
        inspector.setMinimumWidth(328)
        inspector.setMaximumWidth(520)
        box = QVBoxLayout(inspector)
        box.setContentsMargins(16, 16, 16, 16)
        box.setSpacing(12)
        inspector_head = QHBoxLayout()
        inspector_head.setContentsMargins(0, 0, 0, 0)
        self.asset_title = label(self.t('preview.empty'), 'assetTitle')
        self.asset_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        inspector_head.addWidget(self.asset_title, 1)
        self.close_preview_button = QToolButton()
        self.close_preview_button.setObjectName('iconButton')
        self.close_preview_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton))
        self.close_preview_button.setIconSize(QSize(20, 20))
        self.close_preview_button.setFixedSize(32,32)
        self.close_preview_button.setToolTip(self.t('selection.clear'))
        self.close_preview_button.setAccessibleName(self.t('selection.clear'))
        self.close_preview_button.clicked.connect(self.clear_selection)
        inspector_head.addWidget(self.close_preview_button)
        box.addLayout(inspector_head)
        self.canvas = Canvas(self.t('empty.preview'), self.t('preview.canvas.accessible'))
        self.canvas.setToolTip(self.t('preview.canvas.help'))
        self.canvas.setMinimumHeight(160)
        self.canvas.setMaximumHeight(280)
        box.addWidget(self.canvas,1)
        self.asset_meta = label(self.t('preview.empty.description'), 'muted')
        self.asset_meta.hide()
        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.preview_zoom_label = label(self.t('preview.zoom'), 'muted')
        controls.addWidget(self.preview_zoom_label, 1)
        self.zoom_label = label('100%', 'muted')
        self.canvas.viewChanged.connect(self.zoom_label.setText)
        controls.addWidget(self.zoom_label, 0)
        self.fit_button = button(self.t('preview.fit'), self.canvas.reset_view)
        self.fit_button.setFixedHeight(32)
        self.fit_button.setIcon(qta.icon('mdi6.fit-to-screen-outline',color='#657188'))
        controls.addWidget(self.fit_button)
        box.addLayout(controls)

        self.info_heading = label(self.t('asset.info'), 'sectionTitle')
        box.addWidget(self.info_heading)
        self.info_card = QFrame()
        self.info_card.setObjectName('infoCard')
        info_box = QVBoxLayout(self.info_card)
        info_box.setContentsMargins(0, 0, 0, 0)
        info_box.setSpacing(0)
        info_rows = [
            ('name', 'asset.filename', QStyle.StandardPixmap.SP_FileIcon),
            ('type', 'asset.type', QStyle.StandardPixmap.SP_FileDialogInfoView),
            ('size', 'asset.size', QStyle.StandardPixmap.SP_DriveHDIcon),
            ('dimensions', 'asset.dimensions', QStyle.StandardPixmap.SP_FileDialogDetailedView),
            ('path', 'asset.path', QStyle.StandardPixmap.SP_DirIcon),
            ('category', 'asset.category', QStyle.StandardPixmap.SP_FileDialogContentsView),
        ]
        for key, caption, icon_name in info_rows:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(7)
            caption_label = label(self.t(caption), 'infoLabel')
            caption_label.setFixedSize(104,30)
            row.addWidget(caption_label)
            self.info_caption_labels[key] = caption_label
            value = label('-', 'infoValue')
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setWordWrap(False)
            value.setMinimumHeight(30)
            row.addWidget(value, 1)
            info_box.addLayout(row)
            self.info_value_labels[key] = value
        box.addWidget(self.info_card)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.export_button = QToolButton()
        self.export_button.setObjectName('export')
        self.export_button.setText(self.t('export'))
        self.export_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.export_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.export_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.export_button.clicked.connect(lambda: self.export())
        self.export_button.setAccessibleName(self.t('export.accessible'))
        self.export_button.setMinimumHeight(42)
        self.export_menu=QMenu(self.export_button)
        self.image_export_actions=[]
        self.export_actions = {}
        for text_key,mode in [('export.png','png'),('export.crop','crop'),('export.webp','webp'),('export.jpeg','jpeg'),('export.raw','raw'),('export.json','json')]:
            action=self.export_menu.addAction(self.t(text_key),lambda checked=False,m=mode:self.export(m))
            self.export_actions[mode] = action
            if mode not in {'raw','json'}:
                self.image_export_actions.append(action)
        self.export_button.setMenu(self.export_menu)
        self.export_button.setEnabled(False)
        self.copy_clipboard_action = self.export_menu.addAction(self.t('export.copy_clipboard'), self.copy_to_clipboard)
        self.copy_clipboard_action.setIcon(qta.icon('mdi6.content-copy', color='#657188'))
        self.copy_clipboard_action.setEnabled(False)
        self.export_menu.addSeparator()
        self.play_button = QPushButton(self.t('player.play'))
        self.play_button.setIcon(qta.icon('mdi6.play-outline', color='#657188'))
        self.play_button.setToolTip(self.t('player.title'))
        self.play_button.clicked.connect(self.play_current_asset)
        self.play_button.setEnabled(False)
        self.play_button.setVisible(False)
        actions.addWidget(self.export_button, 1)
        self.details_button = button(self.t('export.details'), self.details)
        self.details_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView))
        self.details_button.setEnabled(False)
        self.details_button.hide()
        self.details_action = self.export_menu.addAction(self.t('export.details'), self.details)

        inspector_scroll = QScrollArea()
        inspector_scroll.setFrameShape(QFrame.Shape.NoFrame)
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setMinimumWidth(328)
        inspector_scroll.setStyleSheet('QScrollArea { background: transparent; border: 0; }')
        inspector_scroll.setWidget(inspector)
        inspector_shell = QFrame()
        inspector_shell.setObjectName('panel')
        inspector_shell.setMinimumWidth(336)
        inspector_layout = QVBoxLayout(inspector_shell)
        inspector_layout.setContentsMargins(0,0,0,0)
        inspector_layout.setSpacing(0)
        inspector.setObjectName('inspectorContent')
        inspector_layout.addWidget(inspector_scroll,1)
        footer = QWidget()
        footer_box = QVBoxLayout(footer)
        footer_box.setContentsMargins(16,12,16,16)
        footer_box.addWidget(self.play_button)
        footer_box.addLayout(actions)
        inspector_layout.addWidget(footer)
        split.addWidget(inspector_shell)
        split.setChildrenCollapsible(False)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([720, 360])
        layout.addWidget(split,1)
        self.search.textChanged.connect(lambda: self.filter_timer.start())
        self.pages.addWidget(page)

    def build_install(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 4, 0, 8)
        box.setSpacing(10)
        self.install_eyebrow = label(self.t('install.eyebrow'), 'eyebrow')
        self.install_title = label(self.t('install.title'), 'heroTitle')
        self.install_description = label(self.t('install.description'), 'muted')
        box.addWidget(self.install_eyebrow)
        box.addWidget(self.install_title)
        box.addWidget(self.install_description)
        box.addSpacing(10)

        card = QFrame()
        card.setObjectName('panel')
        card_box = QVBoxLayout(card)
        card_box.setContentsMargins(18, 18, 18, 18)
        card_box.setSpacing(12)
        self.install_found = label(self.t('install.found'), 'eyebrow')
        card_box.addWidget(self.install_found)
        self.location_label = label(self.t('discover.searching'))
        self.location_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card_box.addWidget(self.location_label)
        self.locations = QComboBox()
        self.locations.setFixedHeight(40)
        self.locations.setPlaceholderText(self.t('install.select'))
        card_box.addWidget(self.locations)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.detect_button = button(self.t('install.retry'), self.discover)
        self.detect_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        row.addWidget(self.detect_button,1)
        self.choose_install_button = button(self.t('folder.choose.short'), self.choose_folder, True)
        self.choose_install_button.setIcon(qta.icon('mdi6.folder-open-outline',color='white'))
        row.addWidget(self.choose_install_button,1)
        self.use_button = button(self.t('install.use'), self.use_location)
        self.use_button.setEnabled(False)
        self.locations.currentIndexChanged.connect(lambda: self.use_button.setEnabled(self.locations.currentData() is not None))
        row.addWidget(self.use_button,1)
        card_box.addLayout(row)
        box.addWidget(card)

        guide = QFrame()
        guide.setObjectName('infoCard')
        guide_box = QVBoxLayout(guide)
        guide_box.setContentsMargins(16, 14, 16, 14)
        guide_box.setSpacing(6)
        self.install_guide = label(self.t('install.guide'), 'sectionTitle')
        self.install_guide_text = label(self.t('install.guide.text'), 'muted')
        self.install_guide_note = label(self.t('install.guide.note'), 'muted')
        guide_box.addWidget(self.install_guide)
        guide_box.addWidget(self.install_guide_text)
        guide_box.addWidget(self.install_guide_note)
        box.addWidget(guide)
        box.addStretch()
        self.pages.addWidget(page)

    def standard_icon(self, icon_name, size=18):
        return self.style().standardIcon(icon_name).pixmap(size, size)

    def set_gallery_view(self, mode):
        is_grid = mode == 'grid'
        self.grid_button.setChecked(is_grid)
        self.list_button.setChecked(not is_grid)
        if is_grid:
            self.gallery.setViewMode(QListView.ViewMode.IconMode)
            self.gallery.setIconSize(QSize(138, 108))
            self.gallery.setGridSize(QSize(166, 168))
            self.gallery.setWordWrap(True)
            self.gallery.setWrapping(True)
        else:
            self.gallery.setViewMode(QListView.ViewMode.ListMode)
            self.gallery.setIconSize(QSize(72, 58))
            self.gallery.setGridSize(QSize(0, 74))
            self.gallery.setWordWrap(False)
            self.gallery.setWrapping(False)
        self.gallery.reflow()

    def clear_selection(self):
        self.gallery.setCurrentRow(-1)
        self.current = None
        self.current_data = None
        self.current_image = None
        self.preview_ready = False
        self.canvas.image = None
        self.canvas.message = self.t('empty.preview')
        self.canvas.reset_view()
        self.asset_title.setText(self.t('preview.empty'))
        self.asset_meta.setText(self.t('preview.empty.description'))
        self.close_preview_button.setVisible(False)
        self.export_button.setEnabled(False)
        self.copy_clipboard_action.setEnabled(False)
        self.play_button.setEnabled(False)
        self.play_button.setVisible(False)
        self.details_button.setEnabled(False)
        self.update_info_panel(None)

    def update_info_panel(self, item):
        if item is None:
            values = {'name': '-', 'type': '-', 'size': '-', 'dimensions': '-', 'path': '-', 'category': '-'}
        else:
            picture = self.current_image
            values = {
                'name': Path(item.relative).name,
                'type': item.format_label,
                'size': engine.human_size(item.size),
                'dimensions': f'{picture.width()} × {picture.height()}' if picture is not None else self.t('asset.not_available'),
                'path': item.relative.replace('\\', '/'),
                'category': self.category_label(item.category),
            }
        for key, value in values.items():
            widget = self.info_value_labels.get(key)
            if widget is not None:
                widget.setToolTip(value)
                widget.setText(value)

    def category_clicked(self, name):
        self.navigate(name)
        children = self.nav_child_buttons.get(name, {})
        if children:
            self.set_category_expanded(name, not self.sidebar_expanded.get(name, False))

    def set_category_expanded(self, name, expanded):
        children = self.nav_child_buttons.get(name, {})
        container_layout = self.nav_child_containers.get(name)
        if not children or container_layout is None:
            expanded = False
        if container_layout is not None:
            container_layout[0].setVisible(expanded)
        self.sidebar_expanded[name] = expanded
        button = self.nav_buttons.get(name)
        if button is not None:
            button.set_expandable(bool(children))
            button.set_expanded(expanded)

    def rebuild_sidebar_subcategories(self):
        self.sidebar_filters = {name: set(section[0]) for name, section in SECTIONS.items()}
        self.sidebar_matchers = {name: (set(section[0]), None) for name, section in SECTIONS.items()}
        self.sidebar_labels = {name: self.t(SECTION_TITLE_KEYS.get(name, 'library')) for name in SECTIONS}
        if self.section not in self.sidebar_matchers:
            self.section = 'Todos os assets'
            for key, button in self.nav_buttons.items():
                button.setChecked(key == self.section)
        for root_name, children in self.nav_child_buttons.items():
            for child_id in children:
                self.nav_buttons.pop(child_id, None)
                self.nav_count_labels.pop(child_id, None)
            child_container, child_layout = self.nav_child_containers[root_name]
            while child_layout.count():
                item = child_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.nav_child_buttons[root_name] = {}
            self.set_category_expanded(root_name, False)

        for root_name, _ in SIDEBAR_ITEMS:
            if root_name == 'Todos os assets':
                continue
            root_categories = set(SECTIONS[root_name][0])
            root_items = [item for item in self.items if item.category in root_categories]
            if len(root_items) < 6:
                continue
            minimum = max(3, (len(root_items) + 32) // 33)
            category_counts = Counter(item.category for item in root_items)
            nonempty = [(category, count) for category, count in category_counts.items() if count >= minimum]
            candidates = []

            if len(nonempty) >= 2:
                for category, count in sorted(nonempty, key=lambda pair: (-pair[1], pair[0])):
                    if category in {'Texturas', 'Sprites'}:
                        grouped = Counter(infer_subcategory_key(item) for item in root_items if item.category == category)
                        useful = [(key, count_value) for key, count_value in grouped.items() if key and count_value >= minimum]
                        if len(useful) >= 2:
                            for key, grouped_count in sorted(useful, key=lambda pair: (-pair[1], pair[0])):
                                candidates.append((key, {category}, key, grouped_count))
                            continue
                    label_key = SEMANTIC_SUBCATEGORY_KEYS.get(category)
                    if label_key:
                        candidates.append((label_key, {category}, None, count))
            elif len(nonempty) == 1:
                category, _category_count = nonempty[0]
                grouped = Counter(infer_subcategory_key(item) for item in root_items if item.category == category)
                useful = [(key, count) for key, count in grouped.items() if key and count >= minimum]
                if len(useful) >= 2:
                    for key, count in sorted(useful, key=lambda pair: (-pair[1], pair[0])):
                        candidates.append((key, {category}, key, count))
                    assigned = sum(count for _key, count in useful)
                    remaining = len(root_items) - assigned
                    if remaining >= minimum:
                        fallback_key = {
                            'Personagens': 'subcat.characters.other',
                            'UI': 'subcat.ui.other',
                            'Sprites': 'subcat.sprites.other',
                            'Texturas': 'subcat.textures.other',
                            'Áudio': 'subcat.audio.other',
                            'Efeitos': 'subcat.effects.other',
                        }.get(category, 'subcat.other')
                        candidates.append((fallback_key, {category}, '__unclassified__', remaining))

            for label_key, categories, subcategory_key, count in candidates:
                child_id = f'{root_name}::{label_key}'
                button = NavigationButton(self.t(label_key), lambda checked=False, n=child_id: self.navigate(n), depth=1)
                button.setObjectName('navChild')
                button.count = f'{count:,}'.replace(',', '.')
                self.nav_child_containers[root_name][1].addWidget(button)
                self.nav_child_buttons[root_name][child_id] = (button, label_key)
                self.nav_buttons[child_id] = button
                self.nav_count_labels[child_id] = button
                self.sidebar_labels[child_id] = self.t(label_key)
                self.sidebar_filters[child_id] = set(categories)
                self.sidebar_matchers[child_id] = (set(categories), subcategory_key)

            self.set_category_expanded(root_name, bool(candidates) and self.sidebar_expanded.get(root_name, False))

    def item_matches_section(self, item, section):
        categories, subcategory_key = self.sidebar_matchers.get(section, (set(), None))
        if item.category not in categories:
            return False
        if subcategory_key is None:
            return True
        inferred = infer_subcategory_key(item)
        return inferred is None if subcategory_key == '__unclassified__' else inferred == subcategory_key

    def update_sidebar_counts(self):
        for name, _ in SIDEBAR_ITEMS:
            count = len(self.items) if name == 'Todos os assets' else sum(1 for item in self.items if self.item_matches_section(item, name))
            if name in self.nav_count_labels:
                self.nav_count_labels[name].count = f'{count:,}'.replace(',', '.')
                self.nav_count_labels[name].update()
        for children in self.nav_child_buttons.values():
            for child_id, (button, _label_key) in children.items():
                count = sum(1 for item in self.items if self.item_matches_section(item, child_id))
                button.count = f'{count:,}'.replace(',', '.')
                button.update()
        self.status_count.setText(self.t('status.count', count=f'{len(self.items):,}'))

    def update_sidebar_state(self, title, description, icon_name=QStyle.StandardPixmap.SP_DirIcon, visible_progress=False):
        self.footer_status_is_version = False
        self.status.setText(title)
        self.status.setToolTip(description)
        self.status.setAccessibleDescription(description)

    def scan_action(self):
        if self.folder and not self.scanning:
            self.connect_folder(self.folder, force=True)
        elif not self.discovering:
            self.discover()

    def navigate(self, name):
        for key,b in self.nav_buttons.items():
            b.setChecked(key == name)
        self.pages.setCurrentIndex(0 if name == 'Início' else 2 if name == 'Instalação' else 1)
        if name in self.sidebar_matchers:
            self.section = name
            self.heading.setText(self.sidebar_labels.get(name, self.t(SECTION_TITLE_KEYS.get(name, 'library'))))
            if name in SECTIONS:
                self.description.setText(self.section_description(name))
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.filter_items()

    def discover(self):
        if self.discovering or self.scanning:
            return
        self.discovering = True
        self.manual_choice = False
        self.detect_button.setEnabled(False)
        self.scan_button.setEnabled(False)
        self.footer_status_is_version = False
        self.update_sidebar_state(self.t('discover.searching'), self.t('discover.checking'), QStyle.StandardPixmap.SP_ComputerIcon, True)
        self.status_indicator.setStyleSheet('background: #e4a72c; border-radius: 4px;')
        self.location_label.setText(self.t('discover.location'))
        self.status.setText(self.t('discover.status'))
        self.progress.setRange(0,0)
        self.progress.setVisible(True)
        self.progress_text.setText(self.t('discover.status'))
        self.progress_text.setVisible(True)
        def work():
            try:
                self.jobs.put(('discovery', discover_folders()))
            except Exception as error:
                self.jobs.put(('discovery_error', str(error)))
        threading.Thread(target=work, daemon=True).start()

    def use_location(self):
        if self.locations.currentData():
            self.connect_folder(Path(self.locations.currentData()))

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, self.t('dialog.choose_folder'), str(self.folder.parent) if self.folder else '')
        if not path:
            return
        valid = normalize_folder(path)
        if not valid:
            self.update_sidebar_state(self.t('folder.invalid'), self.t('folder.invalid.description'), QStyle.StandardPixmap.SP_MessageBoxWarning, False)
            self.status_indicator.setStyleSheet('background: #d74a50; border-radius: 4px;')
            show_app_message(self, self.t('popup.invalid.title'), self.t('popup.invalid.text'), QMessageBox.Icon.Warning)
            return
        self.manual_choice = True
        self.connect_folder(valid)

    def refresh_catalog(self):
        if self.folder and not self.scanning:
            self.connect_folder(self.folder,force=True)

    def connect_folder(self, folder, force=False):
        if self.scanning:
            return
        self.scanning = True
        self.footer_status_is_version = False
        self.folder = folder
        self.items = []
        self.cache.clear()
        self.cache_bytes = 0
        self.filter_items()
        self.folder_field.setText(str(folder.parent))
        self.folder_field.setToolTip(str(folder.parent))
        self.status_folder.setText(str(folder.parent))
        self.scan_button.setEnabled(False)
        self.update_sidebar_state(self.t('scan.title'), self.t('scan.description'), QStyle.StandardPixmap.SP_BrowserReload, True)
        self.status_indicator.setStyleSheet('background: #e4a72c; border-radius: 4px;')
        self.location_label.setText(self.t('scan.connected', folder=folder))
        self.status.setText(self.t('status.scanning'))
        self.home_summary.setText(self.t('scan.waiting'))
        self.progress.setRange(0,0)
        self.progress.setVisible(True)
        self.progress_text.setText(self.t('status.scanning'))
        self.progress_text.setVisible(True)
        def work():
            try:
                def report(n,total,count,item):
                    if n % 50 == 0:
                        self.jobs.put(('progress', (n,total,count)))
                items,_,cached = scan_cached(folder, report,force=force)
                for item in items:
                    _ = item.search_blob
                stamps={}
                for item in items:
                    key=str(item.source_path)
                    if key not in stamps:
                        try:
                            stat=item.source_path.stat()
                            stamps[key]=(stat.st_size,stat.st_mtime_ns)
                        except OSError:
                            stamps[key]='unavailable'
                self.source_stamps=stamps
                try:
                    remember_folder(folder)
                except OSError:
                    pass
                self.jobs.put(('scan', items))
            except Exception as error:
                self.jobs.put(('scan_error', str(error)))
        threading.Thread(target=work, daemon=True).start()

    def filter_items(self):
        needle = self.search.text().casefold().strip()
        self.matches = [i for i in self.items if self.item_matches_section(i, self.section) and (not needle or needle in i.search_blob)]
        mode = self.order.currentIndex()
        self.matches.sort(key=lambda i: (-i.size if mode==1 else i.size if mode==2 else 0, Path(i.relative).name.casefold()))
        self.page = 0
        self.populate()

    def empty_action_clicked(self):
        if self.search.text():
            self.search.clear()
        elif self.items:
            self.navigate('Todos os assets')
        else:
            self.choose_folder()

    def turn_page(self, delta):
        self.page = max(0,min(max(0,(len(self.matches)-1)//self.page_size),self.page+delta))
        self.populate()

    def populate(self):
        self.generation += 1
        self.selection_token += 1
        self.pending_selection = None
        self.current = None
        self.current_data = None
        self.current_image = None
        self.preview_ready = False
        self.toast.hide()
        self.gallery.clear()
        self.gallery_stack.setCurrentIndex(1 if self.matches else 0)
        self.empty_title.setText(self.t('empty.no_results') if self.items else self.t('empty.title'))
        self.empty_description.setText(self.t('empty.no_results.description') if self.items else self.t('empty.description'))
        self.empty_action.setText(self.t('empty.clear') if self.search.text() else self.t('empty.view_all') if self.items else self.t('empty.choose'))
        self.canvas.image = None
        self.canvas.message = self.t('empty.preview') if self.matches else self.t('empty.collection')
        self.canvas.update()
        self.export_button.setEnabled(False)
        self.copy_clipboard_action.setEnabled(False)
        self.play_button.setEnabled(False)
        self.details_button.setEnabled(False)
        self.asset_title.setText(self.t('preview.empty'))
        self.asset_meta.setText(self.t('preview.empty.description'))
        self.close_preview_button.setVisible(False)
        self.update_info_panel(None)
        self.render_queue = []
        for item in self.matches[self.page*self.page_size:(self.page+1)*self.page_size]:
            filename = Path(item.relative).name
            text = filename
            entry = QListWidgetItem(text + '\n' + item.format_label + '  ·  ' + engine.human_size(item.size))
            entry.setData(Qt.ItemDataRole.UserRole,item)
            entry.setToolTip(item.relative)
            entry.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
            entry.setSizeHint(QSize(166, 168))
            self.gallery.addItem(entry)
            if item.format_label in VISUAL:
                cached=self.cache.get(('thumb',str(item.source_path),item.source_offset,item.size))
                if cached is not None and cached[0] is not None:
                    entry.setIcon(QIcon(QPixmap.fromImage(cached[0])))
                else:
                    self.render_queue.append((self.generation,item))
        pages = max(1,(len(self.matches)+self.page_size-1)//self.page_size)
        self.counter.setText(self.t('status.count', count=f'{len(self.matches):,}'))
        self.description.setText(self.t('library.summary', count=f'{len(self.matches):,}', sort=self.order.currentText()))
        self.counter.hide()
        self.page_label.setText(self.t('pager.page', current=self.page + 1, total=pages))
        self.prev.setEnabled(self.page>0)
        self.next.setEnabled(self.page+1<pages)
        self.gallery.reflow()
        QTimer.singleShot(0,self.prioritize_visible)

    def prioritize_visible(self):
        viewport=self.gallery.viewport().rect()
        visible=set()
        for row in range(self.gallery.count()):
            entry=self.gallery.item(row)
            if self.gallery.visualItemRect(entry).intersects(viewport):
                visible.add(id(entry.data(Qt.ItemDataRole.UserRole)))
        self.render_queue.sort(key=lambda task:id(task[1]) not in visible)

    def selected(self, entry, previous=None):
        if entry is None:
            return
        self.selection_token += 1
        self.pending_selection = None
        self.current = entry.data(Qt.ItemDataRole.UserRole)
        self.current_data = None
        self.current_image = None
        self.preview_ready = False
        self.canvas.image = None
        self.canvas.message = self.t('loading.image')
        self.canvas.update()
        self.asset_title.setText(Path(self.current.relative).name)
        self.asset_meta.setText(f'{self.current.format_label} · {engine.human_size(self.current.size)}')
        self.close_preview_button.setVisible(True)
        self.update_info_panel(self.current)
        self.toast.hide()
        self.export_button.setEnabled(False)
        self.copy_clipboard_action.setEnabled(False)
        playable = self.current.format_label in self.playable_formats
        self.play_button.setEnabled(playable)
        self.play_button.setVisible(playable)
        self.details_button.setEnabled(True)
        key=('preview',str(self.current.source_path),self.current.source_offset,self.current.size)
        if key in self.cache:
            self.select_timer.stop()
            self.cache.move_to_end(key)
            self.apply_preview(self.current,self.cache[key])
        else:
            self.select_timer.start()

    def request_preview(self):
        if self.current:
            self.pending_selection = (self.selection_token,self.current)

    def _materialize_media_asset(self, item):
        data = engine.decoded_payload(item)
        if data is None:
            raise ValueError(self.t('player.error'))
        extensions = {'Ogg': '.ogg', 'FLAC': '.flac', 'WAV': '.wav', 'WebM': '.webm'}
        extension = extensions.get(item.format_label, item.signature.extension if item.signature else '.bin')
        root = Path(tempfile.gettempdir()) / 'PartyDashViewer' / 'players'
        root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(f'{item.source_path}|{item.source_offset}|{item.size}'.encode()).hexdigest()[:20]
        target = root / f'{digest}{extension}'
        if not target.is_file() or target.stat().st_size != len(data):
            target.write_bytes(data)
        self._media_temp_files.add(str(target))
        return target

    def play_current_asset(self):
        item = self.current
        if item is None:
            return
        if item.format_label not in self.playable_formats:
            show_app_message(self, self.t('player.title'), self.t('player.unavailable'), QMessageBox.Icon.Information)
            return
        try:
            path = self._materialize_media_asset(item)
            is_video = item.format_label == 'WebM'
            if self.player_dialog is not None:
                self.player_dialog.close()
            self.player_dialog = AssetPlayerDialog(path, is_video, self.i18n, self, temporary=True)
            self.player_dialog.show()
        except Exception as error:
            show_app_message(self, self.t('player.title'), self.t('player.error'), QMessageBox.Icon.Warning)

    def start_render(self, kind, token, item):
        key=(kind,str(item.source_path),item.source_offset,item.size)
        self.render_busy = True
        if key in self.cache:
            result=self.cache[key]
            self.cache.move_to_end(key)
            self.jobs.put(('render',(kind,token,item,result)))
            return
        def work():
            try:
                if kind=='thumb' and token!=self.generation:
                    raise ValueError(self.t('error.selection_replaced'))
                thumbnail_path=None
                if kind=='thumb':
                    stamp=self.source_stamps.get(str(item.source_path),'')
                    identity=f'v2|{item.source_path}|{stamp}|{item.source_offset}|{item.size}|{item.format_label}'
                    digest=hashlib.sha256(identity.encode()).hexdigest()
                    thumbnail_path=settings_path().parent/'thumbnails'/f'{digest}.png'
                    if thumbnail_path.is_file():
                        picture=QImage(str(thumbnail_path))
                        if not picture.isNull():
                            self.jobs.put(('render',(kind,token,item,(picture,'','',None))))
                            return
                data = engine.preview_payload(item)
                if data is None:
                    raise ValueError(self.t('error.preview_unavailable'))
                if (kind=='thumb' and token!=self.generation) or (kind=='preview' and token not in (-1,self.selection_token)):
                    raise ValueError(self.t('error.selection_replaced'))
                image,meta = engine.decode_visual(item,data) if item.format_label in VISUAL else (None,'')
                text = engine.text_from_item(item,data) if kind=='preview' and image is None else None
                if image is not None:
                    image.thumbnail((140,112) if kind=='thumb' else (4096,4096))
                    picture = qt_image(image)
                    if thumbnail_path is not None:
                        try:
                            thumbnail_path.parent.mkdir(parents=True,exist_ok=True)
                            picture.save(str(thumbnail_path),'PNG')
                        except OSError:
                            pass
                else:
                    picture = None
                result = (picture,meta,(text or engine.hex_preview(data))[:100000],None)
            except Exception:
                result = (None, '', '', self.t('error.preview_failed'))
            self.jobs.put(('render',(kind,token,item,result)))
        threading.Thread(target=work,daemon=True).start()

    def drain(self):
        for _ in range(30):
            try:
                kind,result = self.jobs.get_nowait()
            except queue.Empty:
                break
            if kind == 'update_check':
                self.update_check_running = False
                if result and version_tuple(result) > version_tuple(VERSION):
                    self.show_toast(self.t('update.available', version=result))
            elif kind in {'discovery','discovery_error'}:
                self.discovering = False
                self.detect_button.setEnabled(True)
                self.scan_button.setEnabled(True)
                self.progress.setRange(0,100)
                self.progress.setVisible(False)
                self.progress_text.setVisible(False)
                if kind=='discovery_error' or not result:
                    self.update_sidebar_state(self.t('discover.choose'), self.t('discover.choose.description'), QStyle.StandardPixmap.SP_MessageBoxWarning if kind == 'discovery_error' else QStyle.StandardPixmap.SP_DirIcon, False)
                    self.status_indicator.setStyleSheet('background: #d74a50; border-radius: 4px;')
                    self.location_label.setText(self.t('discover.not_found') + (f'\n{self.t("popup.details.source")}: {result}' if kind=='discovery_error' else ''))
                    self.home_summary.setText(self.t('discover.choose'))
                    self.status.setText(self.t('discover.waiting'))
                    self.navigate('Instalação')
                else:
                    self.locations.clear()
                    for folder in result:
                        self.locations.addItem(str(folder.parent),str(folder))
                    if not self.scanning and not self.manual_choice:
                        self.connect_folder(result[0])
            elif kind=='progress':
                n,total,count=result
                self.progress.setRange(0,total)
                self.progress.setValue(n)
                self.progress.setVisible(True)
                self.progress_text.setText(self.t('status.found', count=f'{count:,}'))
                self.progress_text.setVisible(True)
                self.status.setText(self.t('status.scan', n=n, total=total, count=f'{count:,}'))
            elif kind=='scan':
                self.scanning=False
                self.items=result
                self.progress.setRange(0,100)
                self.progress.setValue(100)
                self.progress.setVisible(False)
                self.progress_text.setVisible(False)
                self.scan_button.setEnabled(True)
                self.status_indicator.setStyleSheet('background: #2aa45a; border-radius: 4px;')
                self.rebuild_sidebar_subcategories()
                self.update_sidebar_counts()
                count=sum(i.format_label in VISUAL for i in self.items)
                self.home_summary.setText(self.t('home.summary.ready', count=f'{count:,}'))
                self.footer_status_is_version = True
                self.status.setText(self.version_text())
                self.status_folder.setText(str(self.folder.parent))
                self.filter_items()
                hero=next((i for i in self.items if i.category=='Personagens' and i.format_label=='HIP' and i.size>500000),None)
                if hero and self.current is None:
                    self.pending_selection=(-1,hero)
            elif kind=='scan_error':
                self.scanning=False
                self.progress.setRange(0,100)
                self.progress.setVisible(False)
                self.progress_text.setVisible(False)
                self.scan_button.setEnabled(True)
                self.status_indicator.setStyleSheet('background: #d74a50; border-radius: 4px;')
                self.update_sidebar_state(self.t('scan.failed'), self.t('scan.failed.description'), QStyle.StandardPixmap.SP_MessageBoxWarning, False)
                self.status.setText(self.t('scan.failed.status'))
                show_app_message(self, self.t('popup.scan_error.title'), self.t('scan.failed.description'), QMessageBox.Icon.Warning)
                self.navigate('Instalação')
            elif kind in {'export_done','export_error'}:
                self.export_button.setEnabled(self.current is not None and self.preview_ready)
                if kind=='export_done':
                    self.status_indicator.setStyleSheet('background: #2aa45a; border-radius: 4px;')
                    self.footer_status_is_version = False
                    self.status.setText(self.t('status.exported'))
                    self.show_toast(self.t('export.success.filename', name=Path(result).name))
                else:
                    show_app_message(self, self.t('popup.export_error.title'), result, QMessageBox.Icon.Critical)
            elif kind=='render':
                self.render_busy=False
                mode,token,item,(picture,meta,text,error)=result
                key=(mode,str(item.source_path),item.source_offset,item.size)
                if key not in self.cache and error is None:
                    self.cache[key]=(picture,meta,text,error)
                    self.cache_bytes+=(picture.sizeInBytes() if picture is not None else 0)+len(text)*4
                    while self.cache_bytes>96*1024*1024 or len(self.cache)>600:
                        _,old=self.cache.popitem(last=False)
                        self.cache_bytes-=(old[0].sizeInBytes() if old[0] is not None else 0)+len(old[2])*4
                if mode=='thumb' and token==self.generation and picture is not None:
                    for row in range(self.gallery.count()):
                        entry=self.gallery.item(row)
                        if entry.data(Qt.ItemDataRole.UserRole) is item:
                            entry.setIcon(QIcon(QPixmap.fromImage(picture)))
                            break
                elif mode=='preview' and token==-1:
                    self.hero_canvas.image=picture
                    self.hero_canvas.update()
                elif mode=='preview' and token==self.selection_token and item is self.current:
                    self.apply_preview(item,(picture,meta,text,error))
        if not self.render_busy:
            if self.pending_selection:
                token,item=self.pending_selection
                self.pending_selection=None
                if token==-1 or (token==self.selection_token and item is self.current):
                    self.start_render('preview',token,item)
            elif self.render_queue:
                token,item=self.render_queue.pop(0)
                self.start_render('thumb',token,item)

    def apply_preview(self,item,result):
        picture,meta,text,error=result
        self.canvas.image=picture
        self.canvas.message=error or self.t('preview.unavailable')
        self.canvas.reset_view()
        self.current_image=picture
        self.current_data=text or error
        self.preview_ready=True
        self.asset_meta.setText(meta.split(' · encoding')[0] if meta else f'{item.format_label} · {engine.human_size(item.size)}')
        self.export_button.setText(self.t('export'))
        self.export_button.setEnabled(True)
        self.copy_clipboard_action.setEnabled(picture is not None)
        self.update_info_panel(item)
        for action in self.image_export_actions:
            action.setEnabled(picture is not None)

    def details(self):
        if not self.current:
            return
        item=self.current
        dialog=QDialog(self)
        dialog.setObjectName('detailsDialog')
        dialog.setWindowTitle(self.t('popup.asset_details'))
        dialog.resize(720,520)
        box=QVBoxLayout(dialog)
        box.addWidget(label(Path(item.relative).name,'title'))
        box.addWidget(label(f'{self.category_label(item.category)} · {item.format_label} · {engine.human_size(item.size)}'))
        box.addWidget(label(f"{self.t('popup.details.classification')}: {self.t('asset.classification.automatic')}",'muted'))
        text=QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(f"{self.t('popup.details.path')}: {item.relative}\n{self.t('popup.details.source')}: {item.source_path}\n{self.t('popup.details.offset')}: 0x{item.source_offset:X}\n\n"+(self.current_data or self.t('popup.details.loading')))
        box.addWidget(text)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(self.t('popup.close'))
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        dialog.exec()

    def copy_to_clipboard(self):
        if self.current_image is None or self.current_image.isNull():
            show_app_message(self, self.t('export.copy_clipboard'), self.t('clipboard.unavailable'), QMessageBox.Icon.Information)
            return
        QApplication.clipboard().setImage(self.current_image)
        self.footer_status_is_version = False
        self.status.setText(self.t('clipboard.success'))
        self.show_toast(self.t('clipboard.success'))

    def export(self,mode=None):
        item=self.current
        if item is None or not self.export_button.isEnabled():
            return
        if mode is None:
            mode='png' if self.current_image is not None else 'raw'
        ext={'png':'.png','crop':'.png','webp':'.webp','jpeg':'.jpg','json':'.json'}.get(mode,item.signature.extension if item.signature else '.bin')
        path,_=QFileDialog.getSaveFileName(
            self,
            self.t('export.dialog.title'),
            Path(item.relative).stem + ext,
            self.t('export.dialog.filter', ext=ext),
        )
        if not path:
            return
        self.export_button.setEnabled(False)
        def work():
            try:
                export_asset(item,path,mode)
                self.jobs.put(('export_done',path))
            except Exception:
                self.jobs.put(('export_error', self.t('export.error.details')))
        threading.Thread(target=work,daemon=True).start()

    def help(self):
        show_app_message(self, self.t('popup.help.title'), self.t('popup.help.text'))


def main():
    app=QApplication(sys.argv)
    logo_path = Path(__file__).resolve().parent / 'assets' / 'branding' / 'logo.png'
    if logo_path.is_file():
        app.setWindowIcon(QIcon(str(logo_path)))
    apply_light_theme(app)
    window=Studio(autostart='--self-test' not in sys.argv)
    if '--self-test' in sys.argv:
        window.show()
        app.processEvents()
        window.close()
        return 0
    window.show()
    return app.exec()


if __name__=='__main__':
    raise SystemExit(main())
