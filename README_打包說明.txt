離線繪圖工具 — PyInstaller 打包說明
====================================

檔案（本目錄，之後可整份放進專案根目錄一起用）：
  build_portable_exe.bat   打包腳本（不替你裝套件、不連網安裝）
  launcher.py              啟動入口（供 PyInstaller 打成 exe）

打包工具鏈（系統依賴）
----------------------
  - 使用「系統 Python」執行 PyInstaller（不用專案內 portable_python 來打包）。
  - 請先在系統環境自行裝好 PyInstaller，例如：
      pip install pyinstaller
  - 本 bat 不會 pip install，也不會把套件裝進 portable_python。

產品執行環境（打進包內）
------------------------
  - 預設仍打包完整可執行樹：含 portable_python、app、stats_kb 等。
  - 執行時 launcher 優先用包內 portable_python 跑 server（與點此開始.bat 相同語意）。

使用方式
--------
1. 系統已安裝 Python，且可 import PyInstaller。
2. 專案內已有 portable_python\python.exe（給成品執行用）。
3. 雙擊 build_portable_exe.bat。
   - 放在「..\exe」時：自動找隔壁「離線繪圖工具 v5.0」。
   - 放到專案根時：以該資料夾為專案根。
4. 輸出：
   - bat 在 exe 目錄：  dist_portable_exe\PortablePlotTool\
   - bat 在專案根：    專案\dist_portable_exe\PortablePlotTool\
   內含「離線繪圖工具.exe」與完整執行所需目錄。

預設忽略
--------
  tests / test、build、vendor、cache / __pycache__、.git
  temp、output、workspace（會建空目錄）
  *.md、點此開始.bat（由 exe 取代）
  本打包腳本自身
