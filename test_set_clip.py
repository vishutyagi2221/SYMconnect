import subprocess
import os

temp_path = 'D:/ControlViewer/test.png'
from PIL import Image
Image.new('RGB', (100, 100), color='red').save(temp_path)

cmd = [
    'powershell', '-NoProfile', '-Command',
    f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetImage([System.Drawing.Image]::FromFile('{temp_path}'))"
]
subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW)
os.remove(temp_path)
print('Done!')
