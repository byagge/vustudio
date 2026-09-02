# Проверка серверной обработки Photoshop
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $Root "..")

$py = ".\.venv\Scripts\python"
if (-not (Test-Path $py)) { $py = "python" }

& $py -c @"
from photoshop_server import get_server_status
import json
print(json.dumps(get_server_status().to_dict(), ensure_ascii=False, indent=2))
"@
