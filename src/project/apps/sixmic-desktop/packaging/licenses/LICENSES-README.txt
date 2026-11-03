How the licenses/ directory is produced and verified
===================================================

Included license texts
  LICENSE-LGPL-3.0.txt    GNU Lesser General Public License v3
  LICENSE-GPL-3.0.txt     GNU General Public License v3 (referenced by LGPLv3)
  PYTHON_LICENSE.txt      Python Software Foundation License v2 (Python 3.12.10)
  PYINSTALLER_LICENSE.txt PyInstaller GPLv2-or-later with bootloader exception
  THIRD_PARTY_LICENSES.txt, QT_PYSIDE6_NOTICE.txt, SIXMIC_PROTOCOL_NOTICE.txt
  LICENSES.sha256         SHA256 of every file in this directory

Provenance (recorded 2026-10-24, Asia/Taipei)
  * LICENSE-LGPL-3.0.txt: fetched over HTTPS from https://www.gnu.org/licenses/lgpl-3.0.txt
    (byte count 7652). This is the canonical GNU text.
  * LICENSE-GPL-3.0.txt: fetched over HTTPS from https://www.gnu.org/licenses/gpl-3.0.txt
    (byte count 35149).
  * PYTHON_LICENSE.txt: copied from the local Python 3.12.10 installation
    C:\Users\sunxi\AppData\Local\Programs\Python\Python312\LICENSE.txt.
  * PYINSTALLER_LICENSE.txt: copied from the build venv package metadata
    apps/sixmic-desktop/.venv/Lib/site-packages/pyinstaller-6.22.3.dist-info/licenses/COPYING.txt.

Verify before release:
  * run: certutil -hashfile <file> SHA256  (or Get-FileHash) and compare with LICENSES.sha256
  * confirm the Qt/PySide6 versions in requirements-lock.txt still match the
    wheels used for the release build
  * confirm the bundle_evidence.json of the release build lists exactly the Qt
    DLLs/QML modules that were shipped

Unresolved licensing items (release blockers for public distribution)
  * The project owner must declare the distribution license for the SixMic3D
    application code and for interfaces/pc_backend_v1 (see
    SIXMIC_PROTOCOL_NOTICE.txt). No license text for them is bundled yet.
  * The PySide6 wheels only ship a commercial-license reference file
    (LicenseRef-Qt-Commercial.txt), not an LGPL text, so the LGPL/GPL texts in
    this directory were fetched from gnu.org and recorded with SHA256 above.
  * Final SixMic3D.exe must be rebuilt after the main-agent UI merge; the
    shipped Qt DLL/QML subset then needs a fresh bundle_evidence.json record
    (the current BackendCheck bundle is Qt-free by design and not representative).
  * This is not legal advice; a license review is required before release.

Build integration
  build_installer.ps1 preflight fails if any of the expected notice/license
  files above are missing, and SixMic3D.iss installs this whole directory to
  <install dir>\licenses.
