# -*- mode: python ; coding: utf-8 -*-

# Bundle templates AND the skills/ tree — the agent discovers capabilities by
# scanning skills/<name>/SKILL.md on disk at runtime, so the cards must ship as data.
datas = [('templates', 'templates'), ('skills', 'skills')]
binaries = []
# Skill modules are imported dynamically (importlib), which PyInstaller's static
# analysis can't see — list them (and yaml, used by the loader) as hidden imports.
_SKILL_NAMES = ['check_rank', 'compare_competitors', 'audit_website', 'recommend',
                'list_keywords', 'full_scan', 'clarify', 'help']
hiddenimports = ['yaml'] + [f'skills.{n}.skill' for n in _SKILL_NAMES]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

import PyInstaller.building.api as _pyi_api
_pyi_api.EXE._retry_operation = lambda self, func, *a, **kw: None  # skip timestamp stamping (OSError 22 workaround)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SERP-Agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
