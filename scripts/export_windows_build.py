"""Allowlisted source handoff; never include runtime data or an existing profile."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
ROOT=Path(__file__).resolve().parents[1]
FILES=['Cargo.toml','Cargo.lock','README.md','pyproject.toml','requirements.lock','.gitignore',
'apps/desktop/package.json','apps/desktop/package-lock.json','apps/desktop/index.html',
'apps/desktop/tsconfig.json','apps/desktop/vite.config.ts',
'apps/desktop/src-tauri/Cargo.toml','apps/desktop/src-tauri/Cargo.lock','apps/desktop/src-tauri/build.rs',
'apps/desktop/src-tauri/tauri.conf.json','apps/desktop/src-tauri/tauri.installer.conf.json',
'.github/workflows/windows-installer.yml','scripts/build-windows.ps1','scripts/test-windows-install.ps1',
'docs/AUTOMATIC_REVIEW.md','docs/PRODUCTION_AUDIT.md','scripts/build_worker.py','scripts/smoke_packaged_worker.py','scripts/export_windows_build.py','docs/WINDOWS.md']
TREES=['crates/alma-core/src','crates/alma-core/tests','engine','rules','tests',
'apps/desktop/src','apps/desktop/src-tauri/src','apps/desktop/src-tauri/icons','apps/desktop/src-tauri/capabilities','packaging']
ALLOWED={'.rs','.py','.spec','.json','.toml','.lock','.html','.ts','.tsx','.css','.svg','.png','.ico','.icns','.txt','.md','.ps1','.yml'}

def export():
    paths={ROOT/name for name in FILES}
    paths.add(ROOT/'crates/alma-core/Cargo.toml')
    for tree in TREES:
        paths.update(p for p in (ROOT/tree).rglob('*') if p.is_file() and not p.is_symlink()
                     and p.suffix in ALLOWED and '__pycache__' not in p.parts)
    out=ROOT/'release/ALMA-gerar-instalador-no-Windows.zip';out.parent.mkdir(exist_ok=True)
    with ZipFile(out,'w',ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            if not path.is_file() or path.is_symlink():raise ValueError(f'Missing source: {path.relative_to(ROOT)}')
            archive.write(path,'ALMA/'+str(path.relative_to(ROOT)))
    print(out)

if __name__=='__main__':export()
