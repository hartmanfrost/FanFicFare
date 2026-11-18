#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the FanFicFare FB2 calibre plugin zip, as the image does.

Run it from the repository root with a Python that has zlib and Babel:

    uv run --no-project --with-requirements docker/calibre-plugin/requirements-build.txt \\
        python docker/calibre-plugin/build_plugin.py --out OUTDIR

It works on a temporary copy of the sources, so the checkout is left alone:

1. Compile calibre-plugin/translations/*.po to .mo. Upstream's release zips
   have them; makeplugin.py packs .mo files but does not make them.
2. Run makeplugin.py, unchanged.
3. Rewrite the zip with sorted entries, one fixed timestamp and fixed file
   modes, so the same sources give the same bytes (with the same zlib).
4. Check the zip and write FanFicFare.zip, FanFicFare.zip.sha256 and
   FanFicFare.version to OUTDIR.
"""

import argparse
import ast
import glob
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

SOURCES = ['calibre-plugin', 'fanficfare', 'included_dependencies',
           'makeplugin.py', 'makezip.py']
ZIP_NAME = 'FanFicFare.zip'
# The earliest time a zip entry can carry.
FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)
# Files the plugin can't work without, and the fork's own modules.
REQUIRED = [
    '__init__.py',
    'plugin-import-name-fanficfare_plugin.txt',
    'plugin-defaults.ini',
    'fff_plugin.py',
    'fanficfare/defaults.ini',
    'fanficfare/fb2utils.py',
    'fanficfare/updatedata.py',
    'fanficfare/writers/writer_fb2.py',
]


def compile_translations(transdir):
    """Compile every .po in transdir to a .mo next to it; returns the count."""
    from babel.messages.mofile import write_mo
    from babel.messages.pofile import read_po
    count = 0
    for po in sorted(glob.glob(os.path.join(transdir, '*.po'))):
        with open(po, 'rb') as f:
            catalog = read_po(f, abort_invalid=True)
        with open(po[:-3] + '.mo', 'wb') as f:
            # Like msgfmt: fuzzy translations are left out.
            write_mo(f, catalog, use_fuzzy=False)
        count += 1
    return count


def normalize_zip(src, dst):
    """Copy zip src to dst with sorted entries, a fixed date and mode 0644."""
    with zipfile.ZipFile(src) as zin, \
         zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
        for name in sorted(zin.namelist()):
            info = zipfile.ZipInfo(name, date_time=FIXED_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # unix, so external_attr holds the mode
            info.external_attr = 0o100644 << 16
            zout.writestr(info, zin.read(name))


def plugin_name_version(source):
    """Name and version string of the plugin, from calibre-plugin/__init__.py."""
    tree = ast.parse(source)
    consts = {}
    name = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            if target in ('__version__', 'FB2_FORK_REVISION'):
                consts[target] = ast.literal_eval(node.value)
        if isinstance(node, ast.ClassDef) and node.name == 'FanFicFareBase':
            for item in node.body:
                if isinstance(item, ast.Assign) and len(item.targets) == 1 \
                        and getattr(item.targets[0], 'id', None) == 'name':
                    name = ast.literal_eval(item.value)
    missing = [k for k in ('__version__', 'FB2_FORK_REVISION') if k not in consts]
    if name is None or missing:
        raise SystemExit('calibre-plugin/__init__.py: no %s'
                         % ', '.join((['FanFicFareBase.name'] if name is None else []) + missing))
    version = tuple(consts['__version__']) + (consts['FB2_FORK_REVISION'],)
    return name, '.'.join(str(v) for v in version)


def check_zip(path, po_count):
    """Fail unless the zip is complete; returns 'name version'."""
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise SystemExit('%s: bad CRC in %s' % (path, bad))
        names = set(z.namelist())
        errors = ['missing ' + n for n in REQUIRED if n not in names]
        errors += ['unexpected ' + n for n in sorted(names)
                   if n.endswith(('.pyc', '.po', '.pot')) or '__pycache__' in n]
        mo = [n for n in names if n.startswith('translations/') and n.endswith('.mo')]
        if len(mo) != po_count:
            errors.append('%d translations/*.mo for %d .po files' % (len(mo), po_count))
        if errors:
            raise SystemExit('%s:\n  %s' % (path, '\n  '.join(errors)))
        name, version = plugin_name_version(z.read('__init__.py').decode('utf-8'))
        if name != 'FanFicFare FB2':
            raise SystemExit("%s: plugin name is %r, not 'FanFicFare FB2'" % (path, name))
        return '%s %s' % (name, version), len(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--src', default='.',
                        help='repository root (default: the current directory)')
    parser.add_argument('--out', required=True,
                        help='directory for FanFicFare.zip, .sha256 and .version')
    args = parser.parse_args()
    src = os.path.abspath(args.src)
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='fff-plugin-') as tmp:
        ignore = shutil.ignore_patterns('__pycache__', '*.pyc', '*.mo')
        for item in SOURCES:
            s = os.path.join(src, item)
            if os.path.isdir(s):
                shutil.copytree(s, os.path.join(tmp, item), ignore=ignore)
            else:
                shutil.copy2(s, os.path.join(tmp, item))

        po_count = compile_translations(os.path.join(tmp, 'calibre-plugin', 'translations'))
        subprocess.check_call([sys.executable, 'makeplugin.py'], cwd=tmp)
        normalize_zip(os.path.join(tmp, ZIP_NAME), os.path.join(tmp, 'normalized.zip'))
        label, entries = check_zip(os.path.join(tmp, 'normalized.zip'), po_count)
        shutil.move(os.path.join(tmp, 'normalized.zip'), os.path.join(out, ZIP_NAME))

    with open(os.path.join(out, ZIP_NAME), 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(out, ZIP_NAME + '.sha256'), 'w') as f:
        f.write('%s  %s\n' % (digest, ZIP_NAME))
    with open(os.path.join(out, 'FanFicFare.version'), 'w') as f:
        f.write(label + '\n')
    print('%s: %s, %d entries (%d translations), sha256 %s'
          % (os.path.join(out, ZIP_NAME), label, entries, po_count, digest))


if __name__ == '__main__':
    main()
