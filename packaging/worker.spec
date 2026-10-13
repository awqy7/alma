# PyInstaller onedir, built on the target OS. Chromium is a separate resource tree.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all
root=Path(SPECPATH).parent
all_data=[]; all_binaries=[]; all_hidden=[]
for package in ('playwright','pymupdf','pdfplumber','pypdfium2','pydantic','engine'):
    data,binaries,hidden=collect_all(package)
    all_data+=data;all_binaries+=binaries;all_hidden+=hidden
analysis=Analysis([str(root/'packaging/worker_entry.py')],pathex=[str(root)],
                  binaries=all_binaries,datas=all_data,hiddenimports=all_hidden,
                  excludes=['pytest','tkinter','IPython'],noarchive=False)
pyz=PYZ(analysis.pure)
exe=EXE(pyz,analysis.scripts,[],exclude_binaries=True,name='alma-worker',
        console=True,debug=False,strip=False,upx=False)
collection=COLLECT(exe,analysis.binaries,analysis.datas,strip=False,upx=False,name='worker')
